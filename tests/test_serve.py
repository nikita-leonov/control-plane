"""The answer endpoint.

This is the only thing in the panel that changes anything, so it is the only
thing with an attack surface. It exists because a decision queue you can read but
not act on sends you to a terminal, which is how a queue becomes a backlog.

The rule it enforces: an answer may only ever be one of the options that token's
own parking node offered. It cannot name an arbitrary edge, which would be a way
to walk a token anywhere in the graph from a browser.
"""

import json
import pathlib
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cp_run(*args):
    return subprocess.run([sys.executable, str(ROOT / "bin" / "cp-run"), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


def post(port, obj, path="/api/answer"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class AnswerEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.srv = subprocess.Popen([sys.executable, str(ROOT / "bin" / "cp"),
                                    "serve", "--port", str(cls.port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   cwd=str(ROOT))
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/state", timeout=2)
                return
            except Exception:                              # noqa: BLE001
                time.sleep(0.1)
        raise RuntimeError("cp serve did not come up")

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait(timeout=10)
        for p in (STATE / "tokens").glob("s-*.json"):
            p.unlink()
        log = STATE / "transitions.ndjson"
        if log.exists():
            keep = [l for l in log.read_text().splitlines()
                    if l.strip() and not json.loads(l)["token"].startswith("s-")]
            log.write_text("\n".join(keep) + ("\n" if keep else ""))

    def park(self, tid, factory="finance-c-and-c", scenario="happy"):
        cp_run(factory, tid, "--dry-run", "--scenario", scenario)
        t = json.loads((STATE / "tokens" / f"{tid}.json").read_text())
        self.assertEqual(t["status"], "parked", "fixture did not park")
        return t

    def test_it_binds_loopback_only(self):
        """The panel lives where the work lives. Nothing about it should be
        reachable from another machine."""
        with socket.socket() as s:
            s.settimeout(2)
            self.assertNotEqual(s.connect_ex((socket.gethostbyname(socket.gethostname()),
                                              self.port)), 0,
                                "answer endpoint is reachable off loopback")

    def test_an_option_the_token_never_offered_is_refused(self):
        self.park("s-opt")
        code, body = post(self.port, {"token": "s-opt", "value": "merge-anyway"})
        self.assertEqual(code, 400)
        self.assertIn("not one of", body["error"])

    def test_an_arbitrary_edge_name_is_refused(self):
        """Naming an edge directly would be a way to walk a token anywhere."""
        self.park("s-edge")
        code, body = post(self.port, {"token": "s-edge", "value": "close"})
        self.assertEqual(code, 400)

    def test_path_traversal_in_the_token_id_is_refused(self):
        for bad in ("../../etc/passwd", "../nodes/graph", "a/b"):
            code, _ = post(self.port, {"token": bad, "value": "yes"})
            self.assertEqual(code, 404, f"{bad!r} was not refused")

    def test_a_token_that_is_not_parked_is_refused(self):
        cp_run("ai-ih-coach", "s-done", "--dry-run", "--scenario", "happy")
        code, body = post(self.port, {"token": "s-done", "value": "yes"})
        self.assertEqual(code, 409)
        self.assertIn("not parked", body["error"])

    def test_an_oversized_body_is_refused(self):
        code, _ = post(self.port, {"token": "s-x", "value": "y" * 8000})
        self.assertEqual(code, 400)

    def test_a_valid_answer_advances_the_token_and_says_so(self):
        self.park("s-ok")
        code, body = post(self.port, {"token": "s-ok", "value": "yes"})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["node"], "@done")

    def test_the_click_is_recorded_as_a_human_answer_from_the_web(self):
        """Months later it matters whether a person clicked it or a script
        supplied it. That is provenance, not decoration."""
        self.park("s-prov")
        post(self.port, {"token": "s-prov", "value": "yes"})
        rows = [json.loads(l) for l in (STATE / "transitions.ndjson").read_text().splitlines()
                if l.strip() and json.loads(l)["token"] == "s-prov"]
        human = [r for r in rows if r.get("actor") == "human"]
        self.assertEqual(len(human), 1)
        self.assertEqual(human[0]["via"], "web")
        self.assertEqual(human[0]["verdict"], "yes")

    def test_holding_leaves_it_parked_and_answerable_again(self):
        self.park("s-hold")
        code, body = post(self.port, {"token": "s-hold", "value": "hold"})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "parked")
        self.assertEqual(post(self.port, {"token": "s-hold", "value": "yes"})[0], 200)

    def test_unknown_post_paths_are_404(self):
        self.assertEqual(post(self.port, {}, path="/api/anything")[0], 404)


if __name__ == "__main__":
    unittest.main()
