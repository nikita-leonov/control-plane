"""The panel.

The test that matters here is test_ready_agrees_with_beads. An earlier version of
cp computed readiness itself by walking `blocks` edges, and disagreed with
`br ready` on two ai-ih-coach issues — beads has semantics around epics and
started children that the edge data alone does not show. A panel that reports
different numbers than the tracker it is reporting on is worse than no panel: it
is a confident-looking board built on a stale edge.
"""

import importlib.machinery
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CP = ROOT / "bin" / "cp"

_loader = importlib.machinery.SourceFileLoader("cp", str(CP))
cp = importlib.util.module_from_spec(importlib.util.spec_from_loader("cp", _loader))
_loader.exec_module(cp)


def has_backlog(f):
    return (cp.PROJECTS / f / ".beads" / "issues.jsonl").exists()


class ReadyMatchesTheTracker(unittest.TestCase):
    def test_ready_agrees_with_beads(self):
        if not shutil.which("br"):
            self.skipTest("br not on PATH")
        checked = 0
        for f in cp.FACTORIES:
            if not has_backlog(f):
                continue
            rs = cp.ready_ids(f)
            if rs is None:
                continue
            out = subprocess.run(["br", "ready", "--json"], cwd=str(cp.PROJECTS / f),
                                 capture_output=True, text=True, timeout=30)
            d = json.loads(out.stdout)
            rows = d if isinstance(d, list) else d.get("issues", d.get("data", []))
            self.assertEqual(rs, {x["id"] for x in rows}, f"{f}: panel disagrees with br")
            checked += 1
        self.assertGreater(checked, 0, "no backlog was actually compared")

    def test_classify_only_reads_status_fields(self):
        """Everything except `ready` must be a field read, never a computation."""
        rows = [{"id": "a", "status": "closed"}, {"id": "b", "status": "in_progress"},
                {"id": "c", "status": "open"}, {"id": "d", "status": "open"}]
        ready, wip, waiting, done = cp.classify(rows, {"c"})
        self.assertEqual([x["id"] for x in ready], ["c"])
        self.assertEqual([x["id"] for x in wip], ["b"])
        self.assertEqual([x["id"] for x in waiting], ["d"])
        self.assertEqual([x["id"] for x in done], ["a"])

    def test_unreachable_tracker_is_not_a_zero(self):
        """`ready_ids` returning None must not become a confident 0 on the board."""
        ready, _, waiting, _ = cp.classify([{"id": "a", "status": "open"}], None)
        self.assertEqual(ready, [])
        self.assertEqual(len(waiting), 1, "an unknown count must not read as 'not ready'")


class BacklogPresence(unittest.TestCase):
    def test_no_backlog_is_none_not_empty(self):
        """A repo with no beads is a different thing from one with an empty
        backlog, and the board must be able to tell them apart."""
        for f in cp.FACTORIES:
            got = cp.issues(f)
            if has_backlog(f):
                self.assertIsInstance(got, list)
            else:
                self.assertIsNone(got, f"{f} has no .beads but did not report None")


class Rendering(unittest.TestCase):
    def test_pad_measures_visible_width(self):
        """str.ljust counts escape bytes and silently misaligns coloured columns."""
        coloured = "\033[32mgreen\033[0m"
        self.assertEqual(len(cp.strip(coloured)), 5)
        self.assertEqual(len(cp.strip(cp.pad(coloured, 12))), 12)
        self.assertEqual(cp.pad("ab", 5), "ab   ")

    def test_status_runs_clean(self):
        r = subprocess.run([sys.executable, str(CP), "status"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in cp.FACTORIES:
            self.assertIn(f, r.stdout)

    def test_status_says_no_node_has_run(self):
        """While there is no runner, the board must say so rather than render an
        empty section as though it were a quiet one."""
        r = subprocess.run([sys.executable, str(CP), "status"], capture_output=True, text=True)
        self.assertIn("no runner", r.stdout.lower())

    def test_decisions_names_its_own_proxy(self):
        r = subprocess.run([sys.executable, str(CP), "decisions"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("blocked-on-nikita", r.stdout)

    def test_work_on_a_repo_without_a_backlog_explains_itself(self):
        r = subprocess.run([sys.executable, str(CP), "work", "faceoff-finder"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no backlog", r.stdout.lower())

    def test_unknown_command_exits_2(self):
        r = subprocess.run([sys.executable, str(CP), "wat"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
