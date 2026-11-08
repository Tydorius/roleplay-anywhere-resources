"""Room library step 4: generation with the library (the default). P1 gets
the band and each building's wealth and condition, P3 plans rooms by purpose
(or is skipped when a suite fits the building's kind), and code furnishes
them before plan.json is written, so the plan rebuilds with no library."""
import json
import os
import tempfile
import unittest

import copy

from tests.test_model import (CANNED_COTTAGE, CANNED_MILL, CANNED_P1, ScriptedClient, _dump,
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

    reply = LIB_P3

    def call(self, phase, system, user, validate=None, max_retries=2):
        self.prompts[phase] = user
        if phase.startswith("p3-"):
            self.p3_prompts.append(user)
            self._queue.insert(0, _dump(self.reply))
        return super().call(phase, system, user, validate, max_retries)


class RecordingClient(ScriptedClient):
    """The canned replies as they are, every prompt kept."""

    def call(self, phase, system, user, validate=None, max_retries=2):
        self.prompts = getattr(self, "prompts", {})
        self.prompts[phase] = user
        return super().call(phase, system, user, validate, max_retries)


def client():
    queue = [r for r in canned_replies() if r not in (_dump(CANNED_MILL), _dump(CANNED_COTTAGE))]
    c = LibraryClient(queue)
    c.p3_prompts = []
    c.prompts = {}
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


class TestUnitsAndAnOutdoorCatalogue(unittest.TestCase):
    def test_a_unit_building_is_furnished_from_the_library(self):
        c = client()
        p1 = copy.deepcopy(CANNED_P1)
        mill = next(b for z in p1["zones"] for b in z["buildings"] if b["name"] == "The Old Mill")
        mill["units"] = {"name": "Guest room", "count": 3, "residents": 1}
        c._queue[0] = _dump(p1)
        c.reply = dict(LIB_P3, unit={
            "rooms": [{"name": "Guest room", "share": "medium", "use": "guest_room",
                       "purpose": "a narrow room under the eaves"}],
            "connections": [], "entrance": {"room": "Guest room", "side": "south"}})
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c, seed=3, cast=False, out_dir=tmp)
            self.assertTrue(summary["ok"], summary)
            self.assertEqual(summary["validator_errors"], 0, summary)
            with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
        lib_templates = {t["name"] for t in plan["templates"] if t.get("libraryId")}
        design = next(b for b in plan["buildings"] if b["name"] == "The Old Mill")
        self.assertTrue(design["unit"]["furniture"])
        self.assertTrue(all(f["template"] in lib_templates for f in design["unit"]["furniture"]))
        # the P3 prompt said the building repeats units
        self.assertTrue(any("THIS BUILDING REPEATS UNITS" in p for p in c.p3_prompts))

    def test_p2_is_told_the_library_does_the_interiors(self):
        c = client()
        with tempfile.TemporaryDirectory() as tmp:
            api.generate("a mill village", client=c, seed=3, cast=False, out_dir=tmp)
        self.assertIn("ROOM LIBRARY", c.prompts["p2"])
        c2 = RecordingClient(canned_replies())
        with tempfile.TemporaryDirectory() as tmp:
            api.generate("a mill village", client=c2, seed=3, cast=False, out_dir=tmp, library=False)
        self.assertNotIn("ROOM LIBRARY", c2.prompts["p2"])


class TestBuildingsFit(unittest.TestCase):
    def test_every_suite_furnishes_without_dropping_a_piece(self):
        """Each suite as a skipped-P3 building, trimmed to five rooms and
        furnished (compactly when it would overflow): the building packer
        drops nothing. Past five rooms the packer dropped almost every piece."""
        import random
        lib = library_plan.load()
        bad = []
        for sid, s in sorted(lib.suites.items()):
            band = s["bands"][0]
            lo, hi = s["residents"]
            couples = 1 if any(r["purpose"] == "master_bedroom" for r in s["rooms"]) else 0
            b = {"name": "B", "kind": s["kinds"][0], "sizeClass": s["sizeClasses"][0],
                 "residents": max(lo, min(hi, 2 + couples)), "couples": couples}
            d = library_plan.trim_rooms(
                lib, library_plan.design_from_suite(s, b, band, random.Random(1)), b)
            d["furniture"] = []
            reg = library_plan.registry_for(lib, "w", taken=set())
            library_plan.expand_fitting(lib, reg, d, b, band, None, "w", [])
            self.assertLessEqual(len(d["rooms"]), library_plan.MAX_ROOMS, sid)
            lost = library_plan.drops_at_layout(d, b, reg)
            if lost:
                bad.append((sid, lost))
        self.assertEqual(bad, [])

    def test_trim_keeps_the_entrance_and_the_beds(self):
        lib = library_plan.load()
        d = {"rooms": [{"name": n, "share": "small", "use": u} for n, u in
                       [("Hall", "lobby"), ("Study", "study"), ("Library", "library"),
                        ("Pantry", "pantry"), ("Cellar", "cellar"), ("Master", "master_bedroom"),
                        ("Kids", "bedroom")]],
             "connections": [["Hall", "Study"], ["Hall", "Master"], ["Master", "Kids"]],
             "entrance": {"room": "Hall"}}
        library_plan.trim_rooms(lib, d, {"residents": 4, "couples": 1})
        names = [r["name"] for r in d["rooms"]]
        self.assertEqual(len(names), 5)
        for n in ("Hall", "Master", "Kids"):
            self.assertIn(n, names)
        reach = {"Hall"}
        for _ in range(5):
            for a, c in d["connections"]:
                if a in reach or c in reach:
                    reach |= {a, c}
        self.assertEqual(reach, set(names))


class TestLibraryPlanHelpers(unittest.TestCase):
    def test_a_missing_unit_design_gets_a_sensible_room(self):
        u = library_plan.default_unit({"kind": "inn", "units": {"name": "Room", "count": 4}})
        self.assertEqual(u["rooms"][0]["use"], "guest_room")
        u = library_plan.default_unit({"kind": "starship", "units": {"name": "Cabin", "count": 6}})
        self.assertEqual(u["rooms"][0]["use"], "crew_quarters")

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
