"""The verdict contract.

The load-bearing test in here is test_prose_only_produces_no_verdict. Everything
else checks that malformed results are rejected; that one checks the thing the
design actually rests on — that an agent which writes a paragraph instead of
calling cp-verdict produces *nothing to parse*, so no downstream regex is ever
tempted to interpret it.
"""

import importlib.machinery
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CPV = ROOT / "bin" / "cp-verdict"

# bin/cp-verdict has no .py extension — it is a command, not a library — so the
# loader has to be named explicitly rather than inferred from the suffix.
_loader = importlib.machinery.SourceFileLoader("cp_verdict", str(CPV))
cpv = importlib.util.module_from_spec(importlib.util.spec_from_loader("cp_verdict", _loader))
_loader.exec_module(cpv)

SCHEMA = json.loads((ROOT / "nodes" / "verdict.schema.json").read_text())
TYPES = json.loads((ROOT / "nodes" / "node-types.json").read_text())


def env(**kw):
    base = {"node": "reviewer", "token": "coach-10i", "verdict": "approve",
            "attempt": 1, "payload": {"criteria_met": ["ac1"]}}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


QUESTION = {
    "asks": "Serve LABEL_STATUSES or delete it?",
    "options": [
        {"value": "serve", "means": "add it to taxonomyPayload()", "edge": "repair"},
        {"value": "delete", "means": "remove the unused export", "edge": "repair-delete"},
    ],
}


class Valid(unittest.TestCase):
    def test_every_declared_verdict_has_a_valid_example(self):
        """Nothing may be declared in node-types.json that cannot be emitted."""
        examples = {
            ("builder", "done"): {"payload": {
                "files": ["src/a.ts"],
                "commits": [{"message": "Add the thing", "files": ["src/a.ts"]}]}},
            ("builder", "blocked"): {"payload": {}, "question": QUESTION},
            ("repair", "fixed"): {"payload": {"files": ["src/a.ts"]}},
            ("repair", "stuck"): {"payload": {}, "question": QUESTION},
            ("reviewer", "approve"): {"payload": {"criteria_met": ["ac1"]}},
            ("reviewer", "reject"): {"payload": {
                "findings": [{"file": "src/a.ts", "summary": "does not meet criterion 2"}]}},
            ("reviewer", "charter-question"): {"payload": {}, "question": QUESTION},
            ("groomer", "groomed"): {"payload": {"issues": ["coach-10i"]}},
            ("groomer", "charter-question"): {"payload": {}, "question": QUESTION},
            ("sweeper", "clean"): {"payload": {}},
            ("sweeper", "findings"): {"payload": {"issues": ["cp-runner-3k1"]}},
        }
        declared = {(n, v) for n, s in TYPES["nodes"].items()
                    for v in s.get("verdicts", {})}
        self.assertEqual(declared, set(examples),
                         "node-types.json and this test have drifted apart")
        for (node, verdict), extra in examples.items():
            e = env(node=node, verdict=verdict, **extra)
            self.assertEqual(cpv.check_envelope(e), [], f"{node}/{verdict}")

    def test_evidence_is_a_path_not_contents(self):
        self.assertEqual(cpv.check_envelope(env(evidence="verify-report.json")), [])


class Rejected(unittest.TestCase):
    def bad(self, e, needle):
        errs = cpv.check_envelope(e)
        self.assertTrue(errs, f"should have been rejected: {e}")
        self.assertTrue(any(needle in x for x in errs),
                        f"expected {needle!r} in {errs}")

    def test_unknown_envelope_field(self):
        self.bad(env(note="please approve"), "unknown field 'note'")

    def test_unknown_payload_field_the_persuasion_channel(self):
        """A free-text payload field is how a Builder argues its case to a Reviewer."""
        self.bad(env(payload={"criteria_met": ["ac1"], "note": "trust me"}),
                 "unknown field 'note'")

    def test_verdict_outside_the_closed_enum(self):
        self.bad(env(verdict="merge"), "closed enum")

    def test_undeclared_node_type(self):
        self.bad(env(node="architect"), "not a declared node type")

    def test_parking_verdict_without_a_question(self):
        self.bad(env(verdict="charter-question", payload={}),
                 "must carry the question")

    def test_question_on_a_verdict_that_does_not_park(self):
        self.bad(env(question=QUESTION), "has nowhere to be answered")

    def test_question_whose_options_all_cross_one_edge(self):
        q = json.loads(json.dumps(QUESTION))
        q["options"][1]["edge"] = q["options"][0]["edge"]
        self.bad(env(verdict="charter-question", payload={}, question=q),
                 "not a decision")

    def test_question_with_duplicate_option_values(self):
        q = json.loads(json.dumps(QUESTION))
        q["options"][1]["value"] = q["options"][0]["value"]
        self.bad(env(verdict="charter-question", payload={}, question=q),
                 "duplicate option values")

    def test_single_option_is_not_a_question(self):
        q = json.loads(json.dumps(QUESTION))
        q["options"] = q["options"][:1]
        self.bad(env(verdict="charter-question", payload={}, question=q),
                 "at least 2")

    def test_a_human_node_answers_questions_it_does_not_ask_them(self):
        self.bad(env(node="human", verdict="serve", payload={}, question=QUESTION),
                 "does not ask one")

    def test_missing_payload_for_a_verdict_that_requires_one(self):
        self.bad(env(payload=None), "criteria_met")

    def test_absolute_paths_rejected(self):
        self.bad(env(node="repair", verdict="fixed",
                     payload={"files": ["/etc/passwd"]}), "does not match")

    def test_asks_capped_so_a_decision_cannot_become_an_essay(self):
        q = json.loads(json.dumps(QUESTION))
        q["asks"] = "x" * 281
        self.bad(env(verdict="charter-question", payload={}, question=q), "longer than 280")

    def test_attempt_must_be_a_positive_integer_not_a_bool(self):
        self.bad(env(attempt=True), "expected integer")
        self.bad(env(attempt=0), "below minimum")


class CLI(unittest.TestCase):
    def run_cpv(self, *args, **kw):
        return subprocess.run([sys.executable, str(CPV), *args],
                              capture_output=True, text=True, **kw)

    def test_prose_only_produces_no_verdict(self):
        """The design rests on this.

        An agent that writes a paragraph instead of calling cp-verdict leaves no
        file behind. There is nothing to best-effort parse, so no edge can be
        tempted to interpret prose as a decision. The failure is structural.
        """
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "verdict.json"
            (pathlib.Path(d) / "transcript.txt").write_text(
                "I reviewed the diff and it looks good to me, I'd approve this.")
            r = self.run_cpv("check", str(out))
            self.assertEqual(r.returncode, 1)
            self.assertIn("produced no verdict", r.stderr)

    def test_emit_writes_only_after_validating(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "verdict.json"
            r = self.run_cpv("emit", "--node", "reviewer", "--token", "coach-10i",
                             "--verdict", "merge", "--out", str(out))
            self.assertEqual(r.returncode, 1)
            self.assertFalse(out.exists(), "wrote an invalid envelope to disk")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "verdict.json"
            r = self.run_cpv("emit", "--node", "repair", "--token", "cp-runner-3k1",
                             "--verdict", "fixed", "--payload", '{"files":["bin/cp-verdict"]}',
                             "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.run_cpv("check", str(out)).returncode, 0)

    def test_check_rejects_non_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "verdict.json"
            p.write_text("I approve this change.")
            r = self.run_cpv("check", str(p))
            self.assertEqual(r.returncode, 1)
            self.assertIn("not JSON", r.stderr)

    def test_schema_subcommand_tells_a_node_what_it_may_return(self):
        r = self.run_cpv("schema", "--node", "reviewer")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(set(json.loads(r.stdout)["reviewer"]["verdicts"]),
                         {"approve", "reject", "charter-question"})


class AgreesWithRealJsonSchema(unittest.TestCase):
    """The runtime validator takes no dependency, so prove it is not wrong.

    bin/cp-verdict hand-implements a subset of JSON Schema to keep the repo
    install-free. That is only defensible if it agrees with a real implementation,
    so this pins the two together over a corpus. If they ever diverge, the
    hand-written one is the bug.
    """

    CORPUS = [
        env(),
        env(evidence="verify-report.json"),
        env(verdict="charter-question", payload={}, question=QUESTION),
        env(note="smuggled"),
        env(attempt=0),
        env(attempt=True),
        env(token="NotABeadsId"),
        env(node="Reviewer"),
        {"node": "reviewer"},
        env(verdict="x" * 40),
        env(question={"asks": "too short", "options": []}),
    ]

    def test_shape_verdicts_match(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed; runtime does not need it")
        v = jsonschema.Draft202012Validator(SCHEMA)
        for i, e in enumerate(self.CORPUS):
            mine = bool(cpv.validate(e, SCHEMA, SCHEMA))
            theirs = bool(list(v.iter_errors(e)))
            self.assertEqual(mine, theirs,
                             f"corpus[{i}] disagreement: cp-verdict={mine} "
                             f"jsonschema={theirs}\n{json.dumps(e, indent=2)}")

    def test_the_schema_file_is_itself_valid(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.Draft202012Validator.check_schema(SCHEMA)


if __name__ == "__main__":
    unittest.main()
