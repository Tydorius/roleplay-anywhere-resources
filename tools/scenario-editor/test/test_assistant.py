"""The assistant endpoints of the Scenario Editor, over HTTP with the model
mocked at the wire: the fake Client subclasses the generator's real one and
replaces only the HTTP POST, so a turn runs the real contract loop — retries
with the error fed back, call logs under <workspace>/assistant-log/ — without
touching a provider or the real providers.json.

The assistant's job slot is its own: nothing here can block or be blocked by
a world-generation job.
"""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent          # tools/scenario-editor
sys.path.insert(0, str(HERE))

import worldgen_editor as wg                           # noqa: E402  (puts the gallery and generator on sys.path)
import image_gallery as ig                             # noqa: E402
from worldgen import llm as wgllm                      # noqa: E402
import scenario_editor as se                           # noqa: E402
import assistant_editor as at                          # noqa: E402

FULL_KEY = "sk-assist-1234567890abcd"                  # must never reach the browser

STATE = {"replies": [], "sleep": 0.0}   # what the mocked wire serves
INSTALLED = []                          # every fake client the assistant built


class FakeClient(wgllm.Client):
    """The generator's real Client with the network cut out: _post serves the
    queued raw replies (sleeping first when a test needs a slow model);
    everything else — the contract loop, the counters, the call logs — is the
    real code. No providers.json is read."""

    def __init__(self, provider, providers_path=wgllm.PROVIDERS_PATH, log_dir=None):
        self.provider = provider
        self.model = "mock-model"
        self.base_url = "http://127.0.0.1:1/v1"
        self._api_key = FULL_KEY
        self.max_tokens = 4000
        self.timeout = 30
        self.rate_limit_wait = 0
        self.max_output = None
        self.extra_body = {}
        self.vision = False
        self.on_wait = None
        self.log_dir = log_dir
        self.calls = 0
        self.retries = 0
        self.last_error = None
        self.last_cut = False
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.seconds = 0.0
        self.attempts = []              # the messages of every wire attempt
        INSTALLED.append(self)

    def _post(self, messages, max_tokens=None):
        self.attempts.append([dict(m) for m in messages])
        raw = STATE["replies"].pop(0)   # taken before any sleep, so a cancelled
        if STATE["sleep"]:              # call can never steal a later test's reply
            time.sleep(STATE["sleep"])
        return raw, {"prompt": 10, "completion": 5, "total": 15, "finish": "stop"}


class TestAssistantEndpoints(unittest.TestCase):
    srv = None
    base = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="assistant-editor-test-")
        t = Path(cls.tmp.name)
        cls.addClassCleanup(cls.tmp.cleanup)
        wg.PROVIDERS_JSON = t / "providers.json"
        old_work = ig.WORK
        ig.WORK = t / "work"
        cls.addClassCleanup(setattr, ig, "WORK", old_work)
        wg.save_provider("mockp", "http://127.0.0.1:1/v1", FULL_KEY, "mock-model", 16000)

        cls.ws = ig.WORK / "assist"     # the editable workspace the turns work on
        cls.ws.mkdir(parents=True)
        (cls.ws / "scenario.json").write_text("{}", "utf-8")
        cls.sid = "work/assist"

        se.Handler.store = t / "store"
        se.Handler.store.mkdir()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), se.Handler)
        cls.addClassCleanup(cls.srv.shutdown)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    def setUp(self):
        at._job = None                 # no turn of an earlier test is running
        INSTALLED.clear()
        STATE["replies"] = []
        STATE["sleep"] = 0.0
        p = patch.object(wgllm, "Client", FakeClient)
        p.start()
        self.addCleanup(p.stop)

    # ------------------------------------------------------------ http helpers
    @classmethod
    def request(cls, method, path, body=None):
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        req = urllib.request.Request(cls.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    @classmethod
    def get(cls, path):
        code, raw = cls.request("GET", path)
        assert code == 200, f"GET {path}: {code} {raw}"
        return json.loads(raw)

    @classmethod
    def wait_at_job(cls, job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            j = cls.get("/api/assistant/job")["job"]
            if j and j["id"] == job_id and j["state"] != "running":
                return j
            time.sleep(0.05)
        raise AssertionError(f"assistant job {job_id} did not finish in {timeout}s")

    def turn(self, **over):
        """One POST /api/assistant/turn with a small valid body; ``over``
        replaces fields."""
        body = {"source": self.sid, "provider": "mockp", "transcriptId": "t-1",
                "messages": [{"role": "user", "content": "make the tavern warmer"}],
                "tools": ["rename-region <id> to <new name> - renames one region"],
                "scenarioSummary": "Thornfield: a village with a tavern and a mill."}
        body.update(over)
        return self.request("POST", "/api/assistant/turn", body)

    def start_turn(self, **over):
        code, raw = self.turn(**over)
        assert code == 200, f"POST /api/assistant/turn: {code} {raw}"
        return json.loads(raw)["job"]

    def finish(self, job):
        done = self.wait_at_job(job["id"])
        self.assertEqual(done["state"], "done", done["error"])
        return done

    # ------------------------------------------------------------ a happy turn
    def test_a_happy_turn_round_trips(self):
        STATE["replies"] = ['{"reply": "I renamed the tavern.", "actions": '
                            '[{"tool": "rename-region", "args": {"id": "r-tavern", '
                            '"name": "The Warm Hearth"}}]}']
        done = self.finish(self.start_turn())
        self.assertEqual(done["reply"], "I renamed the tavern.")
        self.assertEqual(done["actions"],
                         [{"tool": "rename-region",
                           "args": {"id": "r-tavern", "name": "The Warm Hearth"}}])
        self.assertEqual(done["model"], "mock-model")
        self.assertEqual(done["provider"], "mockp")
        self.assertEqual(done["source"], self.sid)
        self.assertEqual(done["transcriptId"], "t-1")
        self.assertEqual(done["calls"], 1)
        self.assertGreaterEqual(done["tokens"], 15)
        self.assertGreaterEqual(done["seconds"], 0.0)
        fake = INSTALLED[-1]
        self.assertEqual(len(fake.attempts), 1)          # accepted on the first try
        sent = fake.attempts[0]
        self.assertEqual(sent[0]["role"], "system")      # the system prompt leads
        self.assertIn("ONE JSON object", sent[0]["content"])
        self.assertIn("- rename-region <id> to <new name>", sent[0]["content"])
        self.assertIn("Thornfield: a village with a tavern and a mill.",
                      sent[0]["content"])
        # ...then the transcript, verbatim
        self.assertEqual(sent[1:], [{"role": "user", "content": "make the tavern warmer"}])
        # the client logs into the workspace's assistant-log/, in this turn's own
        # folder, and a call landed there
        self.assertEqual(fake.log_dir[:len(str(self.ws / "assistant-log"))],
                         str(self.ws / "assistant-log"))
        logs = sorted((self.ws / "assistant-log").glob("*/*-assistant.json"))
        self.assertTrue(logs, "no call log was written")
        data = json.loads(logs[0].read_text("utf-8"))
        self.assertEqual(data["phase"], "assistant")
        self.assertNotIn(FULL_KEY, logs[0].read_text("utf-8"))

    # ------------------------------------------------------------ retries
    def test_a_prose_reply_is_retried_once_with_the_error_fed_back(self):
        STATE["replies"] = ["Sure! I would love to help with the tavern.",
                            '{"reply": "Done.", "actions": []}']
        done = self.finish(self.start_turn())
        self.assertEqual(done["reply"], "Done.")
        self.assertEqual(done["actions"], [])
        fake = INSTALLED[-1]
        self.assertEqual(len(fake.attempts), 2)          # exactly one retry
        first, again = fake.attempts
        self.assertEqual(again[:2], first)               # system + transcript unchanged
        self.assertEqual(again[2]["role"], "assistant")  # the bad reply quoted back
        self.assertIn("Sure! I would love to help", again[2]["content"])
        self.assertEqual(again[3]["role"], "user")       # ...and the error fed back
        self.assertIn("Your reply had problems", again[3]["content"])
        self.assertIn("no JSON", again[3]["content"])

    def test_a_shape_violating_reply_is_retried_the_same_way(self):
        STATE["replies"] = ['{"reply": "Sure.", "actions": "none"}',
                            '{"reply": "Sure.", "actions": []}']
        done = self.finish(self.start_turn())
        self.assertEqual(done["reply"], "Sure.")
        fake = INSTALLED[-1]
        self.assertEqual(len(fake.attempts), 2)
        self.assertIn('"actions" must be a list', fake.attempts[1][3]["content"])

    def test_a_reply_that_never_shapes_up_fails_the_job(self):
        STATE["replies"] = ['{"reply": "x", "actions": "no"}'] * 3
        done = self.wait_at_job(self.start_turn()["id"])
        self.assertEqual(done["state"], "failed")
        self.assertIn('"actions" must be a list', done["error"])
        self.assertIsNone(done["reply"])
        self.assertEqual(len(INSTALLED[-1].attempts), 3)  # the call, then two retries

    def test_a_reply_that_never_becomes_json_fails_the_turn(self):
        STATE["replies"] = ["just words", "still just words", "and again words"]
        done = self.wait_at_job(self.start_turn()["id"])
        self.assertEqual(done["state"], "failed")
        self.assertIn("no JSON object", done["error"])
        self.assertIsNone(done["reply"])

    def test_a_busy_provider_fails_the_turn_with_its_message(self):
        class BusyClient(FakeClient):
            def _post(self, messages, max_tokens=None):
                raise wgllm.ProviderBusy(
                    "mockp stayed busy or rate-limited for 15.0 minutes")
        with patch.object(wgllm, "Client", BusyClient):
            done = self.wait_at_job(self.start_turn()["id"])
        self.assertEqual(done["state"], "failed")
        self.assertIn("stayed busy", done["error"])

    # ------------------------------------------------------------ refused before the job starts
    def test_an_oversize_transcript_summary_or_tools_is_refused(self):
        code, raw = self.turn(messages=[{"role": "user", "content": "x" * 8001}])
        self.assertEqual(code, 400)
        self.assertIn("8,000", raw)
        code, raw = self.turn(messages=[{"role": "user", "content": "hi"}] * 61)
        self.assertEqual(code, 400)
        self.assertIn("60", raw)
        code, raw = self.turn(messages=[{"role": "user", "content": "y" * 4000}] * 21)
        self.assertEqual(code, 400)
        self.assertIn("80,000", raw)
        code, raw = self.turn(messages=[{"role": "system", "content": "hello"}])
        self.assertEqual(code, 400)
        self.assertIn("role", raw)
        code, raw = self.turn(messages=[{"role": "user", "content": {"part": "no"}}])
        self.assertEqual(code, 400)
        code, raw = self.turn(scenarioSummary="z" * 12001)
        self.assertEqual(code, 400)
        self.assertIn("12,000", raw)
        code, raw = self.turn(tools=["rename things " + "very " * 100])
        self.assertEqual(code, 400)
        self.assertIn("200", raw)
        code, raw = self.turn(tools="rename-region")
        self.assertEqual(code, 400)
        code, _ = self.request("POST", "/api/assistant/cancel")
        self.assertEqual(code, 400)                     # nothing is running
        code, _ = self.request("POST", "/api/assistant/turn", ["not", "an", "object"])
        self.assertEqual(code, 400)

    def test_an_unknown_workspace_or_provider_is_refused(self):
        for source in ("staging", "work/nope", "", None):
            code, raw = self.turn(source=source)
            self.assertEqual(code, 400, source)
            self.assertIn("workspace", raw)
        code, raw = self.turn(provider="nobody")
        self.assertEqual(code, 400)
        self.assertIn("nobody", raw)

    # ------------------------------------------------------------ one at a time, cancel
    def test_a_second_turn_while_one_runs_is_busy(self):
        STATE["sleep"] = 2.0
        STATE["replies"] = ['{"reply": "late but fine", "actions": []}']
        first = self.start_turn()
        code, raw = self.turn()
        self.assertEqual(code, 409)
        self.assertTrue(json.loads(raw)["busy"])
        done = self.finish(first)                       # the first still completes
        self.assertEqual(done["reply"], "late but fine")

    def test_cancel_stops_a_running_turn(self):
        STATE["sleep"] = 3.0
        STATE["replies"] = ['{"reply": "never seen", "actions": []}']
        j = self.start_turn()
        self.assertEqual(j["state"], "running")
        code, raw = self.request("POST", "/api/assistant/cancel")
        self.assertEqual(code, 200)
        done = self.wait_at_job(j["id"], timeout=10)
        self.assertEqual(done["state"], "cancelled")
        self.assertIn("cancelled", done["error"])
        self.assertIsNone(done["reply"])

    # ------------------------------------------------------------ meta, the key
    def test_meta_lists_providers_and_limits(self):
        m = self.get("/api/assistant/meta")
        by_name = {p["name"]: p for p in m["providers"]}
        self.assertTrue(by_name["mockp"]["ready"])
        self.assertEqual(by_name["mockp"]["keyHint"], "\u2026abcd")
        self.assertEqual((m["maxActions"], m["maxMessages"], m["summaryLimit"]),
                         (10, 60, 12000))

    def test_the_api_key_never_reaches_the_browser(self):
        STATE["replies"] = ['{"reply": "ok", "actions": []}']
        code, raw = self.turn()
        done = self.wait_at_job(json.loads(raw)["job"]["id"])
        self.assertEqual(done["state"], "done", done["error"])
        for text in (raw, json.dumps(done),
                     self.request("GET", "/api/assistant/job")[1],
                     self.request("GET", "/api/assistant/meta")[1]):
            self.assertNotIn(FULL_KEY, text)
        for log in (self.ws / "assistant-log").glob("*/*-assistant.json"):
            self.assertNotIn(FULL_KEY, log.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
