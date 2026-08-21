"""The backlog stays about how work moves.

If it changes how work moves it belongs here; if it changes what a product does
it belongs in that factory's tracker. That rule was in README.md for a while and
eroded anyway — three faceoff-finder issues accumulated here, because a factory
with no tracker of its own leaves its work nowhere else to go. Hence a check,
and hence tests for the check.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECK = ROOT / "tools" / "check-backlog-scope.py"
PROJECTS = pathlib.Path("/mnt/projects")


def check(issues):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for o in issues:
            f.write(json.dumps(o) + "\n")
        path = f.name
    try:
        return subprocess.run([sys.executable, str(CHECK), path],
                              capture_output=True, text=True, cwd=str(ROOT))
    finally:
        pathlib.Path(path).unlink()


def issue(**kw):
    base = {"id": "cp-x-aaa", "title": "t", "description": "d",
            "status": "open", "labels": ["program"]}
    base.update(kw)
    return base


class TheRule(unittest.TestCase):
    def test_the_real_backlog_passes(self):
        r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                           cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_issue_about_a_factorys_insides_is_flagged(self):
        r = check([issue(description="The bug is in tools/lint_ratchet.py")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("faceoff-finder", r.stderr)

    def test_an_unclassified_issue_is_flagged(self):
        """An issue nobody labelled is an issue nobody classified, and
        classification is the entire subject of this check."""
        r = check([issue(labels=[])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no scope label", r.stderr)

    def test_infrastructure_work_passes(self):
        r = check([issue(description="The runner should persist tokens in state/")])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_closed_issue_is_not_policed(self):
        """History is history. The rule governs what is still to be done."""
        r = check([issue(status="closed", labels=[],
                         description="something in tools/lint_ratchet.py")])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_cross_factory_is_an_explicit_visible_claim(self):
        """Some infrastructure genuinely has to name a factory's insides — the
        escape hatch lives in the backlog where it can be seen, not in the
        checker where it cannot."""
        r = check([issue(labels=["program", "cross-factory"],
                         description="Set beads up in faceoff-finder, from FINDINGS.md")])
        self.assertEqual(r.returncode, 0, r.stderr)


class TheExemptionExpires(unittest.TestCase):
    """A permanent exemption is the rule deleted slowly."""

    def test_it_holds_only_while_that_factory_has_no_tracker(self):
        i = issue(labels=["program", "moves-to-faceoff-finder"],
                  description="about tools/lint_ratchet.py")
        has_tracker = (PROJECTS / "faceoff-finder" / ".beads" / "issues.jsonl").exists()
        r = check([i])
        if has_tracker:
            self.assertEqual(r.returncode, 1, "the exemption should have expired")
            self.assertIn("expired", r.stderr)
        else:
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("awaiting a home", r.stdout)

    def test_it_expires_the_moment_the_tracker_appears(self):
        p = PROJECTS / "faceoff-finder" / ".beads" / "issues.jsonl"
        if p.exists():
            self.skipTest("faceoff-finder already has a tracker")
        made = not p.parent.exists()
        p.parent.mkdir(exist_ok=True)
        p.write_text("")
        try:
            r = check([issue(labels=["program", "moves-to-faceoff-finder"],
                             description="about tools/lint_ratchet.py")])
            self.assertEqual(r.returncode, 1)
            self.assertIn("expired", r.stderr)
        finally:
            p.unlink()
            if made:
                p.parent.rmdir()

    def test_a_bogus_destination_is_rejected(self):
        r = check([issue(labels=["program", "moves-to-nowhere"])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a factory", r.stderr)


if __name__ == "__main__":
    unittest.main()
