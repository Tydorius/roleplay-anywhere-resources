"""Room library step 4: generation with the library (the default). P1 gets
the band and each building's wealth and condition, P3 plans rooms by purpose
(or is skipped when a suite fits the building's kind), and code furnishes
them before plan.json is written, so the plan rebuilds with no library."""
import json
import os
import tempfile
import unittest

from tests.test_model import (CANNED_COTTAGE, CANNED_MILL, ScriptedClient, _dump,
                              canned_replies)
from worldgen import api, library_plan, phases

LIB_P3 = {"suite": None, "wall": "wood", "ground": "packed earth",
          "rooms": [{"name": "Grinding floor", "share": "large", "use": "mill",
                     "purpose": "a floor white with flour round the millstones"},
                    {"name": "Loft", "share": "small", "use": "bedroom",
                     "purpose": "a cramped sleeping loft over the floor"}],
          "connections": [["Grinding floor", "Loft"]],
          "entrance": {"room": "Grinding floor", "side": "south"},
          "wealth": {}, "yard": None}


class LibraryClient(ScriptedClient):
    """The canned replies for every phase except P3, which gets a library
    reply (rooms with purposes, no furniture)."""

    def call(self, phase, system, user, validate=None, max_retries=2):
        if phase.startswith("p3-"):
            self.p3_prompts.append(user)
            self._queue.insert(0, _dump(LIB_P3))
        return super().call(phase, system, user, validate, max_retries)


def client():
    queue = [r for r in canned_replies() if r not in (_dump(CANNED_MILL), _dump(CANNED_COTTAGE))]
    c = LibraryClient(queue)
    c.p3_prompts = []
    return c


class TestGenerateWithTheLibrary(unittest.TestCase):
    def test_the_library_furnishes_the_rooms(self):
        c = client()
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c, seed=3, cast=False, out_dir=tmp)
            self.assertTrue(summary["ok"], summary)
            self.assertEqual(summary["validator_errors"], 0, summary)
            with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
            # a re-roll from the saved plan needs no library and no model
            again = api.relayout(os.path.join(tmp, "plan.json"), seed=4,
                                 out_dir=os.path.join(tmp, "again"))
            self.assertTrue(again["ok"], again)
        self.assertIn("library", plan)
        self.assertIn(plan["setting"]["band"], ("medieval", "industrial", "modern", "scifi"))
        lib_templates = {t["name"] for t in plan["templates"] if t.get("libraryId")}
        self.assertTrue(lib_templates)
        for b in plan["buildings"]:
            self.assertTrue(b["furniture"], b["name"])
            self.assertTrue(all(f["template"] in lib_templates for f in b["furniture"]), b["name"])
        for z in plan["zones"]:
            for b in z["buildings"]:
                self.assertIn(b["wealth"], ("poor", "modest", "wealthy", "elite"))
                self.assertIn(b["condition"], ("ruined", "worn", "kept", "pristine"))
        # the library P3 prompt carries no catalogue of furniture
        for prompt in c.p3_prompts:
            self.assertIn("ROOM PURPOSES", prompt)
            self.assertNotIn("CATALOGUE (name", prompt)

    def test_the_old_method_is_still_there(self):
        c = client()
        self.assertTrue(callable(phases.run_phases))
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=type("C", (ScriptedClient,), {})(
                canned_replies()), seed=3, cast=False, out_dir=tmp, library=False)
            with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
        self.assertTrue(summary["ok"], summary)
        self.assertNotIn("library", plan)
        self.assertFalse(any(t.get("libraryId") for t in plan["templates"]))


class TestLibraryPlanHelpers(unittest.TestCase):
    def test_band_from_the_setting_words(self):
        lib = library_plan.load()
        self.assertEqual(library_plan.band_of(lib, {"band": "scifi"}), "scifi")
        self.assertEqual(library_plan.band_of(lib, {"genre": "cyberpunk"}), "scifi")
        self.assertEqual(library_plan.band_of(lib, {"era": "Victorian"}), "industrial")
        self.assertEqual(library_plan.band_of(lib, {}), "medieval")

    def test_sleepers_go_to_the_right_rooms(self):
        lib = library_plan.load()
        rooms = [{"name": "Main", "use": "living_room"}, {"name": "Master", "use": "master_bedroom"},
                 {"name": "Kids", "use": "bedroom"}, {"name": "Spare", "use": "guest_room"}]
        s = library_plan._sleepers(lib, rooms, residents=5, couples=1)
        self.assertEqual(s["Master"], (0, 1))
        self.assertEqual(s["Kids"], (3, 0))
        self.assertEqual(s["Main"], (0, 0))
        self.assertEqual(s["Spare"][1], 0)
        self.assertGreaterEqual(s["Spare"][0], 1)

    def test_a_home_without_a_bedroom_gets_one(self):
        lib = library_plan.load()
        design = {"rooms": [{"name": "Hall", "share": "large", "use": "living_room"}],
                  "connections": [], "entrance": {"room": "Hall"}}
        log = []
        library_plan.ensure_sleep_room(design, {"name": "Hut", "residents": 2}, lib, log)
        self.assertEqual(len(design["rooms"]), 2)
        self.assertEqual(design["connections"], [["Hall", "Bedroom"]])

    def test_check_catches_bad_purposes(self):
        lib = library_plan.load()
        errs = library_plan.check_p3({"rooms": [{"name": "A", "use": "throne_room"}],
                                      "entrance": {"room": "A"}}, "X", lib)
        self.assertTrue(any("not in the purpose list" in e for e in errs))
        self.assertEqual(library_plan.check_p3(dict(LIB_P3), "X", lib), [])


if __name__ == "__main__":
    unittest.main()
