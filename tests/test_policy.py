"""Per-node tool policy.

Tools are limited by the launcher, not requested in a prompt. Two asymmetries
carry the weight and both are asserted here rather than described: a judge that
can edit what it is judging is not a judge, and the Builder cannot cross its own
outgoing edge.

The guard is the backstop *behind* the allowlist. Testing it is not testing the
allowlist — it is testing that a gap in one is not a gap in both.

Nothing here invokes a model; the gate stays offline. That the PreToolUse hook
actually fires inside a real `claude -p` was measured separately — see
TheHookFiresForReal.
"""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "bin" / "cp-guard"
STATE = ROOT / "state"


def _load(name, path):
    ldr = importlib.machinery.SourceFileLoader(name, str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ldr))
    ldr.exec_module(mod)
    return mod


cpg = _load("cp_guard", GUARD)
cprun = _load("cp_run", ROOT / "bin" / "cp-run")
cp = _load("cp_cli", ROOT / "bin" / "cp")
TYPES = json.loads((ROOT / "nodes" / "node-types.json").read_text())
AGENTS = [n for n, s in TYPES["nodes"].items() if not s.get("verdicts_from_question")]


def hook(event, **env):
    """Run the hook exactly as the CLI would: JSON on stdin, JSON on stdout."""
    r = subprocess.run([sys.executable, str(GUARD), "hook"], input=json.dumps(event),
                       capture_output=True, text=True, env={**os.environ, **env})
    return json.loads(r.stdout), r


def decision(out):
    return out["hookSpecificOutput"]["permissionDecision"]


class TheTwoAsymmetries(unittest.TestCase):
    def test_the_reviewer_cannot_edit_what_it_is_judging(self):
        for tool in ("Edit", "Write", "NotebookEdit"):
            ok, why = cpg.decide("reviewer", tool)
            self.assertFalse(ok, f"reviewer was allowed {tool}: {why}")

    def test_the_builder_cannot_cross_its_own_outgoing_edge(self):
        """commit is an edge, merge is an edge, closing the issue is an edge.
        This is where the rule the whole graph rests on stops being rhetorical."""
        for cmd in ("git merge main", "git push origin main", "br close cp-x",
                    "git commit -m x"):
            ok, why = cpg.decide("builder", "Bash", cmd)
            self.assertFalse(ok, f"builder was allowed {cmd!r}: {why}")

    def test_the_builder_can_still_do_its_job(self):
        for cmd in ("./verify --fast", "git add bin/cp", "git diff", "git status"):
            ok, why = cpg.decide("builder", "Bash", cmd)
            self.assertTrue(ok, f"builder was denied {cmd!r}: {why}")
        self.assertTrue(cpg.decide("builder", "Edit")[0])


class DenyByDefault(unittest.TestCase):
    def test_a_tool_nobody_listed_is_refused(self):
        """The default branch is the one that matters. A tool nobody thought
        about is refused, not permitted."""
        ok, why = cpg.decide("reviewer", "WebFetch")
        self.assertFalse(ok)
        self.assertIn("deny by default", why)

    def test_an_unlisted_bash_command_is_refused(self):
        self.assertFalse(cpg.decide("reviewer", "Bash", "curl https://example.com")[0])

    def test_the_tools_that_grant_tools_are_denied_everywhere(self):
        """Measured rather than theorised. A Reviewer told to edit a file did
        not reach for Edit — it reached for ToolSearch, to go and get Edit.
        Deny-by-default caught that, but only because nobody had listed
        ToolSearch, and that kind of safety evaporates the first time an
        allowlist is widened in a hurry."""
        for n in AGENTS:
            for esc in ("ToolSearch", "Task", "Agent"):
                ok, why = cpg.decide(n, esc)
                self.assertFalse(ok, f"{n} was allowed {esc}: {why}")
                self.assertIn("denied", why, f"{n}/{esc} is only refused by default")

    def test_every_node_can_emit_a_verdict(self):
        """Without this a node has no way to advance at all — it would be
        isolated into uselessness rather than into safety."""
        for n in AGENTS:
            ok, why = cpg.decide(n, "Bash", "cp-verdict emit --node x --verdict done")
            self.assertTrue(ok, f"{n} cannot call cp-verdict: {why}")


class MatchingIsNotStringPrefixing(unittest.TestCase):
    def test_a_compound_command_cannot_smuggle_a_second_call(self):
        """`git diff && rm -rf .` is the classic bypass of a prefix match."""
        self.assertTrue(cpg.decide("reviewer", "Bash", "git diff")[0])
        for cmd in ("git diff && rm -rf .", "git diff; git push", "git diff | tee /tmp/x",
                    "git diff $(git push)", "git diff `rm -rf .`"):
            self.assertFalse(cpg.decide("reviewer", "Bash", cmd)[0],
                             f"{cmd!r} was allowed")

    def test_a_denied_segment_anywhere_refuses_the_whole_call(self):
        self.assertFalse(cpg.decide("builder", "Bash", "git add . && git push")[0])

    def test_matching_respects_token_boundaries(self):
        """`git diff` must not grant `git difftool`."""
        self.assertFalse(cpg.decide("reviewer", "Bash", "git difftool")[0])

    def test_an_empty_command_is_not_a_free_pass(self):
        self.assertFalse(cpg.decide("reviewer", "Bash", "")[0])


class TheHookIsTheBackstop(unittest.TestCase):
    def test_a_denied_call_is_blocked(self):
        out, _ = hook({"tool_name": "Edit", "tool_input": {"file_path": "a.py"}},
                      CP_NODE="reviewer", CP_TOKEN="t-pol", CP_FACTORY="control-plane")
        self.assertEqual(decision(out), "deny")

    def test_an_allowed_call_passes(self):
        out, _ = hook({"tool_name": "Bash", "tool_input": {"command": "git diff --stat"}},
                      CP_NODE="reviewer", CP_TOKEN="t-pol", CP_FACTORY="control-plane")
        self.assertEqual(decision(out), "allow")

    def test_a_guard_that_does_not_know_its_node_refuses(self):
        """A guard that does not know what it is guarding cannot claim a call is
        safe. It must not fall through to allow."""
        env = {k: v for k, v in os.environ.items() if k != "CP_NODE"}
        r = subprocess.run([sys.executable, str(GUARD), "hook"],
                           input=json.dumps({"tool_name": "Edit"}),
                           capture_output=True, text=True, env=env)
        self.assertEqual(decision(json.loads(r.stdout)), "deny")


class AViolationIsASignal(unittest.TestCase):
    def test_a_blocked_call_lands_on_the_transition_log(self):
        hook({"tool_name": "Edit", "tool_input": {"file_path": "server.ts"}},
             CP_NODE="reviewer", CP_TOKEN="t-sig", CP_FACTORY="control-plane")
        rows = [r for r in cp.log_rows() or []
                if r.get("kind") == "violation" and r["token"] == "t-sig"]
        self.assertTrue(rows, "a Reviewer that tried to call Edit left no trace")
        self.assertEqual(rows[-1]["tool"], "Edit")
        self.assertEqual(rows[-1]["from"], "reviewer")

    def test_a_violation_is_not_counted_as_a_crossing(self):
        """It happened AT a node, not between two. Counting it as a crossing
        would corrupt the one record that reconstructs a token's path."""
        before = cp.runs()
        hook({"tool_name": "Write", "tool_input": {"file_path": "x"}},
             CP_NODE="reviewer", CP_TOKEN="t-sig2", CP_FACTORY="control-plane")
        self.assertEqual(cp.runs(), before)

    def test_the_panel_surfaces_it(self):
        hook({"tool_name": "Edit", "tool_input": {"file_path": "x"}},
             CP_NODE="reviewer", CP_TOKEN="t-sig3", CP_FACTORY="control-plane")
        r = subprocess.run([sys.executable, str(ROOT / "bin" / "cp"), "status"],
                           capture_output=True, text=True)
        self.assertIn("BLOCKED TOOL CALLS", r.stdout)
        self.assertIn("reviewer", r.stdout)


    def test_the_served_panel_payload_carries_it(self):
        """`cp status` is one panel; the browser is the other. A signal that
        reaches only the terminal is not surfaced."""
        hook({"tool_name": "Edit", "tool_input": {"file_path": "x"}},
             CP_NODE="reviewer", CP_TOKEN="t-sig4", CP_FACTORY="control-plane")
        state = cp.api_state()
        self.assertIn("violations", state)
        self.assertTrue(any(v["token"] == "t-sig4" for v in state["violations"]))

    def test_the_panel_never_counts_a_violation_as_a_crossing(self):
        """The transitions list feeds the journey and the graph. A violation in
        it that is not marked would draw a hop that never happened."""
        state = cp.api_state()
        for r in state["transitions"]:
            if r.get("kind") == "violation":
                self.assertIsNone(r["to"], "a violation must not name a destination")


class ThePolicyLivesInTheContract(unittest.TestCase):
    def test_every_agent_node_declares_one(self):
        for n in AGENTS:
            self.assertIn("tools", TYPES["nodes"][n],
                          f"{n} has no tool policy — deny by default has nothing to work from")

    def test_the_launcher_carries_the_policy_not_a_hand_written_list(self):
        argv = cprun.build_launch_argv("reviewer", "/tmp/m.json",
                                       pathlib.Path("/tmp/wt"), TYPES)
        allowed = argv[argv.index("--allowedTools") + 1].split(",")
        denied = argv[argv.index("--disallowedTools") + 1].split(",")
        self.assertEqual(allowed, TYPES["nodes"]["reviewer"]["tools"]["allowed"])
        self.assertEqual(denied, TYPES["nodes"]["reviewer"]["tools"]["denied"])

    def test_the_settings_file_is_generated_from_the_policy(self):
        """Two hand-maintained copies of one rule is two rules, and the drift
        only shows up the day one of them was the lock that mattered."""
        cprun.build_launch_argv("reviewer", "/tmp/m.json", pathlib.Path("/tmp/wt"), TYPES)
        gen = json.loads((STATE / "settings-reviewer.json").read_text())
        cmd = gen["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("cp-guard", cmd)

    def test_the_node_env_names_the_node(self):
        """CP_NODE is load-bearing: without it the hook refuses every call."""
        env = cprun.env_for_node({"token": "t-x", "factory": "control-plane",
                                  "run": 1, "seen": {}}, "reviewer")
        self.assertEqual(env["CP_NODE"], "reviewer")


class TheHookFiresForReal(unittest.TestCase):
    """Measured once against the installed CLI, on 2026-08-21, rather than
    assumed from the settings shape.

    A reviewer-policy node launched with the generated --settings and CP_NODE
    set, asked to edit a file, was denied by the hook and left a violation row
    on the transition log. Notably it did not attempt Edit — it attempted
    ToolSearch, to go and load Edit.

    That check needs the network and an authenticated CLI, so it is not part of
    the gate: the gate must run offline and cannot depend on a model being
    reachable. The per-node-type version of it is tracked as
    cp-live-policy-check-tas. What is asserted here is the part that can be —
    the settings the launcher generates are the shape the CLI reads.
    """

    def test_the_generated_settings_are_a_valid_hook_config(self):
        s = cpg.settings_for("reviewer")
        entry = s["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "*")
        self.assertEqual(entry["hooks"][0]["type"], "command")
        self.assertTrue(pathlib.Path(entry["hooks"][0]["command"].split()[0]).exists())


def tearDownModule():
    log = STATE / "transitions.ndjson"
    if log.exists():
        keep = [l for l in log.read_text().splitlines()
                if l.strip() and not json.loads(l)["token"].startswith("t-")]
        log.write_text("\n".join(keep) + ("\n" if keep else ""))


if __name__ == "__main__":
    unittest.main()
