"""World settings files: one person's choices for a world, sent to someone
else who runs the same world. Checked on the way in like the forms check
them, never carrying a provider or key, and written by every run."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from worldgen import __main__ as cli
from worldgen import api, settings

from tests.test_013_frame import a_frame
from tests.test_model import ScriptedClient, canned_replies


def a_settings(**kw):
    base = dict(mode="short", idea="a mill town",
                answers={"genre": {"choices": ["Fantasy"], "other": ""}},
                population=[10, 30], notes="keep it cozy", seed=5,
                extensions=["floors"], library=False, frame=a_frame(), model="m-1")
    base.update(kw)
    return settings.make(**base)


class TestFormat(unittest.TestCase):
    def test_round_trip(self):
        s = a_settings()
        back = settings.loads(settings.dumps(s))
        self.assertEqual(back, s)
        self.assertEqual(back["kind"], settings.KIND)
        self.assertEqual(back["extensions"], ["floors", "portals"], "floors brings portals")

    def test_answers_are_cleaned_like_the_forms_clean_them(self):
        s = a_settings(answers={"genre": {"choices": ["Fantasy", "Not an option"]},
                                "nope": {"choices": [], "other": "x"}})
        self.assertEqual(s["answers"], {"genre": {"choices": ["Fantasy"], "other": ""}})

    def test_population_is_clamped_and_the_map_can_decide(self):
        self.assertEqual(a_settings(population=[1, 99999])["population"][0] >= 1, True)
        self.assertEqual(a_settings(population="map")["population"], "map")

    def test_unusable_files_say_why(self):
        cases = [("[]", "one JSON object"),
                 ('{"idea": "x"}', "isn't a world settings file"),
                 ('{"kind": "%s", "version": 99, "idea": "x"}' % settings.KIND, "newer"),
                 ('{"kind": "%s", "version": 1, "mode": "huge", "idea": "x"}' % settings.KIND,
                  "unknown mode"),
                 ('{"kind": "%s", "version": 1, "idea": "x", "extensions": ["jetpacks"]}'
                  % settings.KIND, "unknown extension"),
                 ('{"kind": "%s", "version": 1}' % settings.KIND, "nothing to build"),
                 ("{not json", "isn't valid JSON")]
        for text, why in cases:
            with self.assertRaises(settings.SettingsError) as cm:
                settings.loads(text)
            self.assertIn(why, str(cm.exception), text)

    def test_no_provider_or_key_is_kept(self):
        data = json.loads(settings.dumps(a_settings()))
        data.update(provider="zai", api_key="sk-secret", base_url="https://x")
        self.assertFalse({"provider", "api_key", "base_url"} & set(settings.check(data)))

    def test_questionnaire_for_a_plain_idea_is_none(self):
        self.assertIsNone(settings.questionnaire(settings.make(idea="a hamlet")))
        q = settings.questionnaire(a_settings())
        self.assertEqual((q["mode"], q["notes"]), ("short", "keep it cozy"))


class TestRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worldgen-settings-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generate_writes_settings_json(self):
        out = os.path.join(self.tmp, "w")
        api.generate("a mill village", client=ScriptedClient(canned_replies()), out_dir=out,
                     seed=3, library=False, cast=False)
        s = settings.read(os.path.join(out, settings.FILE_NAME))
        self.assertEqual((s["idea"], s["seed"], s["library"], s["model"]),
                         ("a mill village", 3, False, "stub-model"))

    def test_cli_runs_a_settings_file_with_overrides(self):
        path = os.path.join(self.tmp, "s.json")
        settings.write(path, a_settings(extensions=[]))
        seen = {}

        def fake_generate(**kw):
            seen.update(kw)
            return {"ok": True}
        with mock.patch.object(cli.api, "generate", fake_generate), \
                mock.patch("builtins.print"):
            code = cli.main(["generate", "--settings", path, "--provider", "p",
                             "--out", os.path.join(self.tmp, "o"), "--seed", "9"])
        self.assertEqual(code, 0)
        self.assertEqual((seen["idea"], seen["seed"], seen["library"]), ("a mill town", 9, False))
        self.assertEqual(seen["frame"]["genre"]["primary"], "Fantasy")
        self.assertEqual(seen["questionnaire"]["answers"]["genre"]["choices"], ["Fantasy"])

    def test_cli_needs_an_idea_or_a_settings_file(self):
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["generate", "--provider", "p", "--out", self.tmp]), 2)


if __name__ == "__main__":
    unittest.main()
