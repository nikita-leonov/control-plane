"""The edges that actually touch a repo.

Everything before this was a wrong number on a screen. commit, merge and close
are where a bug becomes a wrong commit, so they are tested against real git
repositories built in a temp directory — never against a factory.

The load-bearing test is test_it_refuses_a_path_the_plan_did_not_name. The plan
is the contract between the Builder and everything downstream; an edge that
quietly commits more than was declared makes every later claim about what a
change contains untrue.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EDGES = ROOT / "bin" / "edges"

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo, *args, check=True):
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       env=GIT_ENV)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def new_repo(d):
    git(d, "init", "-q", "-b", "main")
    (d / "a.txt").write_text("one\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "base")
    return git(d, "rev-parse", "HEAD")


def run_edge(name, cwd, **env):
    return subprocess.run([str(EDGES / name)], cwd=str(cwd), capture_output=True, text=True,
                          env={**GIT_ENV, "CP_EDGE": name, **env})


def result_file(d, commits):
    """Written outside the worktree, as the runner does — a result file inside
    the tree would itself be an undeclared change."""
    p = pathlib.Path(tempfile.mkdtemp()) / "result.json"
    p.write_text(json.dumps({"node": "builder", "token": "cp-t", "verdict": "done",
                             "attempt": 1, "payload": {"files": [f for c in commits
                                                                 for f in c["files"]],
                                                       "commits": commits}}))
    return p


class Commit(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.base = new_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, res):
        return {"CP_TOKEN": "cp-t", "CP_FACTORY": "control-plane", "CP_RESULT": str(res),
                "CP_WORKTREE": str(self.tmp), "CP_BASE": self.base}

    def test_one_commit_per_plan_entry_with_that_entrys_message(self):
        (self.tmp / "a.txt").write_text("two\n")
        (self.tmp / "b.txt").write_text("new\n")
        res = result_file(self.tmp, [{"message": "first change", "files": ["a.txt"]},
                                     {"message": "second change", "files": ["b.txt"]}])
        r = run_edge("commit", self.tmp, **self.env(res))
        self.assertEqual(r.returncode, 0, r.stderr)
        msgs = git(self.tmp, "log", "--format=%s", f"{self.base}..HEAD").splitlines()
        self.assertEqual(msgs, ["second change", "first change"])
        self.assertEqual(git(self.tmp, "show", "--name-only", "--format=", "HEAD"), "b.txt")

    def test_it_refuses_a_path_the_plan_did_not_name(self):
        """A node that touched more than it declared is a finding, not something
        to tidy up silently on the way past."""
        (self.tmp / "a.txt").write_text("two\n")
        (self.tmp / "sneaky.txt").write_text("not in the plan\n")
        res = result_file(self.tmp, [{"message": "just a.txt", "files": ["a.txt"]}])
        r = run_edge("commit", self.tmp, **self.env(res))
        self.assertEqual(r.returncode, 1, "an undeclared path must fail the work, not pass")
        self.assertIn("sneaky.txt", r.stderr)
        self.assertEqual(git(self.tmp, "log", "--format=%s", f"{self.base}..HEAD"), "",
                         "it must not commit anything when the plan does not match")

    def test_a_plan_with_no_commits_is_broken_not_failed(self):
        p = self.tmp / "r.json"
        p.write_text(json.dumps({"node": "builder", "token": "cp-t", "verdict": "done",
                                 "attempt": 1, "payload": {"files": [], "commits": []}}))
        self.assertEqual(run_edge("commit", self.tmp, **self.env(p)).returncode, 2)

    def test_a_missing_worktree_is_broken_not_failed(self):
        res = result_file(self.tmp, [{"message": "x y", "files": ["a.txt"]}])
        env = self.env(res)
        env["CP_WORKTREE"] = "/nonexistent/worktree"
        self.assertEqual(run_edge("commit", self.tmp, **env).returncode, 2)

    def test_a_base_the_repo_does_not_have_is_broken(self):
        res = result_file(self.tmp, [{"message": "x y", "files": ["a.txt"]}])
        env = self.env(res)
        env["CP_BASE"] = "0" * 40
        self.assertEqual(run_edge("commit", self.tmp, **env).returncode, 2)

    def test_it_is_a_pure_function_of_the_plan_and_the_base(self):
        """Same plan, same starting sha, same result. Commit shas carry a
        timestamp, so what has to match is the tree — the content that lands."""
        trees = []
        for _ in range(2):
            d = pathlib.Path(tempfile.mkdtemp())
            try:
                base = new_repo(d)
                (d / "a.txt").write_text("two\n")
                (d / "b.txt").write_text("new\n")
                res = result_file(d, [{"message": "first change", "files": ["a.txt"]},
                                      {"message": "second change", "files": ["b.txt"]}])
                r = run_edge("commit", d, CP_TOKEN="cp-t", CP_FACTORY="control-plane",
                             CP_RESULT=str(res), CP_WORKTREE=str(d), CP_BASE=base)
                self.assertEqual(r.returncode, 0, r.stderr)
                trees.append(git(d, "rev-parse", "HEAD^{tree}"))
            finally:
                shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(trees[0], trees[1], "the same plan produced a different tree")


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.base = new_repo(self.tmp)
        git(self.tmp, "checkout", "-q", "-b", "cp/cp-t")
        (self.tmp / "b.txt").write_text("work\n")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "the work")
        git(self.tmp, "checkout", "-q", "main")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        return {"CP_TOKEN": "cp-t", "CP_FACTORY": "control-plane"}

    def test_it_merges_the_branch(self):
        r = run_edge("merge", self.tmp, **self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "b.txt").exists())
        self.assertIn("Merge cp-t", git(self.tmp, "log", "--format=%s", "-1"))

    def test_it_refuses_to_merge_over_uncommitted_changes(self):
        (self.tmp / "a.txt").write_text("local edit\n")
        r = run_edge("merge", self.tmp, **self.env())
        self.assertEqual(r.returncode, 1)
        self.assertEqual(git(self.tmp, "log", "--format=%s", "-1"), "base")

    def test_a_missing_branch_is_broken_not_failed(self):
        env = self.env()
        env["CP_TOKEN"] = "cp-nonexistent"
        self.assertEqual(run_edge("merge", self.tmp, **env).returncode, 2)

    def test_a_conflict_leaves_the_repo_where_it_found_it(self):
        (self.tmp / "b.txt").write_text("conflicting\n")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "conflict")
        before = git(self.tmp, "rev-parse", "HEAD")
        r = run_edge("merge", self.tmp, **self.env())
        self.assertEqual(r.returncode, 1)
        self.assertEqual(git(self.tmp, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.tmp, "status", "--porcelain"), "",
                         "a failed merge must not leave the repo mid-merge")

    def test_not_a_repo_is_broken(self):
        d = pathlib.Path(tempfile.mkdtemp())
        try:
            self.assertEqual(run_edge("merge", d, **self.env()).returncode, 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def br(repo, *args):
    return subprocess.run(["br", *args, "--no-daemon"], cwd=str(repo),
                          capture_output=True, text=True, env=GIT_ENV)


@unittest.skipUnless(shutil.which("br"), "br is not installed")
class Close(unittest.TestCase):
    """Against a throwaway tracker. Never against a factory's."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        new_repo(self.tmp)
        br(self.tmp, "init", "--prefix", "tst")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, slug):
        br(self.tmp, "create", f"issue {slug}", "-t", "task", "--slug", slug)
        out = br(self.tmp, "list", "--json").stdout
        rows = json.loads(out) if out.strip() else []
        rows = rows if isinstance(rows, list) else rows.get("issues", [])
        return next(o["id"] for o in rows if slug in o["id"])

    def test_it_closes_the_issue(self):
        i = self.make("thing")
        r = run_edge("close", self.tmp, CP_TOKEN=i, CP_FACTORY="tst", CP_RUN="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("closed", br(self.tmp, "show", i).stdout.lower())

    def test_replaying_a_close_is_safe(self):
        """An edge may be crossed again after a resume. Closing twice must not
        become a failure, or every resumed token dies at the last hop."""
        i = self.make("again")
        self.assertEqual(run_edge("close", self.tmp, CP_TOKEN=i, CP_FACTORY="tst").returncode, 0)
        r = run_edge("close", self.tmp, CP_TOKEN=i, CP_FACTORY="tst")
        self.assertEqual(r.returncode, 0)
        self.assertIn("already closed", r.stdout)

    def test_a_tracker_refusal_fails_the_work_it_does_not_force_it(self):
        """If beads refuses because something still blocks the issue, it is
        usually right. The token goes to a person with the tracker's own reason
        rather than being forced through."""
        a, b = self.make("dependent"), self.make("blocker")
        br(self.tmp, "dep", "add", a, b, "-t", "blocks")
        r = run_edge("close", self.tmp, CP_TOKEN=a, CP_FACTORY="tst")
        if r.returncode == 0:
            self.skipTest("this beads does not refuse a close past an open blocker")
        self.assertEqual(r.returncode, 1, "a refusal is the work failing, not the edge breaking")

    def test_an_unknown_issue_is_broken_not_failed(self):
        r = run_edge("close", self.tmp, CP_TOKEN="tst-nope-xxx", CP_FACTORY="tst")
        self.assertEqual(r.returncode, 2)

    def test_no_tracker_is_broken(self):
        d = pathlib.Path(tempfile.mkdtemp())
        try:
            r = run_edge("close", d, CP_TOKEN="tst-x-xxx", CP_FACTORY="tst")
            self.assertEqual(r.returncode, 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class DryRunCannotTouchARepo(unittest.TestCase):
    def test_every_mutating_edge_refuses_on_its_own(self):
        """The runner swaps a no-op in, and each script checks as well. Two
        locks, because the first one used to key off the working directory and
        would have stopped covering these the day they became real."""
        g = json.loads((ROOT / "nodes" / "graph.json").read_text())
        mutating = [n for n, s in g["edges"].items() if s.get("mutates")]
        self.assertEqual(sorted(mutating), ["close", "commit", "merge"])
        for name in mutating:
            r = run_edge(name, ROOT, CP_DRY_RUN="1", CP_TOKEN="cp-t",
                         CP_FACTORY="control-plane")
            self.assertEqual(r.returncode, 2, f"{name} ran during a dry run")
            self.assertIn("dry run", r.stderr)

    def test_the_runner_swaps_them_out(self):
        src = (ROOT / "bin" / "cp-run").read_text()
        self.assertIn('edge.get("mutates")', src,
                      "the dry-run guard must key on what an edge does, not where it runs")


if __name__ == "__main__":
    unittest.main()
