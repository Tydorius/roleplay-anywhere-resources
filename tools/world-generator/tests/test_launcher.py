"""The launcher behind the double-click files: with no providers.json it asks
for a provider and writes one (keeping other entries, never echoing the key),
then makes a world from an idea or re-rolls a saved one. Scripted answers
stand in for the person typing; a scripted client stands in for the model."""
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import launcher
from worldgen import api, llm
from worldgen import settings as settings_mod
from tests.test_013_frame import a_frame
from tests.test_model import ScriptedClient, canned_replies


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
KEY = "sk-test-secret-123456"


class Session:
    """Feeds ``answers`` to the launcher's prompts and records what it says."""

    def __init__(self, answers, tmp, client=None):
        self.answers, self.said = list(answers), []
        self.path = os.path.join(tmp, "providers.json")
        self.launcher = launcher.Launcher(
            inp=self.reply, out=self.said.append, secret=self.reply,
            providers_path=self.path, out_root=os.path.join(tmp, "out"), client=client)

    def reply(self, prompt):
        self.said.append(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected question: {prompt!r}")
        return self.answers.pop(0)

    def text(self):
        return "\n".join(map(str, self.said))

    def providers(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)


class TestProviderSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worldgen-launcher-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_run_writes_providers_json_from_a_preset(self):
        s = Session(["1", "", "", "", KEY, "n", "7"], self.tmp)   # zai, defaults, key, no test, quit
        self.assertEqual(s.launcher.main(), 0)
        entry = s.providers()["zai"]
        self.assertEqual((entry["base_url"], entry["model"], entry["api_key"]),
                         ("https://api.z.ai/api/paas/v4", "glm-5.3-flash", KEY))
        self.assertEqual(s.launcher.ready_providers(), ["zai"])
        self.assertNotIn(KEY, s.text(), "the key must never be echoed")
        self.assertIn("First, set up the model provider", s.text())

    def test_enter_keeps_the_saved_key_and_other_providers_survive(self):
        s = Session(["1", "", "", "", KEY, "n"], self.tmp)
        s.launcher.setup_provider()
        s2 = Session(["6", "", "", "", "", "n"], self.tmp)         # ollama: Enter = "none"
        s2.launcher.setup_provider()
        s3 = Session(["1", "", "", "glm-5.3", "", "n"], self.tmp)  # change zai's model, keep its key
        s3.launcher.setup_provider()
        data = s3.providers()
        self.assertEqual(data["ollama"]["api_key"], "none")
        self.assertEqual((data["zai"]["model"], data["zai"]["api_key"]), ("glm-5.3", KEY))
        self.assertEqual(sorted(s3.launcher.ready_providers()), ["ollama", "zai"])

    def test_a_preset_keeps_its_optional_settings(self):
        s = Session(["5", "", "", "", KEY, "n"], self.tmp)        # deepseek
        s.launcher.setup_provider()
        entry = s.providers()["deepseek"]
        self.assertEqual(entry["base_url"], "https://api.deepseek.com")
        self.assertEqual(entry["extra_body"], {"thinking": {"type": "enabled"}})
        s2 = Session(["4", "", "", "", KEY, "n"], self.tmp)       # openai
        s2.launcher.setup_provider()
        self.assertEqual(s2.providers()["openai"]["max_output"], 16384)

    def test_a_remote_provider_needs_a_key(self):
        s = Session(["3", "", "", "", ""], self.tmp)                # openrouter, no key
        self.assertIsNone(s.launcher.setup_provider())
        self.assertFalse(os.path.exists(s.path))
        self.assertIn("Not saved", s.text())

    def test_the_placeholder_key_is_not_ready(self):
        shutil.copy(launcher.EXAMPLE_PATH, os.path.join(self.tmp, "providers.json"))
        s = Session([], self.tmp)
        self.assertEqual(s.launcher.ready_providers(), ["ollama", "lmstudio", "llama-swap"])


class StubServer:
    """A /chat/completions server on a free local port that answers "ok",
    after ``delay`` seconds."""

    def __init__(self, delay=0.0):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(handler):
                handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
                time.sleep(delay)
                body = json.dumps({"model": "stub-model", "usage": {"total_tokens": 3},
                                   "choices": [{"message": {"content": "ok"}}]}).encode()
                try:
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/json")
                    handler.end_headers()
                    handler.wfile.write(body)
                except OSError:
                    pass   # the client gave up waiting

            def log_message(handler, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestProviderCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worldgen-launcher-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def setup_stub(self, server, answers_after):
        # another server, its name, URL, model, key, then the test request
        return Session(["9", "stub", server.url, "stub-model", "abc", *answers_after], self.tmp)

    def test_a_working_provider_passes_its_test(self):
        server = StubServer()
        try:
            s = self.setup_stub(server, ["y"])
            self.assertEqual(s.launcher.setup_provider(), "stub")
        finally:
            server.close()
        self.assertIn("OK: stub-model answered", s.text())

    def test_a_slow_provider_reports_a_timeout_not_a_traceback(self):
        server = StubServer(delay=3)
        old = llm.CHECK_TIMEOUT
        llm.CHECK_TIMEOUT = 1
        try:
            s = self.setup_stub(server, ["y"])
            s.launcher.setup_provider()
        finally:
            llm.CHECK_TIMEOUT = old
            server.close()
        self.assertIn("That didn't work: no reply within 1s", s.text())
        self.assertIn("busy", s.text())


class TestWorlds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worldgen-launcher-")
        # the scripted replies are the worlds without a cast; test_cast has its own
        generate = api.generate
        patcher = mock.patch.object(api, "generate",
                                    lambda *a, **k: generate(*a, cast=False, **k))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_world_from_an_idea(self):
        # quick mode, the idea, default population, use the frame, four
        # extensions off, the old furnishing method (the canned P3 replies are
        # old-style), default seed, start
        s = Session(["1", "a mill village", "", "1", "n", "n", "n", "n", "n", "", ""],
                    self.tmp,
                    client=ScriptedClient([_dump(a_frame())] + canned_replies()))
        summary = s.launcher.new_world()
        self.assertTrue(summary["ok"], summary)
        self.assertTrue(os.path.exists(os.path.join(summary["out"], summary["zip"])))
        self.assertTrue(os.path.exists(os.path.join(summary["out"], "launcher.log")))
        self.assertEqual(summary["extensions"], [])
        self.assertIn("Done:", s.text())
        self.assertIn("P1:", s.text())
        self.assertIn("THE WORLD FRAME", s.text())
        # the frame reached the plan and the questionnaire with it
        with open(os.path.join(summary["out"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(plan["questionnaire"]["mode"], "quick")
        self.assertEqual(plan["questionnaire"]["population"], [20, 40])
        self.assertEqual(plan["frame"]["genre"]["primary"], "Fantasy")

    def test_short_questionnaire_walks_the_questions(self):
        # mode short, no idea, then: genre Fantasy (Enter stops the second
        # pick), extraordinary skipped, tone Other ("a warm hearth"), player
        # and drive skipped, play Explore+Fight, avoid free text, population
        # 10-30, use the frame, extensions off, seed, start
        s = Session(["2", "",
                     "1", "", "", "6", "a warm hearth", "", "",
                     "1", "2", "no demons",
                     "10-30", "1", "n", "n", "n", "n", "n", "", ""],
                    self.tmp,
                    client=ScriptedClient([_dump(a_frame())] + canned_replies()))
        summary = s.launcher.new_world()
        self.assertTrue(summary["ok"], summary)
        with open(os.path.join(summary["out"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
        q = plan["questionnaire"]
        self.assertEqual(q["mode"], "short")
        self.assertEqual(q["population"], [10, 30])
        self.assertEqual(q["answers"]["genre"], {"choices": ["Fantasy"], "other": ""})
        self.assertEqual(q["answers"]["tone"]["other"], "a warm hearth")
        self.assertEqual(q["answers"]["play"]["choices"], ["Explore", "Fight"])
        self.assertEqual(q["answers"]["avoid"]["other"], "no demons")
        self.assertNotIn("stakes", q["answers"], "the short form has no Q8-14")
        # the questions were asked, and the answers reached the P0 prompt
        self.assertIn("What kind of world?", s.text())
        self.assertIn("Anything to avoid?", s.text())
        self.assertIn("a warm hearth", _dump(s.launcher.client.sent[0]))
        self.assertIn("no demons", _dump(s.launcher.client.sent[0]))

    def test_long_mode_runs_the_clarifying_turn(self):
        # mode long, the idea, genre Fantasy then Enter (stop the second
        # pick), the other 13 questions skipped, default population, the
        # model's clarify question answered "Cozy", use the frame,
        # extensions off, default seed, start
        frame_replies = [_dump({"questions": [{"question": "Cozy or deadly?",
                                               "options": ["Cozy", "Deadly"]}]}),
                         _dump(a_frame())] + canned_replies()
        s = Session(["4", "a mill village", "1", ""]
                    + [""] * 13
                    + ["", "1", "1", "n", "n", "n", "n", "n", "", ""],
                    self.tmp, client=ScriptedClient(frame_replies))
        summary = s.launcher.new_world()
        self.assertTrue(summary["ok"], summary)
        self.assertIn("questions of its own", s.text())
        self.assertIn("Cozy or deadly?", s.text())
        # the clarification reached the frame call's prompt (the second call)
        self.assertIn("A: Cozy", _dump(s.launcher.client.sent[1]))
        with open(os.path.join(summary["out"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(plan["questionnaire"]["mode"], "long")
        self.assertEqual(plan["questionnaire"]["mode"], "long")

    def test_a_run_saves_its_settings_and_a_settings_file_runs_again(self):
        s = Session(["1", "a mill village", "", "1", "n", "n", "n", "n", "n", "4", ""],
                    self.tmp,
                    client=ScriptedClient([_dump(a_frame())] + canned_replies()))
        first = s.launcher.new_world()
        path = os.path.join(first["out"], settings_mod.FILE_NAME)
        self.assertIn("Your choices for this world", s.text())
        saved = settings_mod.read(path)
        self.assertEqual((saved["idea"], saved["seed"], saved["library"]),
                         ("a mill village", 4, False))
        self.assertEqual(saved["frame"]["genre"]["primary"], "Fantasy")
        with open(path, encoding="utf-8") as f:
            self.assertNotIn(KEY, f.read())
        # the saved frame is used: no P0 call this time, so the replies start at P1
        s2 = Session([f'"{path}"', "", "", ""], self.tmp,
                     client=ScriptedClient(canned_replies()))
        again = s2.launcher.world_from_settings()
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["seed"], 4)
        self.assertIn("Idea: a mill village", s2.text())
        with open(os.path.join(again["out"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(plan["frame"]["genre"]["primary"], "Fantasy")

    def test_a_bad_settings_file_says_why(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"idea": "no kind"}')
        s = Session([bad], self.tmp)
        self.assertIsNone(s.launcher.world_from_settings())
        self.assertIn("Can't use that file: this isn't a world settings file", s.text())

    def test_floors_turns_portals_on_without_asking(self):
        s = Session(["y", "n", "n"], self.tmp)       # floors yes; region groups, lights no
        self.assertEqual(s.launcher.pick_extensions(), ["floors", "portals"])
        self.assertIn("Portals: on (needed by floors)", s.text())

    def test_reroll_a_saved_world(self):
        world = os.path.join(self.tmp, "out", "village-20261101-120000")
        os.makedirs(world)
        shutil.copy(os.path.join(FIXTURES, "village.json"), os.path.join(world, "plan.json"))
        s = Session(["1", "7"], self.tmp)
        summary = s.launcher.reroll()
        self.assertTrue(summary["ok"], summary)
        self.assertEqual((summary["seed"], summary["calls"]), (7, 0))
        self.assertIn("village-seed7-", os.path.basename(summary["out"]))


if __name__ == "__main__":
    unittest.main()
