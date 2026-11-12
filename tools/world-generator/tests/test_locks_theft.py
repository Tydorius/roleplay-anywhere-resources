"""Anywhere RPG 1.0 locks, keys and theft on a generated world: the Python
port of the editor's lock helpers (world10.js) produces exactly the shapes
the game reads, a fixture world with a strongroom ships it locked with its
keeper holding the key, homes and sellers' workplaces count taking as theft
while inns do not, and a locked room on the player's only way to their start
cell or bed is left open and noted."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api, native
from worldgen.vendor import scenario_checks
from tests.test_sleep import CATALOGUE, _tmpl
from tests.util import load_plan


def locked_world():
    """A 24x24 map with a 6x6 house at [4,4], one door out on its south wall
    and that door hung, ready to lock."""
    scn = {
        "gridSize": [24, 24],
        "regions": [
            {"id": "house", "name": "House", "wall": "wood",
             "position": [4, 4], "size": [6, 6], "openings": [[6, 4]]},
        ],
        "entities": [], "objectTemplates": [], "itemTemplates": [],
    }
    native.hang_doors(scn)
    return scn


def person(scn, name):
    e = {"id": f"npc_{name.replace(' ', '')}", "type": "npc", "name": name,
         "pos": [10, 10], "size": [1, 1], "inventory": [], "statusEffects": []}
    scn["entities"].append(e)
    return e


WATCH_HOUSE_PLAN = {
    "name": "Weffling",
    "worldBackground": "A village with a watch house.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Weffling", "kind": "village", "sizeClass": "medium",
        "description": "The green.", "ground": "grass", "adjacentTo": [],
        "outdoor": [], "buildings": [
            {"name": "Weffling Watch House", "kind": "watch house",
             "sizeClass": "small", "purpose": "the village lock-up", "yard": None},
            {"name": "The Green Ox", "kind": "inn", "sizeClass": "medium",
             "purpose": "ale and lodging", "residents": 1, "yard": None},
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [],
    "templates": CATALOGUE + [_tmpl("Hearth", 2, 1, ["fire", "cook"])],
    "buildings": [
        {"name": "Weffling Watch House", "wall": "stone", "ground": "stone",
         "rooms": [{"name": "Office", "share": "large",
                    "purpose": "the watch's desk"},
                   {"name": "Cell", "share": "small",
                    "purpose": "the lock-up"}],
         "connections": [["Office", "Cell"]],
         "entrance": {"room": "Office", "side": "south"},
         "furniture": [{"template": "Oak Table", "room": "Office", "count": 1,
                        "hint": "center"},
                       {"template": "Straw Bed", "room": "Cell", "count": 1,
                        "hint": "wall:north"}],
         "yard": None},
        {"name": "The Green Ox", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Common Room", "share": "large",
                    "purpose": "ale and talk"},
                   {"name": "Guest Chamber", "share": "medium",
                    "purpose": "lodging for paying guests"}],
         "connections": [["Common Room", "Guest Chamber"]],
         "entrance": {"room": "Common Room", "side": "south"},
         "furniture": [{"template": "Straw Bed", "room": "Guest Chamber",
                        "count": 2, "hint": "row:north"}],
         "yard": None},
    ],
    "npcs": [
        {"name": "Jailer Jo", "gender": "female", "role": "jailer",
         "home": "Weffling Watch House", "work": "Weffling Watch House",
         "description": "Keeps the keys.", "physicalDescription": "keen"},
        {"name": "Guard One", "gender": "male", "role": "watch guard",
         "home": "Weffling Watch House", "work": "Weffling Watch House",
         "description": "Walks the rounds.", "physicalDescription": "tall"},
        {"name": "Guard Two", "gender": "male", "role": "watch guard",
         "home": "Weffling Watch House", "work": "Weffling Watch House",
         "description": "Walks the rounds.", "physicalDescription": "short"},
        {"name": "Innkeep Ida", "gender": "female", "role": "innkeeper",
         "home": "The Green Ox", "work": "The Green Ox",
         "description": "Pulls the ale.", "physicalDescription": "stout"},
    ],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "The Green Ox", "work": "Weffling",
               "description": "Passing through.", "physicalDescription": "cloaked"},
}


def watch_plan(room="Cell", npcs="all", player_home="The Green Ox",
               player_work="Weffling"):
    """The watch-house plan with the holding room, the cast and the player's
    home and work varied."""
    data = json.loads(json.dumps(WATCH_HOUSE_PLAN))
    for g in data["buildings"]:
        if g["name"] == "Weffling Watch House" and room != "Cell":
            for r in g["rooms"]:
                if r["name"] == "Cell":
                    r["name"] = room
                    r["purpose"] = f"the village {room.lower()}"
            g["connections"] = [["Office", room]]
    if npcs == "innkeep":
        data["npcs"] = [n for n in data["npcs"] if n["name"] == "Innkeep Ida"]
    elif npcs == "none":
        data["npcs"] = []
    data["player"]["home"] = player_home
    data["player"]["work"] = player_work
    return data


class TestLockShapes(unittest.TestCase):
    """The lock and key helpers against the editor's own shapes."""

    def test_set_locked_adds_the_exact_locked_effect_and_unlocks(self):
        scn = locked_world()
        door = scn["entities"][0]
        ids = native.Ids(scn)
        self.assertEqual(native.set_locked(scn, scn["regions"][0], True, ids),
                         {"count": 1})
        self.assertTrue(door["statusEffects"][0]["id"].startswith("se_"))
        sid = door["statusEffects"][0]["id"]
        self.assertEqual(door["statusEffects"],
                         [{"id": sid,
                           "def": {"desc": "locked", "emoji": "🔒",
                                   "type": "constant",
                                   "mechanics": [{"type": "locked"}]},
                           "appliedAt": 28800}])
        self.assertTrue(native.is_locked(door))
        self.assertTrue(native.region_locked(scn, scn["regions"][0]))
        self.assertEqual(native.set_locked(scn, scn["regions"][0], True, ids),
                         {"count": 0}, "a locked door stays as it is")
        self.assertEqual(native.set_locked(scn, scn["regions"][0], False, ids),
                         {"count": 1})
        self.assertEqual(door["statusEffects"], [])
        self.assertFalse(native.region_locked(scn, scn["regions"][0]))

    def test_region_doors_are_the_doors_its_wall_splits(self):
        scn = locked_world()
        doors = native.region_doors(scn, scn["regions"][0])
        self.assertEqual([d["name"] for d in doors], ["Door 1"])
        outside = {"id": "elsewhere", "name": "Elsewhere", "position": [0, 0],
                   "size": [2, 2]}
        self.assertEqual(native.region_doors(scn, outside), [])
        self.assertEqual(native.set_locked(scn, outside, True, native.Ids(scn)),
                         {"error": "Elsewhere has no doors to lock; "
                                   "hang doors first"})

    def test_give_key_makes_the_exact_template_and_stack_once(self):
        scn = locked_world()
        jo = person(scn, "Jo")
        ids = native.Ids(scn)
        native.give_key(scn, scn["regions"][0], jo, ids)
        tpl = scn["itemTemplates"][0]
        self.assertTrue(tpl["id"].startswith("itpl_"))
        self.assertEqual({k: v for k, v in tpl.items() if k != "id"},
                         {"name": "House key", "description": "", "type": "misc",
                          "quality": "common", "opens": "house"})
        stack = jo["inventory"][0]
        self.assertTrue(stack["id"].startswith("it_"))
        self.assertEqual({k: v for k, v in stack.items() if k != "id"},
                         {"templateId": tpl["id"], "count": 1})
        native.give_key(scn, scn["regions"][0], jo, ids)
        self.assertEqual(len(jo["inventory"]), 1, "one key is enough")
        self.assertEqual(len(scn["itemTemplates"]), 1)
        self.assertEqual([t["id"] for t in native.keys_to(scn, scn["regions"][0])],
                         [tpl["id"]])


class TestLockChoices(unittest.TestCase):
    """What the generator decides to lock, at spec level."""

    def _spec(self, data):
        world = worldgen.run(data, seed=1)
        return world, worldgen.build_spec(world, data)

    def test_the_cell_locks_and_the_head_of_the_watch_holds_the_key(self):
        _world, spec = self._spec(watch_plan())
        self.assertEqual(spec["nativeLocks"]["locks"],
                         [{"room": "Weffling Watch House Cell",
                           "holders": ["Jailer Jo", "Guard One"]}])
        self.assertEqual(spec["nativeLocks"]["theft"],
                         ["Weffling Watch House"],
                         "a staffed home that sells nothing still counts "
                         "taking as theft; the inn does not")

    def test_a_cell_with_nobody_stays_locked_and_keyless(self):
        _world, spec = self._spec(watch_plan(npcs="none"))
        self.assertEqual(spec["nativeLocks"]["locks"],
                         [{"room": "Weffling Watch House Cell", "holders": []}])

    def test_a_strongroom_with_nobody_is_left_unlocked(self):
        _world, spec = self._spec(watch_plan(room="Strongroom", npcs="none"))
        self.assertEqual(spec["nativeLocks"]["locks"], [])

    def test_the_player_holds_a_key_only_where_they_work_or_live(self):
        _world, spec = self._spec(watch_plan(
            npcs="none", player_work="Weffling Watch House"))
        self.assertEqual(spec["nativeLocks"]["locks"],
                         [{"room": "Weffling Watch House Cell",
                           "holders": ["The Wanderer"]}],
                         "the player works the watch, so the key is theirs")

    def test_a_locked_room_on_the_players_only_way_to_bed_is_skipped(self):
        data = watch_plan(npcs="innkeep", player_home="Weffling Watch House")
        world, spec = self._spec(data)
        self.assertEqual(spec["nativeLocks"]["locks"], [],
                         "the only bed is inside the cell")
        notes = world.metrics.get("objects", {}).get("unplaced", [])
        self.assertIn({"what": "room Weffling Watch House Cell",
                       "reason": "left unlocked: locking it would cut off "
                                 "the player's start cell or bed"},
                      notes)
        self.assertIn(("room Weffling Watch House Cell",
                       "left unlocked: locking it would cut off the player's "
                       "start cell or bed"),
                      world.failures)


class TestFixtureWorldLocks(unittest.TestCase):
    """medieval-glm-plan.json built end to end, with the mill's Meal Store
    rewritten in the plan as the miller's strongroom: the build stays clean,
    the strongroom's doors ship locked with the miller holding the key, homes
    and the smithy count taking as theft while the inn does not, and the
    vendored 1.0 checker reports nothing against the shipped world."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-locks-theft-")
        cls.data = load_plan("medieval-glm-plan.json")
        for g in cls.data["buildings"]:
            if g["name"] == "Millbrook Mill":
                for r in g["rooms"]:
                    if r["name"] == "Meal Store":
                        r["purpose"] = ("the mill's strongroom, iron-bound, "
                                        "where the toll grain and coin are "
                                        "locked away")
        cls.spec = worldgen.build_spec(worldgen.run(cls.data, seed=1), cls.data)
        cls.summary = api._layout_and_build(cls.data, seed=1, out_dir=cls.tmp)
        path = os.path.join(cls.summary["out"],
                            cls.summary["zip"][:-len(".zip")], "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)
        cls.path = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _region(self, name):
        return next(r for r in self.scn["regions"] if r["name"] == name)

    def _entity(self, name):
        return next(e for e in self.scn["entities"] if e["name"] == name)

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_the_strongroom_ships_locked(self):
        room = self._region("Millbrook Mill Meal Store")
        self.assertTrue(native.region_locked(self.scn, room))
        locked = [r["name"] for r in self.scn["regions"]
                  if native.region_locked(self.scn, r)]
        self.assertEqual(locked, ["Millbrook Mill Meal Store"],
                         "nothing else in the village locks")

    def test_the_miller_holds_the_strongroom_key(self):
        room = self._region("Millbrook Mill Meal Store")
        godwin = self._entity("Godwin Stokes")
        tpl = {t["id"]: t for t in self.scn["itemTemplates"]}
        keys = [tpl[s["templateId"]] for s in godwin["inventory"]
                if tpl.get(s["templateId"], {}).get("opens") == room["id"]]
        self.assertEqual([k["name"] for k in keys],
                         ["Millbrook Mill Meal Store key"])
        self.assertEqual([k["type"] for k in keys], ["misc"])
        self.assertEqual([k["quality"] for k in keys], ["common"])

    def test_homes_and_sellers_workplaces_are_theft_and_the_inn_is_not(self):
        theft = {r["name"] for r in self.scn["regions"]
                 if r.get("takingIsTheft") is True}
        self.assertIn("Alderman Hob's Cottage", theft, "a plain home")
        self.assertIn("Harrow Farmhouse", theft)
        self.assertIn("Thornbrook Smithy", theft,
                      "the smith sells what he makes")
        self.assertIn("Millbrook Mill", theft, "the miller sells flour")
        self.assertNotIn("The Sickle & Sheaf", theft, "an inn inherits")
        self.assertNotIn("St. Brigid's Chapel", theft, "a temple inherits")
        # rooms carry nothing of their own: they inherit from the building
        for r in self.scn["regions"]:
            if r["name"] != "Alderman Hob's Cottage" and \
                    r["name"].startswith("Alderman Hob's Cottage"):
                self.assertNotIn("takingIsTheft", r)
        # and nothing unwalled (outdoors) is ever flagged
        self.assertTrue(all(r.get("wall") for r in self.scn["regions"]
                            if r.get("takingIsTheft") is True))

    def test_no_ordinary_door_is_locked(self):
        doors = [e for e in self.scn["entities"] if native.is_door(self.scn, e)]
        self.assertTrue(doors)
        locked = [e["name"] for e in doors if native.is_locked(e)]
        mill = native.region_doors(self.scn,
                                   self._region("Millbrook Mill Meal Store"))
        self.assertEqual(sorted(locked), sorted(e["name"] for e in mill))

    def test_the_summary_lists_the_locked_rooms_and_theft_buildings(self):
        locks = self.summary["locks"]
        self.assertEqual(locks["rooms"],
                         [{"room": "Millbrook Mill Meal Store",
                           "keys": ["Godwin Stokes"]}])
        self.assertGreater(locks["theft_buildings"], 0)

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)

    def test_the_shipped_scenario_mods_check_is_clean(self):
        from worldgen import checks as checks_mod
        self.assertEqual(checks_mod.check_scenario_mods(self.path, self.spec),
                         [])


if __name__ == "__main__":
    unittest.main()
