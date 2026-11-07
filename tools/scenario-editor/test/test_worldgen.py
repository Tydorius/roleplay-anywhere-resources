"""The world generation endpoints of the Scenario Editor, over HTTP with a
mocked generator: start, progress, cancel, the one-at-a-time rule, re-roll
from a saved plan, providers listed without their keys, the question bank,
the Frame-it job (with the long form's clarifying turn) and a generation
started with an approved frame.

The mock replaces worldgen.api.generate with a wrapper around the real
relayout of the village fixture: a genuine plan-to-zip build with no model
calls, so the whole path (job thread, zip import, workspace, plan.json)
runs for real.
"""
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent          # tools/scenario-editor
import sys
sys.path.insert(0, str(HERE))

import worldgen_editor as wg                           # noqa: E402  (puts the gallery and generator on sys.path)
import image_gallery as ig                             # noqa: E402
import scenario_editor as se                           # noqa: E402

FIXTURE = HERE.parent / "world-generator" / "fixtures" / "village.json"
FULL_KEY = "sk-test-1234567890abcd"                    # must never reach the browser

GEN_KWARGS = []          # what each mocked generate call received beyond the basics
FRAME_CALLS = []         # what each mocked frame call received

A_FRAME = {              # a World Frame as P0 returns it
    "genre": {"primary": "Fantasy", "influences": []},
    "premise": "A mill town on a cold river, where the weir feeds everyone's flour.",
    "reality": "Rare and mysterious",
    "setting": {"era": "a quiet age", "technology": "water and wind", "climate": "cold winters"},
    "tone": "Cozy", "conflict": "The old miller wants the weir raised; the fishers don't",
    "playerRole": "the new miller's apprentice", "themes": ["belonging"],
    "constraints": [], "summary": "A cozy mill town of twenty-odd souls on a cold river.",
    "unresolved": [],
}


def mocked_generate(idea, provider=None, extensions=(), seed=1, out_dir=None,
                    progress=None, cancel=None, **kw):
    """The fake model run: copy the fixture plan, build it for real, report
    progress like the generator does."""
    GEN_KWARGS.append(kw)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, out / "plan.json")
    progress({"phase": "P1", "label": "the world plan", "calls": 1, "tokens": 5})
    summary = wg.wgapi.relayout(str(out / "plan.json"), seed=seed, out_dir=str(out))
    summary.update(provider=provider, idea=idea, calls=7, tokens=12345)
    progress({"phase": "done", "label": "built", "calls": 7, "tokens": 12345})
    return summary


def mocked_frame(mode, idea="", answers=None, population=None, clarify=None,
                 provider=None, log_dir=None, progress=None, cancel=None, **kw):
    """The fake P0: the long form asks one clarifying question before framing."""
    FRAME_CALLS.append({"mode": mode, "idea": idea, "answers": answers,
                        "population": population, "clarify": clarify,
                        "provider": provider, "log_dir": log_dir,
                        "notes": kw.get("notes", "")})
    if progress:
        progress({"phase": "P0", "label": "the world frame", "calls": 1, "tokens": 900})
    if mode == "long" and clarify is None:
        return {"frame": None,
                "questions": [{"question": "Cozy or deadly?", "options": ["Cozy", "Deadly"]}],
                "stats": {}}
    return {"frame": json.loads(json.dumps(A_FRAME)), "questions": [], "stats": {}}


def slow_generate(idea=None, progress=None, cancel=None, **kw):
    """A run that reaches P1 and stays there until cancelled."""
    if progress:
        progress({"phase": "P1", "label": "the world plan", "calls": 1, "tokens": 5})
    while not cancel():
        time.sleep(0.05)
    raise wg.wgapi.Cancelled("cancelled before the p3 call")


class TestWorldgenEndpoints(unittest.TestCase):
    srv = None
    base = None
    sid = None          # a workspace made by a mocked generation, in setUpClass

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="wg-editor-test-")
        t = Path(cls.tmp.name)
        cls.addClassCleanup(cls.tmp.cleanup)
        wg.PROVIDERS_JSON = t / "providers.json"
        wg.OUT_ROOT = t / "out"
        old_work = ig.WORK
        ig.WORK = t / "work"
        cls.addClassCleanup(setattr, ig, "WORK", old_work)
        wg.save_provider("mockp", "http://localhost:9999/v1", FULL_KEY, "mock-model", 16000)

        se.Handler.store = t / "store"
        se.Handler.store.mkdir()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), se.Handler)
        cls.addClassCleanup(cls.srv.shutdown)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

        patcher = patch.object(wg.wgapi, "generate", mocked_generate)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

        j = cls.post("/api/worldgen/generate",
                     {"idea": "a test village", "provider": "mockp", "seed": 3})["job"]
        cls.finished = cls.wait_job(j["id"])
        assert cls.finished["state"] == "done", cls.finished
        cls.sid = cls.finished["source"]

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
    def post(cls, path, body=None):
        code, raw = cls.request("POST", path, body if body is not None else {})
        assert code == 200, f"POST {path}: {code} {raw}"
        return json.loads(raw)

    @classmethod
    def wait_job(cls, job_id, timeout=240):
        deadline = time.time() + timeout
        while time.time() < deadline:
            j = cls.get("/api/worldgen/job")["job"]
            if j and j["id"] == job_id and j["state"] != "running":
                return j
            time.sleep(0.3)
        raise AssertionError(f"job {job_id} did not finish in {timeout}s")

    # ------------------------------------------------------------ providers
    def test_meta_lists_providers_and_extensions_without_keys(self):
        m = self.get("/api/worldgen/meta")
        by_name = {p["name"]: p for p in m["providers"]}
        self.assertIn("mockp", by_name)
        self.assertTrue(by_name["mockp"]["ready"])
        self.assertEqual(by_name["mockp"]["keyHint"], "\u2026abcd")
        self.assertEqual(by_name["mockp"]["model"], "mock-model")
        exts = {e["id"]: e for e in m["extensions"]}
        self.assertEqual(set(exts), {"floors", "portals", "region-groups", "lights"})
        self.assertFalse(any(e["default"] for e in exts.values()))
        self.assertEqual(exts["floors"]["mods"], ["portals", "floors"])
        self.assertEqual(exts["floors"]["requires"], ["portals"])
        code, raw = self.request("GET", "/api/worldgen/meta")
        self.assertNotIn(FULL_KEY, raw, "the api key reached the browser")

    def test_provider_settings_roundtrip_keeps_an_unsent_key(self):
        r = self.post("/api/worldgen/providers", {"name": "second", "base_url": "http://x/v1",
                                                  "api_key": "sk-other-00001111", "model": "m2"})
        self.assertEqual([p["name"] for p in r["providers"]], ["mockp", "second"])
        # updating without sending a key keeps the stored one, masked in the listing
        r = self.post("/api/worldgen/providers", {"name": "second", "base_url": "http://y/v1",
                                                  "api_key": "", "model": "m3"})
        second = next(p for p in r["providers"] if p["name"] == "second")
        self.assertEqual(second["keyHint"], "\u2026" + "1111")
        self.assertTrue(second["ready"])
        self.assertNotIn("sk-other-00001111", json.dumps(r))

    def test_estimate_endpoint(self):
        e = self.get("/api/worldgen/estimate?idea=" + urllib.parse.quote("a fogbound harbour town"))["estimate"]
        self.assertTrue(25 <= e["calls"] <= 35, e)
        self.assertGreater(e["tokens"], 0)
        code, raw = self.request("GET", "/api/worldgen/estimate?idea=")
        self.assertEqual(code, 400)

    # ------------------------------------------------------------ generation
    def test_generation_makes_a_workspace_that_opens(self):
        j = self.finished                        # captured in setUpClass, before any other job ran
        self.assertEqual(j["state"], "done")
        self.assertTrue(self.sid.startswith("work/"))
        self.assertTrue(j["summary"]["ok"], j["summary"])
        sc = self.get("/api/scenario?source=" + urllib.parse.quote(self.sid))["scenario"]
        self.assertEqual(sc["name"], "Thornfield")
        self.assertGreater(len(sc["regions"]), 10)
        info = self.get("/api/worldgen/plan?source=" + urllib.parse.quote(self.sid))
        self.assertTrue(info["has"])                    # plan.json sits beside the workspace

    def test_generate_validates_before_starting(self):
        code, raw = self.request("POST", "/api/worldgen/generate",
                                 {"idea": "x", "provider": "nobody", "seed": 1})
        self.assertEqual(code, 400)
        code, raw = self.request("POST", "/api/worldgen/generate",
                                 {"idea": "x", "provider": "mockp", "extensions": ["levitate"], "seed": 1})
        self.assertEqual(code, 400)
        self.assertIn("levitate", raw)
        code, raw = self.request("POST", "/api/worldgen/generate", None)   # not a JSON object
        self.assertEqual(code, 400)

    # ------------------------------------------------------------ question bank, framing
    def test_questions_endpoint_serves_the_bank(self):
        b = self.get("/api/worldgen/questions")
        self.assertEqual(b["modes"], ["quick", "short", "medium", "long"])
        self.assertEqual(len(b["short"]), 7)
        self.assertEqual(len(b["medium"]), 14)     # the medium form: the short seven plus the deep seven
        self.assertEqual([q["id"] for q in b["short"]][0], "genre")
        self.assertNotIn("stakes", [q["id"] for q in b["short"]], "the medium form's questions")
        self.assertIn("stakes", [q["id"] for q in b["medium"]])
        self.assertEqual(b["population"], {"default": [20, 40], "min": 5, "max": 60})
        for q in b["short"] + b["medium"]:
            if not q.get("free"):
                self.assertNotIn("Other", q["options"], "Other is implicit in the UI")
                self.assertGreaterEqual(len(q["options"]), 2)

    def test_frame_job_returns_the_frame(self):
        with patch.object(wg.wgapi, "frame", mocked_frame):
            FRAME_CALLS.clear()
            j = self.post("/api/worldgen/frame",
                          {"mode": "short", "idea": "a mill town",
                           "answers": {"genre": {"choices": ["Fantasy"], "other": ""},
                                       "bogus": {"choices": ["nope"], "other": ""}},
                           "population": [10, 90], "provider": "mockp"})["job"]
            done = self.wait_job(j["id"])
        self.assertEqual(done["state"], "done", done["error"])
        self.assertEqual(done["kind"], "frame")
        self.assertEqual(done["frame"]["genre"]["primary"], "Fantasy")
        self.assertEqual(done["questions"], [])
        # the answers were cleaned by the generator's rules before the call
        self.assertEqual(FRAME_CALLS[-1]["mode"], "short")
        self.assertEqual(FRAME_CALLS[-1]["answers"], {"genre": {"choices": ["Fantasy"], "other": ""}})
        self.assertEqual(FRAME_CALLS[-1]["population"], [10, 60])   # clamped to the bank
        self.assertEqual(FRAME_CALLS[-1]["provider"], "mockp")

    def test_frame_job_long_clarify_roundtrip(self):
        with patch.object(wg.wgapi, "frame", mocked_frame):
            FRAME_CALLS.clear()
            j = self.post("/api/worldgen/frame",
                          {"mode": "long", "idea": "a mill town", "provider": "mockp"})["job"]
            first = self.wait_job(j["id"])
            self.assertEqual(first["state"], "done")
            self.assertIsNone(first["frame"])
            self.assertEqual(first["questions"][0]["question"], "Cozy or deadly?")
            j = self.post("/api/worldgen/frame",
                          {"mode": "long", "idea": "a mill town", "provider": "mockp",
                           "clarify": [{"question": "Cozy or deadly?", "answer": "Cozy"},
                                       {"question": "", "answer": "dropped"}]})["job"]
            done = self.wait_job(j["id"])
        self.assertEqual(done["state"], "done", done["error"])
        self.assertEqual(done["frame"]["tone"], "Cozy")
        self.assertEqual(FRAME_CALLS[-1]["clarify"],
                         [{"question": "Cozy or deadly?", "answer": "Cozy"}])

    def test_frame_skipping_every_question_frames_at_once_with_notes(self):
        with patch.object(wg.wgapi, "frame", mocked_frame):
            FRAME_CALLS.clear()
            j = self.post("/api/worldgen/frame",
                          {"mode": "long", "idea": "a mill town", "provider": "mockp",
                           "clarify": [], "notes": "  Act 1: the mill burns.  "})["job"]
            done = self.wait_job(j["id"])
        self.assertEqual(done["state"], "done", done["error"])
        self.assertIsNotNone(done["frame"])             # [] skips the clarifying turn
        self.assertEqual(FRAME_CALLS[-1]["clarify"], [])
        self.assertEqual(FRAME_CALLS[-1]["notes"], "Act 1: the mill burns.")

    def test_draft_roundtrip_and_frame_result_saved_into_it(self):
        self.post("/api/worldgen/draft?id=d-test-1",
                  {"mode": "long", "idea": "a mill town", "notes": "plot", "frame": "ignored"})
        with patch.object(wg.wgapi, "frame", mocked_frame):
            j = self.post("/api/worldgen/frame",
                          {"mode": "long", "idea": "a mill town", "provider": "mockp",
                           "draft": "d-test-1"})["job"]
            self.wait_job(j["id"])
        d = self.get("/api/worldgen/draft?id=d-test-1")["draft"]
        self.assertEqual((d["idea"], d["notes"]), ("a mill town", "plot"))
        self.assertEqual(d["questions"][0]["question"], "Cozy or deadly?")
        self.assertNotIn("frame", d)                    # the page can't write the frame
        listed = {x["id"]: x for x in self.get("/api/worldgen/drafts")["drafts"]}
        self.assertTrue(listed["d-test-1"]["questions"])
        self.post("/api/worldgen/draft?id=d-test-1", {"clearFrame": True})
        self.assertNotIn("questions", self.get("/api/worldgen/draft?id=d-test-1")["draft"])
        self.post("/api/worldgen/draft?id=d-test-1", {"delete": True})
        code, _ = self.request("GET", "/api/worldgen/draft?id=d-test-1")
        self.assertEqual(code, 400)
        code, _ = self.request("POST", "/api/worldgen/draft?id=../evil", {"idea": "x"})
        self.assertEqual(code, 400)

    def test_frame_validates_before_starting(self):
        code, raw = self.request("POST", "/api/worldgen/frame",
                                 {"mode": "huge", "idea": "x", "provider": "mockp"})
        self.assertEqual(code, 400)
        code, raw = self.request("POST", "/api/worldgen/frame",
                                 {"mode": "quick", "provider": "mockp"})
        self.assertEqual(code, 400)                        # quick needs the idea
        code, raw = self.request("POST", "/api/worldgen/frame",
                                 {"mode": "short", "idea": "x", "provider": "nobody"})
        self.assertEqual(code, 400)

    def test_generate_carries_the_frame_and_questionnaire(self):
        GEN_KWARGS.clear()
        j = self.post("/api/worldgen/generate",
                      {"idea": "", "provider": "mockp", "seed": 5,
                       "frame": A_FRAME,
                       "questionnaire": {"mode": "short",
                                         "answers": {"genre": {"choices": ["Fantasy"], "other": ""}},
                                         "population": [25, 35]}})["job"]
        done = self.wait_job(j["id"])
        self.assertEqual(done["state"], "done", done["error"])
        self.assertTrue(done["source"].startswith("work/"))
        self.assertEqual(GEN_KWARGS[-1]["frame"], A_FRAME)
        self.assertEqual(GEN_KWARGS[-1]["questionnaire"],
                         {"mode": "short",
                          "answers": {"genre": {"choices": ["Fantasy"], "other": ""}},
                          "population": [25, 35]})
        # a bad questionnaire mode never starts the job
        code, raw = self.request("POST", "/api/worldgen/generate",
                                 {"idea": "", "provider": "mockp",
                                  "frame": A_FRAME,
                                  "questionnaire": {"mode": "huge"}})
        self.assertEqual(code, 400)
        code, raw = self.request("POST", "/api/worldgen/generate",
                                 {"idea": "", "provider": "mockp", "frame": {"no": "summary"}})
        self.assertEqual(code, 400)

    # ------------------------------------------------------------ one at a time, cancel
    def test_cancel_stops_a_running_job_and_blocks_a_second(self):
        def stop_any_job():                          # a failed assert must not leave the job running
            self.request("POST", "/api/worldgen/cancel")
            for _ in range(100):
                j = self.get("/api/worldgen/job")["job"]
                if j["state"] != "running":
                    return
                time.sleep(0.1)
        with patch.object(wg.wgapi, "generate", slow_generate):
            j = self.post("/api/worldgen/generate", {"idea": "slow", "provider": "mockp"})["job"]
            self.addCleanup(stop_any_job)
            self.assertEqual(j["state"], "running")
            code, raw = self.request("POST", "/api/worldgen/generate",
                                     {"idea": "second", "provider": "mockp"})
            self.assertEqual(code, 409)
            self.assertTrue(json.loads(raw)["busy"])
            p = self.get("/api/worldgen/job")["job"]
            self.assertEqual(p["phase"], "P1")          # progress is visible while running
            self.post("/api/worldgen/cancel")
            done = self.wait_job(j["id"], timeout=30)
        self.assertEqual(done["state"], "cancelled")
        self.assertIn("cancelled", done["error"])

    # ------------------------------------------------------------ re-roll
    def test_reroll_replaces_the_layout_in_a_new_workspace(self):
        j = self.post("/api/worldgen/reroll?source=" + urllib.parse.quote(self.sid), {"seed": 42})["job"]
        done = self.wait_job(j["id"])
        self.assertEqual(done["state"], "done", done["error"])
        self.assertNotEqual(done["source"], self.sid)
        self.assertEqual(done["summary"]["seed"], 42)
        self.assertEqual(done["summary"]["calls"], 0)   # no model calls
        sc = self.get("/api/scenario?source=" + urllib.parse.quote(done["source"]))["scenario"]
        self.assertEqual(sc["name"], "Thornfield")      # same world, new layout
        self.assertTrue(self.get("/api/worldgen/plan?source=" +
                                 urllib.parse.quote(done["source"]))["has"])

    def test_reroll_needs_a_saved_plan(self):
        ws = ig.WORK / "noplan"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "scenario.json").write_text("{}", "utf-8")
        code, raw = self.request("POST", "/api/worldgen/reroll?source=work/noplan", {"seed": 1})
        self.assertEqual(code, 400)
        self.assertIn("no saved plan", raw)
        code, raw = self.request("POST", "/api/worldgen/reroll?source=staging", {"seed": 1})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
