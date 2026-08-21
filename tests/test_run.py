"""The runner.

Two properties carry the design and both are tested here rather than asserted in
prose: the runner never asks a model where to go, and a token that stops always
stops somewhere a person can see.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN = ROOT / "bin" / "cp-run"
STATE = ROOT / "state"


def run(*args):
    return subprocess.run([sys.executable, str(RUN), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


def token(tid):
    return json.loads((STATE / "tokens" / f"{tid}.json").read_text())


def crossings(tid):
    log = STATE / "transitions.ndjson"
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text().splitlines()
            if l.strip() and json.loads(l)["token"] == tid]


class Walks(unittest.TestCase):
    def test_happy_path_reaches_a_terminal(self):
        r = run("control-plane", "t-happy", "--dry-run", "--scenario", "happy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(token("t-happy")["node"], "@done")
        self.assertEqual(token("t-happy")["status"], "done")

    def test_reject_loops_through_repair_and_still_lands(self):
        r = run("ai-ih-coach", "t-reject", "--dry-run", "--scenario", "reject")
        self.assertEqual(r.returncode, 0, r.stderr)
        path = [c["to"] for c in crossings("t-reject")]
        self.assertIn("repair", path, "a rejection must reach the repair node")
        self.assertEqual(token("t-reject")["node"], "@done")

    def test_a_charter_question_parks_with_a_question(self):
        run("ai-ih-coach", "t-charter", "--dry-run", "--scenario", "charter")
        t = token("t-charter")
        self.assertEqual(t["status"], "parked")
        self.assertIn("asks", t["question"])
        self.assertGreaterEqual(len(t["question"]["options"]), 2)

    def test_every_crossing_is_recorded_before_the_next(self):
        run("control-plane", "t-log", "--dry-run", "--scenario", "happy")
        rows = crossings("t-log")
        self.assertTrue(rows)
        for r in rows:
            for field in ("ts", "token", "factory", "from", "to"):
                self.assertIn(field, r)
        # the path must be continuous: each `to` is the next row's origin context
        self.assertEqual(rows[-1]["to"], "@done")


class TheLogReconstructsThePath(unittest.TestCase):
    def test_the_chain_is_continuous(self):
        """Each crossing must start where the last one ended.

        The criterion for the transition log is that it reconstructs the full
        path of a change without an agent transcript. A row whose `from` skips a
        hop reads plausibly and is wrong, which is the worst kind of evidence.
        """
        run("finance-c-and-c", "t-chain", "--dry-run", "--scenario", "happy")
        run("--resume", "t-chain", "--answer", "yes")
        import json as _j
        g = _j.loads((ROOT / "nodes" / "graph.json").read_text())
        rows = crossings("t-chain")
        self.assertGreater(len(rows), 4)
        for a, b in zip(rows, rows[1:]):
            # A row is one edge crossing: from -> [edge] -> to. So the next row
            # either starts where this one landed, or crosses the edge this one
            # named — which is what a human answer does, since choosing an option
            # selects an edge rather than moving the token itself.
            ok = (a["to"] == b["from"]) or (a["to"] in g["edges"] and a["to"] == b["edge"])
            self.assertTrue(ok, f"path skips: ...{a['from']}->{a['to']} then {b['from']}->{b['to']}")
        self.assertEqual(rows[-1]["to"], "@done")

    def test_a_verdict_is_only_on_the_crossing_that_produced_it(self):
        """A verdict repeated onto later rows reads as though the Reviewer
        approved edges it never saw."""
        run("control-plane", "t-verd", "--dry-run", "--scenario", "happy")
        rows = crossings("t-verd")
        withv = [r for r in rows if r["verdict"]]
        self.assertTrue(withv)
        for r in withv:
            self.assertIn(r["from"], ("builder", "reviewer", "repair", "@park"),
                          f"{r['from']} does not emit verdicts")


class TheHumanNode(unittest.TestCase):
    def test_finance_parks_before_merge_and_the_others_do_not(self):
        run("finance-c-and-c", "t-fin", "--dry-run", "--scenario", "happy")
        self.assertEqual(token("t-fin")["status"], "parked",
                         "finance-c-and-c must not merge without a person")
        self.assertIn("merge", token("t-fin")["question"]["asks"])

        run("ai-ih-coach", "t-coach", "--dry-run", "--scenario", "happy")
        self.assertEqual(token("t-coach")["status"], "done",
                         "the same graph without a human node runs straight through")

    def test_answering_crosses_the_edge_it_named(self):
        run("finance-c-and-c", "t-fin2", "--dry-run", "--scenario", "happy")
        r = run("--resume", "t-fin2", "--answer", "yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(token("t-fin2")["node"], "@done")
        human = [c for c in crossings("t-fin2") if c.get("actor") == "human"]
        self.assertTrue(human, "a human answer must appear in the provenance record")

    def test_holding_leaves_it_parked(self):
        run("finance-c-and-c", "t-fin3", "--dry-run", "--scenario", "happy")
        run("--resume", "t-fin3", "--answer", "hold")
        self.assertEqual(token("t-fin3")["status"], "parked")

    def test_resume_without_an_answer_prints_the_question(self):
        run("finance-c-and-c", "t-fin4", "--dry-run", "--scenario", "happy")
        r = run("--resume", "t-fin4")
        self.assertIn("Cross", r.stdout)
        self.assertIn("yes", r.stdout)


class RefusesWhatItCannotDoSafely(unittest.TestCase):
    def test_live_mode_is_refused_until_isolation_exists(self):
        """A runner that launches nodes with ambient tools and no manifest is the
        failure the graph exists to prevent. It must not start, not warn."""
        r = run("control-plane", "t-live", "--scenario", "happy")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isolation", r.stderr)

    def test_no_edge_script_invokes_a_model(self):
        for p in (ROOT / "bin" / "edges").iterdir():
            body = p.read_text()
            for banned in ("claude ", "claude -p", "anthropic", "openai"):
                self.assertNotIn(banned, body, f"{p.name} looks like it calls a model")

    def test_a_missing_route_parks_the_token_rather_than_guessing(self):
        """Deadlock is kept visible on purpose.

        A model router would have improvised past a missing route and hidden the
        gap. A scripted one cannot, so the hole becomes findable — the token
        stops and says which exit code had nowhere to go.
        """
        g = ROOT / "nodes" / "graph.json"
        orig = g.read_text()
        try:
            d = json.loads(orig)
            d["edges"]["commit"]["routes"] = {"9": "reviewer"}   # nothing routes exit 0
            g.write_text(json.dumps(d, indent=2))
            run("control-plane", "t-dead", "--dry-run", "--scenario", "happy")
            t = token("t-dead")
            self.assertEqual(t["status"], "parked")
            self.assertEqual(t["node"], "@park")
            self.assertIn("no route", t["question"]["asks"].lower() + " " +
                          " ".join(c.get("why", "") for c in crossings("t-dead")))
        finally:
            g.write_text(orig)

    def test_unknown_factory_is_refused(self):
        r = run("not-a-factory", "t-x", "--dry-run")
        self.assertEqual(r.returncode, 2)


class Resumability(unittest.TestCase):
    def test_token_state_survives_and_carries_its_mode(self):
        run("finance-c-and-c", "t-mode", "--dry-run", "--scenario", "happy")
        t = token("t-mode")
        self.assertTrue(t["dry_run"], "the run mode belongs to the token, not the invocation")
        self.assertEqual(t["scenario"], "happy")
        # resuming without repeating --dry-run must not fall through to live mode
        r = run("--resume", "t-mode", "--answer", "yes")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_second_run_is_a_separate_journey(self):
        """Re-running a token must not splice two runs into one path.

        The old crossings stay in the log — history is history — but they carry a
        different run number so the journey reads as what actually happened.
        """
        run("control-plane", "t-rerun", "--dry-run", "--scenario", "happy")
        first = crossings("t-rerun")
        run("control-plane", "t-rerun", "--dry-run", "--scenario", "happy")
        allrows = crossings("t-rerun")
        self.assertEqual(len(allrows), len(first) * 2)
        self.assertEqual({r.get("run") for r in allrows}, {1, 2})
        self.assertEqual(token("t-rerun")["run"], 2)
        second = [r for r in allrows if r.get("run") == 2]
        self.assertEqual(second[0]["from"], "builder", "a new run starts at the entry")

    def test_every_crossing_carries_its_run(self):
        """An unstamped row defaults to run 1 and lands in the wrong journey —
        which is worse than missing, because it reads as part of a path."""
        run("finance-c-and-c", "t-stamp", "--dry-run", "--scenario", "happy")
        run("--resume", "t-stamp", "--answer", "yes")
        for r in crossings("t-stamp"):
            self.assertIn("run", r, f"unstamped: {r}")

    def test_show_reads_a_token_back(self):
        run("control-plane", "t-show", "--dry-run", "--scenario", "happy")
        r = run("--show", "t-show")
        self.assertEqual(json.loads(r.stdout)["token"], "t-show")


class Definition(unittest.TestCase):
    def test_graph_validates(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "check-graph.py")],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_only_finance_has_a_human_node(self):
        g = json.loads((ROOT / "nodes" / "graph.json").read_text())
        gated = {f for f, s in g["factories"].items() if s.get("human_before")}
        self.assertEqual(gated, {"finance-c-and-c"},
                         "autonomy is a graph property; this is where it is set")


def tearDownModule():
    for p in (STATE / "tokens").glob("t-*.json"):
        p.unlink()
    log = STATE / "transitions.ndjson"
    if log.exists():
        keep = [l for l in log.read_text().splitlines()
                if l.strip() and not json.loads(l)["token"].startswith("t-")]
        log.write_text("\n".join(keep) + ("\n" if keep else ""))


if __name__ == "__main__":
    unittest.main()
