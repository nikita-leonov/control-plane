"""The edge contract.

An edge is a script whose exit code selects the outgoing branch, and which is a
pure function of (node result, repo at a known commit). Everything the graph
claims — resumability, replay, a router with no model in it — rests on that
being true rather than intended.

The load-bearing test is test_two_is_never_confused_with_one. A repair node
handed a broken edge would "fix" code that was never the problem, and would look
busy doing it.
"""

import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EDGES = ROOT / "bin" / "edges"
STATE = ROOT / "state"
GRAPH = json.loads((ROOT / "nodes" / "graph.json").read_text())


def run_edge(script, **env):
    return subprocess.run([str(EDGES / script)], capture_output=True, text=True,
                          env={**os.environ, "CP_EDGE": script, **env})


def sh(body, **env):
    """Run a snippet against the contract library, as a real edge would."""
    src = f'. "{EDGES / "_lib.sh"}"\n{body}\n'
    return subprocess.run(["bash", "-c", src], capture_output=True, text=True,
                          env={**os.environ, "CP_EDGE": "probe", **env})


class ExitCodesAreTheInterface(unittest.TestCase):
    def test_the_three_verbs_mean_what_they_say(self):
        self.assertEqual(sh('edge_ok').returncode, 0)
        self.assertEqual(sh('edge_failed "a check failed"').returncode, 1)
        self.assertEqual(sh('edge_broken "no git"').returncode, 2)

    def test_two_is_never_confused_with_one(self):
        """Not just different numbers — distinguishable output. A broken edge
        that reads like a failing one gets retried, and retrying a broken edge
        is how a factory spends an afternoon on nothing."""
        failed, broken = sh('edge_failed "x"'), sh('edge_broken "x"')
        self.assertNotEqual(failed.returncode, broken.returncode)
        self.assertIn("BROKEN", broken.stderr)
        self.assertNotIn("BROKEN", failed.stderr)

    def test_a_missing_input_is_broken_not_failed(self):
        """Getting this backwards routes a missing input to a repair node, which
        cannot possibly fix it."""
        self.assertEqual(sh('edge_needs CP_NOPE').returncode, 2)

    def test_a_missing_node_result_is_broken_not_failed(self):
        r = sh('edge_result payload.files', CP_RESULT="/nonexistent/result.json")
        self.assertEqual(r.returncode, 2)


class Replay(unittest.TestCase):
    def test_crossing_the_same_edge_twice_selects_the_same_branch(self):
        """The property that makes recorded-result replay worth anything. If an
        edge is not a function of its input, a replayed run proves nothing about
        the run it is replaying."""
        env = {"CP_TOKEN": "t-replay", "CP_FACTORY": "control-plane",
               "CP_RESULT": str(STATE / "verdict.json"), "CP_BASE": "0" * 40,
               "CP_WORKTREE": "/tmp/cp-worktrees/control-plane/t-replay"}
        for name, spec in GRAPH["edges"].items():
            if spec.get("cwd") == "factory":
                continue                     # runs ./verify; covered by that repo's gate
            script = pathlib.Path(spec["run"][0]).name
            first = run_edge(script, **env, CP_EDGE=name)
            second = run_edge(script, **env, CP_EDGE=name)
            self.assertEqual(first.returncode, second.returncode,
                             f"{name} selected a different branch on replay")
            self.assertIn(str(first.returncode), spec["routes"],
                          f"{name} exited {first.returncode}, which nothing routes")

    def test_an_edge_is_told_its_input_rather_than_finding_it(self):
        """CP_RESULT and CP_BASE arrive from the runner. A script that resolved
        HEAD itself would be a different function on every crossing."""
        lib = (EDGES / "_lib.sh").read_text()
        for var in ("CP_RESULT", "CP_BASE", "CP_WORKTREE"):
            self.assertIn(var, lib)

    def test_the_runner_records_the_base_commit_once(self):
        subprocess.run([sys.executable, str(ROOT / "bin" / "cp-run"), "control-plane",
                        "t-base", "--dry-run", "--scenario", "happy"],
                       capture_output=True, text=True, cwd=str(ROOT))
        tok = json.loads((STATE / "tokens" / "t-base.json").read_text())
        self.assertIn("base", tok)


class NoModelOnAnEdge(unittest.TestCase):
    def test_no_edge_script_mentions_a_model(self):
        """An edge that asks a model is a router that is not deterministic, which
        is the one thing this design exists to remove."""
        for p in EDGES.iterdir():
            if not p.is_file():
                continue
            body = p.read_text().lower()
            for banned in ("claude", "anthropic", "openai", "gpt-"):
                self.assertNotIn(banned, body, f"{p.name} looks like it calls a model")

    def test_the_checker_catches_one(self):
        for name in ("probe-tmp", "_probe_lib_tmp"):
            probe = EDGES / name
            probe.write_text('#!/usr/bin/env bash\nclaude -p hi\n')
            probe.chmod(0o755)
            try:
                r = subprocess.run([sys.executable, str(ROOT / "tools" / "check-edges.py")],
                                   capture_output=True, text=True, cwd=str(ROOT))
                self.assertEqual(r.returncode, 1, f"{name} was not caught")
                self.assertIn("mentions a model", r.stderr)
            finally:
                probe.unlink()

    def test_the_shared_library_is_scanned_too(self):
        """It is sourced by every edge, so a model call there is a model call on
        all of them — and it is the file a reference-following check would skip."""
        checker = (ROOT / "tools" / "check-edges.py").read_text()
        self.assertIn("EDGES.iterdir()", checker)


class TheContractIsDeclared(unittest.TestCase):
    def test_every_edge_declares_what_it_can_return(self):
        for name, spec in GRAPH["edges"].items():
            self.assertTrue(spec.get("exits"),
                            f"{name} declares no exits — nothing says what it can return")

    def test_every_declared_exit_has_a_route(self):
        for name, spec in GRAPH["edges"].items():
            for code in spec["exits"]:
                self.assertIn(str(code), spec["routes"],
                              f"{name} can exit {code} but nothing routes it")

    def test_every_edge_script_shares_one_idea_of_an_exit_code(self):
        for name, spec in GRAPH["edges"].items():
            if spec.get("cwd") == "factory":
                continue
            body = (ROOT / spec["run"][0]).read_text()
            self.assertIn("_lib.sh", body,
                          f"{name} does not source the contract it exits by")

    def test_the_checker_is_in_the_gate(self):
        """A contract nothing runs is a comment."""
        self.assertIn("check-edges.py", (ROOT / "verify").read_text())


def tearDownModule():
    for p in (STATE / "tokens").glob("t-*.json"):
        p.unlink()
    for p in STATE.glob("manifest-t-*.json"):
        p.unlink()
    log = STATE / "transitions.ndjson"
    if log.exists():
        keep = [l for l in log.read_text().splitlines()
                if l.strip() and not json.loads(l)["token"].startswith("t-")]
        log.write_text("\n".join(keep) + ("\n" if keep else ""))


if __name__ == "__main__":
    unittest.main()
