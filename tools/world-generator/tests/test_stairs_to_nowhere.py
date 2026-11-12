"""No stairs to nowhere: a built world shows no staircase that leads
nowhere — the floors code places the real, linked stairs — and only a ruined
building keeps a stair, the one rising to its collapsed upper floor."""
import json
import os
import tempfile
import unittest

import worldgen
from tests import util
from worldgen import checks as checks_mod
from worldgen import phases

# the catalogue template names the small plan builds with
TEMPLATES = {"Staircase", "Oak table", "Stepladder", "Ladder"}


def small_plan(status):
    """One house on the moor with a 'Staircase' furniture line; its P1b
    status is the one thing the caller varies."""
    return {
        "name": "Stair Test",
        "worldBackground": "A cold moor with one hard-luck house.",
        "setting": {"era": "a cold medieval moor", "technology": "pre-industrial",
                    "density": "sparse", "climate": "cold moor"},
        "mapSize": "small",
        "templates": [
            {"name": "Staircase", "size": [1, 1], "walkability": 1,
             "tags": ["stairs"], "description": "A creaking stair of oak treads.",
             "physicalDescription": "worn treads and a rope handrail",
             "rule": "against the wall"},
            {"name": "Oak table", "size": [2, 1], "walkability": 0, "tags": [],
             "description": "A trestle table.", "physicalDescription": "planks",
             "rule": "the room's middle"},
            {"name": "Stepladder", "size": [1, 1], "walkability": 1, "tags": [],
             "description": "A short stepladder.", "physicalDescription": "two hinged stiles",
             "rule": "anywhere"},
            {"name": "Ladder", "size": [1, 1], "walkability": 1, "tags": [],
             "description": "A plain ladder.", "physicalDescription": "two rails and rungs",
             "rule": "against the wall"},
        ],
        "zones": [{
            "name": "Moor Edge", "kind": "hamlet", "sizeClass": "small",
            "description": "One house against the wind.", "ground": "grass",
            "adjacentTo": [], "outdoor": [],
            "buildings": [{"name": "The Old Watch House", "kind": "house",
                           "sizeClass": "medium",
                           "purpose": "the old watch house",
                           "status": status}],
        }],
        "buildings": [{
            "name": "The Old Watch House", "wall": "wood", "ground": "wood",
            "rooms": [{"name": "Hall", "share": "large", "purpose": "the cold hall"}],
            "connections": [], "entrance": {"room": "Hall", "side": "south"},
            "furniture": [
                {"template": "Oak table", "room": "Hall", "count": 1, "hint": "center"},
                {"template": "Staircase", "room": "Hall", "count": 1, "hint": "wall:north"},
            ],
            "yard": None,
        }],
        "roads": [],
    }


def portal_ends(world):
    """The builder entity names every linked pair stops at."""
    return {e for p in world.portals
            for e in (p["from"]["object"], p["to"]["object"])}


class TestBramblewickKeepsOnlyLinkedStairs(unittest.TestCase):
    """The live barony plan built with floors: its catalogue 'Staircase'
    furniture leads nowhere, so those objects go; the six real stair pairs
    and the two wall-walk passage pairs stay, linked both ways."""

    @classmethod
    def setUpClass(cls):
        cls.world = util.build_world("live/bramblewick-barony.plan.json",
                                     extensions=("floors",), seed=1)

    def test_no_stair_object_leads_nowhere(self):
        names = checks_mod.object_entity_names(self.world)
        ends = portal_ends(self.world)
        for o, name in names.items():
            if phases.STAIR_WORDS.search(o.template):
                self.assertIn(name, ends,
                              f"{o.template!r} object {name} leads nowhere")

    def test_the_real_stairs_still_link_both_ways(self):
        self.assertEqual(len(self.world.portals), 8)
        names = set(checks_mod.object_entity_names(self.world).values())
        for p in self.world.portals:
            self.assertTrue(p["twoWay"], p["name"])
            self.assertIn(p["from"]["object"], names, p["name"])
            self.assertIn(p["to"]["object"], names, p["name"])

    def test_the_dead_staircases_are_counted(self):
        self.assertEqual(self.world.metrics["stairs"],
                         {"dropped": 7, "ruined": 0})


class TestARuinKeepsItsStair(unittest.TestCase):
    """The same small plan twice: a home loses its 'Staircase' furniture,
    an abandoned building keeps the stair rising to its collapsed floor."""

    @classmethod
    def setUpClass(cls):
        cls.worlds = {status: worldgen.run(small_plan(status), seed=1)
                      for status in ("home", "abandoned")}

    def test_a_home_loses_the_staircase(self):
        world = self.worlds["home"]
        self.assertFalse([o for o in world.objects if o.template == "Staircase"])
        self.assertEqual(world.metrics["stairs"], {"dropped": 1, "ruined": 0})
        self.assertTrue(any(u["what"] == "stair Staircase in The Old Watch House"
                            for u in world.metrics["objects"]["unplaced"]))

    def test_an_abandoned_building_keeps_it(self):
        world = self.worlds["abandoned"]
        self.assertTrue([o for o in world.objects if o.template == "Staircase"])
        self.assertEqual(world.metrics["stairs"], {"dropped": 0, "ruined": 1})


class TestSanitizeDropsStairFurniture(unittest.TestCase):
    """The P3 furniture cleaning drops stair-named lines — ladders and step
    stools are not stairs — and a ruined building keeps them."""

    def _clean(self, ruined, furniture, storeys=None, upper=None):
        d = {"name": "The Old Watch House", "wall": "wood", "ground": "wood",
             "rooms": [{"name": "Hall", "share": "large", "purpose": "the hall"}],
             "connections": [], "entrance": {"room": "Hall", "side": "south"},
             "furniture": furniture, "yard": None}
        if storeys is not None:
            d["stairs"] = {"room": "Hall"}
            d["upper"] = upper or []
        log = []
        phases.sanitize_p3(d, "The Old Watch House", TEMPLATES, log,
                           storeys=storeys, ruined=ruined)
        return d, log

    def test_staircase_dropped_in_a_kept_building(self):
        d, log = self._clean(False, [{"template": "Staircase", "room": "Hall",
                                      "count": 1, "hint": ""}])
        self.assertEqual(d["furniture"], [])
        self.assertTrue(any("the code places the real stairs" in why
                            for (_what, why) in log), log)

    def test_staircase_kept_in_a_ruined_building(self):
        d, log = self._clean(True, [{"template": "Staircase", "room": "Hall",
                                     "count": 1, "hint": ""}])
        self.assertEqual(len(d["furniture"]), 1)
        self.assertFalse(any("the code places the real stairs" in why
                             for (_what, why) in log), log)

    def test_upper_storey_furniture_also_dropped(self):
        upper = [{"storey": 2,
                  "rooms": [{"name": "Landing", "share": "medium",
                             "purpose": "the stair head"}],
                  "connections": [],
                  "furniture": [{"template": "Staircase", "room": "Landing",
                                 "count": 1, "hint": ""}]}]
        d, _log = self._clean(False, [], storeys=2, upper=upper)
        self.assertEqual(d["upper"][0]["furniture"], [])
        d, _log = self._clean(True, [], storeys=2, upper=upper)
        self.assertEqual(len(d["upper"][0]["furniture"]), 1)

    def test_ladders_and_step_stools_are_not_stairs(self):
        furniture = [{"template": name, "room": "Hall", "count": 1, "hint": ""}
                     for name in ("Stepladder", "Ladder")]
        d, log = self._clean(False, furniture)
        self.assertEqual([f["template"] for f in d["furniture"]],
                         ["Stepladder", "Ladder"])
        self.assertFalse(any("stairs" in why for (_what, why) in log), log)

    def test_the_stair_words_and_the_floors_suffixes(self):
        for name in ("Staircase", "stairway up the wall", "The Stairwell",
                     "Back stairs"):
            self.assertTrue(phases.stair_furniture_name(name), name)
        for name in ("Stepladder", "Ladder", "steps to the loft",
                     "The Old Hall stairs up", "The Old Hall stairs down",
                     "Thornrose Court passage"):
            self.assertFalse(phases.stair_furniture_name(name), name)

    def test_what_makes_a_building_a_ruin(self):
        self.assertTrue(phases.ruined_building({"status": "abandoned"}))
        self.assertTrue(phases.ruined_building({"condition": "ruined"}))
        for words in ("ruins", "ruined", "derelict", "collapsed",
                      "burnt-out", "gutted"):
            self.assertTrue(phases.ruined_building(
                {"name": f"The {words} House"}), words)
        self.assertFalse(phases.ruined_building(
            {"status": "home", "condition": "kept",
             "name": "The Old Watch House", "kind": "house", "purpose": "watch"}))


def _stair_scenario(region_name, region_description, portal=None):
    """A shipped scenario with one portal-less 'Staircase' object inside the
    given region."""
    return {
        "regions": [{"name": region_name, "id": "rgn_1",
                     "position": [0, 0], "size": [6, 6],
                     "description": region_description}],
        "objectTemplates": [{"id": "otpl_s", "name": "Staircase",
                             "size": [1, 1], "walkability": 1.0}],
        "entities": [{"id": "ent_1", "type": "object", "name": "Staircase 1",
                      "pos": [2, 2], "size": [1, 1], "hp": 10, "maxHp": 10,
                      "inventory": [], "statusEffects": [],
                      "templateId": "otpl_s", "portal": portal}],
    }


class TestShippedScenarioNet(unittest.TestCase):
    """The shipped-scenario check: a stair-named object with no portal is a
    stair to nowhere — unless it rises in a region the scenario calls a
    ruin."""

    def _issues(self, scenario):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scenario.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(scenario, f)
            return checks_mod.check_scenario_mods(path, {})

    def test_a_portalless_staircase_in_a_home_is_reported(self):
        issues = self._issues(_stair_scenario("Hall", "the hall of a house"))
        self.assertTrue(any("leads nowhere" in i for i in issues), issues)

    def test_the_same_stair_in_a_ruin_is_not(self):
        issues = self._issues(_stair_scenario("The Collapsed Hall",
                                              "what is left of the house"))
        self.assertFalse([i for i in issues if "leads nowhere" in i], issues)

    def test_a_linked_stair_object_is_not(self):
        issues = self._issues(_stair_scenario("Hall", "the hall of a house",
                                              portal={"to": "ent_2"}))
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
