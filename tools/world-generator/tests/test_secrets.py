"""Anywhere RPG 1.0 secret doors on a generated world, under the opt-in
secret-passages extension: the Python port of the editor's secret-passage
helpers (world10.js) produces exactly the shapes the game's
secret-passages mod reads, a manor's priest hole ships hidden and known to
its household, a castle gets one hidden interior doorway of its own
choosing that keeps every room reachable, a village of plain houses hides
nothing, and a doorway on the player's only way to their bed is left
ordinary and noted — while locks and secrets stack on the same door.
Without the extension nothing is hidden and no mod data is written."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api, native
from worldgen.vendor import scenario_checks
from tests.test_sleep import CATALOGUE, _tmpl

# secret doors are opt-in: every build here that expects one turns this on
EXT = ("secret-passages",)


def secret_world():
    """A 24x24 map with a 6x6 house at [4,4] — its front door on the south
    wall, two doors onto a 4x4 vault at [5,10] — hung, ready to hide."""
    scn = {
        "gridSize": [24, 24],
        "regions": [
            {"id": "house", "name": "House", "wall": "wood",
             "position": [4, 4], "size": [6, 6],
             "openings": [[6, 4], [6, 9], [7, 9]]},
            {"id": "vault", "name": "Vault", "wall": "wood",
             "position": [5, 10], "size": [4, 4],
             "openings": [[6, 10], [7, 10]]},
        ],
        "entities": [], "objectTemplates": [], "itemTemplates": [],
    }
    native.hang_doors(scn)
    return scn


def _inn():
    """A two-room inn for the player to lodge at, so their bed never lands
    in the room under test."""
    return {"name": "The Gate Inn", "wall": "wood", "ground": "wood",
            "rooms": [{"name": "Common Room", "share": "large",
                       "purpose": "ale and talk"},
                      {"name": "Guest Chamber", "share": "medium",
                       "purpose": "lodging for paying guests"}],
            "connections": [["Common Room", "Guest Chamber"]],
            "entrance": {"room": "Common Room", "side": "south"},
            "furniture": [{"template": "Straw Bed", "room": "Guest Chamber",
                           "count": 1, "hint": "wall:north"}],
            "yard": None}


_INN_ZONE = {"name": "The Gate Inn", "kind": "inn", "sizeClass": "small",
             "purpose": "ale and lodging", "residents": 1, "yard": None}


def _plan(name, buildings, zone_buildings, npcs, player):
    """A one-village plan on the shared catalogue, with the player's work
    defaulting to the village itself."""
    player = dict(player)
    player.setdefault("work", name)
    return {
        "name": name,
        "worldBackground": "A village.",
        "setting": {"era": "medieval", "technology": "iron",
                    "density": "sparse", "climate": "mild"},
        "mapSize": "small",
        "zones": [{
            "name": name, "kind": "village", "sizeClass": "medium",
            "description": "The green.", "ground": "grass", "adjacentTo": [],
            "outdoor": [], "buildings": zone_buildings,
            "dressing": {"paths": "dirt", "props": [], "filler": []},
        }],
        "roads": [],
        "templates": CATALOGUE + [_tmpl("Hearth", 2, 1, ["fire", "cook"])],
        "buildings": buildings,
        "npcs": npcs,
        "player": player,
    }


_AT_INN = {"name": "The Chapman", "gender": "female", "role": "pedlar",
           "home": "The Gate Inn",
           "description": "Selling ribbon.", "physicalDescription": "worn"}


def manor_plan():
    """Netherby Manor: a priest hole off the master bedroom, its household
    at work in the manor and the player lodging at the village inn."""
    return _plan("Netherby", [
        {"name": "Netherby Manor", "wall": "stone", "ground": "stone",
         "rooms": [
             {"name": "Great Hall", "share": "large",
              "purpose": "the lord's table"},
             {"name": "Master Bedroom", "share": "medium",
              "purpose": "the lord and lady's bedchamber"},
             {"name": "Priest Hole", "share": "small",
              "purpose": "a hidden room behind the panelling"}],
         "connections": [["Great Hall", "Master Bedroom"],
                         ["Master Bedroom", "Priest Hole"]],
         "entrance": {"room": "Great Hall", "side": "south"},
         "furniture": [
             {"template": "Oak Table", "room": "Great Hall", "count": 1,
              "hint": "center"},
             {"template": "Straw Bed", "room": "Master Bedroom", "count": 1,
              "hint": "wall:north"},
             {"template": "Straw Bed", "room": "Priest Hole", "count": 1,
              "hint": "wall:north"}],
         "yard": None}, _inn()],
        [{"name": "Netherby Manor", "kind": "manor", "sizeClass": "large",
          "purpose": "the lord's country seat", "yard": None}, _INN_ZONE],
        [{"name": "Steward Sam", "gender": "male", "role": "steward",
          "home": "Netherby Manor", "work": "Netherby Manor",
          "description": "Keeps the accounts.", "physicalDescription": "neat"},
         {"name": "Marta May", "gender": "female", "role": "maid",
          "home": "Netherby Manor", "work": "Netherby Manor",
          "description": "Sweeps the hall.", "physicalDescription": "small"}],
        _AT_INN)


def castle_plan():
    """Ashfell Castle: a great hall with the study, cellar, barracks and
    chapel ranged off it, garrisoned; the player lodges at the inn."""
    return _plan("Ashfell", [
        {"name": "Ashfell Castle", "wall": "stone", "ground": "stone",
         "rooms": [
             {"name": "Great Hall", "share": "large",
              "purpose": "the lord's table and the hearth"},
             {"name": "Study", "share": "medium",
              "purpose": "the lord's books"},
             {"name": "Cellar", "share": "medium",
              "purpose": "ale in casks"},
             {"name": "Guard Barracks", "share": "medium",
              "purpose": "the garrison's beds"},
             {"name": "Chapel", "share": "medium",
              "purpose": "prayers for the household"}],
         "connections": [["Great Hall", "Study"], ["Great Hall", "Cellar"],
                         ["Great Hall", "Guard Barracks"],
                         ["Great Hall", "Chapel"]],
         "entrance": {"room": "Great Hall", "side": "south"},
         "furniture": [
             {"template": "Oak Table", "room": "Great Hall", "count": 1,
              "hint": "center"},
             {"template": "Oak Table", "room": "Study", "count": 1,
              "hint": "center"},
             {"template": "Iron Chest", "room": "Cellar", "count": 1,
              "hint": "corner"},
             {"template": "Straw Bed", "room": "Guard Barracks", "count": 2,
              "hint": "row:north"},
             {"template": "Stone Altar", "room": "Chapel", "count": 1,
              "hint": "wall:north"}],
         "yard": None}, _inn()],
        [{"name": "Ashfell Castle", "kind": "castle", "sizeClass": "large",
          "purpose": "the lord's stronghold", "yard": None}, _INN_ZONE],
        [{"name": "Captain Hale", "gender": "male", "role": "castle captain",
          "home": "Ashfell Castle", "work": "Ashfell Castle",
          "description": "Keeps the gate.", "physicalDescription": "grey"},
         {"name": "Guard Gault", "gender": "male", "role": "guard",
          "home": "Ashfell Castle", "work": "Ashfell Castle",
          "description": "Walks the wall.", "physicalDescription": "tall"}],
        _AT_INN)


def hamlet_plan():
    """A hamlet of two cottages and nothing grander: nowhere to hide."""
    return _plan("Ambleton", [
        {"name": "Dun Cottage", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "large",
                    "purpose": "meals by the hearth"},
                   {"name": "Bedroom", "share": "small",
                    "purpose": "sleeping"}],
         "connections": [["Main Room", "Bedroom"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [{"template": "Oak Table", "room": "Main Room",
                        "count": 1, "hint": "center"},
                       {"template": "Straw Bed", "room": "Bedroom",
                        "count": 1, "hint": "wall:north"}],
         "yard": None},
        {"name": "Croft Cottage", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "large",
                    "purpose": "meals by the hearth"},
                   {"name": "Bedroom", "share": "small",
                    "purpose": "sleeping"}],
         "connections": [["Main Room", "Bedroom"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [{"template": "Oak Table", "room": "Main Room",
                        "count": 1, "hint": "center"},
                       {"template": "Straw Bed", "room": "Bedroom",
                        "count": 1, "hint": "wall:north"}],
         "yard": None}],
        [{"name": "Dun Cottage", "kind": "cottage", "sizeClass": "small",
          "purpose": "a cottage", "yard": None},
         {"name": "Croft Cottage", "kind": "cottage", "sizeClass": "small",
          "purpose": "a cottage", "yard": None}],
        [{"name": "Goodwife Dun", "gender": "female", "role": "cottager",
          "home": "Dun Cottage", "work": "Ambleton",
          "description": "Keeps the garden.", "physicalDescription": "bent"},
         {"name": "Old Croft", "gender": "male", "role": "cottager",
          "home": "Croft Cottage", "work": "Ambleton",
          "description": "Mends fences.", "physicalDescription": "lean"}],
        {"name": "The Wanderer", "gender": "female", "role": "traveller",
         "home": "Dun Cottage",
         "description": "Passing through.", "physicalDescription": "cloaked"})


def rectory_plan():
    """The Old Rectory: the player's own lodging, with their only bed in
    the priest hole — hiding its one doorway would wall the bed in."""
    return _plan("Charteris", [
        {"name": "The Old Rectory", "wall": "wood", "ground": "wood",
         "rooms": [
             {"name": "Main Room", "share": "large",
              "purpose": "meals by the hearth"},
             {"name": "Priest Hole", "share": "small",
              "purpose": "a hidden room behind the pantry"}],
         "connections": [["Main Room", "Priest Hole"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [
             {"template": "Oak Table", "room": "Main Room", "count": 1,
              "hint": "center"},
             {"template": "Straw Bed", "room": "Priest Hole", "count": 1,
              "hint": "wall:north"}],
         "yard": None}],
        [{"name": "The Old Rectory", "kind": "house", "sizeClass": "small",
          "purpose": "the player's lodging", "yard": None}],
        [],
        {"name": "The Wanderer", "gender": "female", "role": "traveller",
         "home": "The Old Rectory",
         "description": "Staying the night.", "physicalDescription": "cloaked"})


def strongroom_plan():
    """Marchfield Manor: a hidden chamber that is also the manor's
    strongroom, so its doorway locks and hides at once."""
    return _plan("Marchfield", [
        {"name": "Marchfield Manor", "wall": "stone", "ground": "stone",
         "rooms": [
             {"name": "Great Hall", "share": "large",
              "purpose": "the lord's table"},
             {"name": "Hidden Chamber", "share": "medium",
              "purpose": "the manor's strongroom, iron-bound"}],
         "connections": [["Great Hall", "Hidden Chamber"]],
         "entrance": {"room": "Great Hall", "side": "south"},
         "furniture": [
             {"template": "Oak Table", "room": "Great Hall", "count": 1,
              "hint": "center"},
             {"template": "Iron Chest", "room": "Hidden Chamber", "count": 1,
              "hint": "corner"}],
         "yard": None}, _inn()],
        [{"name": "Marchfield Manor", "kind": "manor", "sizeClass": "medium",
          "purpose": "the lord's seat", "yard": None}, _INN_ZONE],
        [{"name": "Sim Steward", "gender": "male", "role": "steward",
          "home": "Marchfield Manor", "work": "Marchfield Manor",
          "description": "Keeps the keys.", "physicalDescription": "thin"}],
        _AT_INN)


class TestSecretShapes(unittest.TestCase):
    """The secret-door helpers against the mod's own shapes."""

    def test_set_secret_adds_the_exact_concealed_effect_and_only_once(self):
        scn = secret_world()
        door = next(e for e in scn["entities"] if native.is_door(scn, e))
        ids = native.Ids(scn)
        native.set_secret(scn, door, ids)
        self.assertTrue(door["statusEffects"][0]["id"].startswith("se_"))
        sid = door["statusEffects"][0]["id"]
        self.assertEqual(door["statusEffects"],
                         [{"id": sid,
                           "def": {"desc": "secret passage", "emoji": "🕳️",
                                   "type": "constant",
                                   "mechanics": [{"type": "concealed"}]},
                           "appliedAt": 28800}])
        self.assertTrue(native.is_secret(door))
        self.assertTrue(native.is_secret_fx(door["statusEffects"][0]))
        native.set_secret(scn, door, ids)
        self.assertEqual(len(door["statusEffects"]), 1,
                         "one concealment is enough")

    def test_doors_between_are_only_the_doorway_the_rooms_share(self):
        scn = secret_world()
        house, vault = scn["regions"]
        between = native.doors_between(scn, house, vault)
        self.assertEqual(sorted(d["name"] for d in between),
                         sorted(d["name"] for d in native.region_doors(scn, vault)))
        front = [d for d in native.region_doors(scn, house)
                 if d not in between]
        self.assertEqual(len(front), 1, "the front door out stays ordinary")
        outside = {"id": "elsewhere", "name": "Elsewhere",
                   "position": [0, 0], "size": [2, 2]}
        self.assertEqual(native.doors_between(scn, house, outside), [])

    def test_locks_and_secrets_stack_on_the_same_door(self):
        scn = secret_world()
        house, vault = scn["regions"]
        ids = native.Ids(scn)
        native.set_locked(scn, vault, True, ids)
        for door in native.doors_between(scn, house, vault):
            native.set_secret(scn, door, ids)
        for door in native.doors_between(scn, house, vault):
            self.assertTrue(native.is_locked(door))
            self.assertTrue(native.is_secret(door))
            self.assertEqual([fx["def"]["desc"] for fx in door["statusEffects"]],
                             ["locked", "secret passage"])

    def test_add_secret_data_merges_into_existing_arpg_mods(self):
        scn = {"arpgMods": {"lights": {"lamps": ["a"]}}}
        door = {"id": "door_9"}
        native.add_secret_data(scn, door, ["Maren Harrow"])
        self.assertEqual(scn["arpgMods"],
                         {"lights": {"lamps": ["a"]},
                          "secretPassages": {"passages": {
                              "door_9": {"knownBy": ["Maren Harrow"]}}}})
        native.add_secret_data(scn, door, ["Maren Harrow"])
        self.assertEqual(scn["arpgMods"]["secretPassages"]["passages"],
                         {"door_9": {"knownBy": ["Maren Harrow"]}},
                         "recorded once per door, not stacked")


class TestSecretChoices(unittest.TestCase):
    """What the generator decides to hide, at spec level, with the
    extension on."""

    def _spec(self, data):
        world = worldgen.run(data, seed=1, extensions=EXT)
        return world, worldgen.build_spec(world, data)

    def test_the_priest_hole_is_hidden_and_known_to_the_household(self):
        _world, spec = self._spec(manor_plan())
        self.assertEqual(spec["nativeSecrets"],
                         [{"between": ["Netherby Manor Priest Hole",
                                       "Netherby Manor Master Bedroom"],
                           "knownBy": ["Steward Sam", "Marta May"]}])

    def test_the_castle_hides_exactly_one_interior_doorway(self):
        world, spec = self._spec(castle_plan())
        secrets = spec["nativeSecrets"]
        self.assertEqual(len(secrets), 1)
        between = secrets[0]["between"]
        self.assertNotEqual(between[0], between[1])
        self.assertTrue(all(r.startswith("Ashfell Castle ") for r in between),
                        between)
        self.assertEqual(secrets[0]["knownBy"],
                         ["Captain Hale", "Guard Gault"])
        rooms = world.metrics["rooms"]
        self.assertEqual(rooms["unreachable"], [],
                         "every room stays reachable without the hidden door")
        self.assertEqual(rooms["reachable"], rooms["total"])
        _world2, spec2 = self._spec(castle_plan())
        self.assertEqual(spec2["nativeSecrets"], secrets,
                         "the same seed hides the same doorway")

    def test_a_hamlet_of_houses_hides_nothing(self):
        _world, spec = self._spec(hamlet_plan())
        self.assertEqual(spec["nativeSecrets"], [])

    def test_a_priest_hole_on_the_players_only_way_to_bed_is_skipped(self):
        world, spec = self._spec(rectory_plan())
        self.assertEqual(spec["nativeSecrets"], [],
                         "the only bed is inside the priest hole")
        notes = world.metrics.get("objects", {}).get("unplaced", [])
        self.assertIn({"what": "room The Old Rectory Priest Hole",
                       "reason": "left an ordinary door: a secret one would "
                                 "cut off the player's start cell or bed"},
                      notes)
        self.assertIn(("room The Old Rectory Priest Hole",
                       "left an ordinary door: a secret one would cut off "
                       "the player's start cell or bed"),
                      world.failures)

    def test_locks_and_secrets_coexist_on_the_same_room(self):
        _world, spec = self._spec(strongroom_plan())
        self.assertEqual(spec["nativeSecrets"],
                         [{"between": ["Marchfield Manor Hidden Chamber",
                                       "Marchfield Manor Great Hall"],
                           "knownBy": ["Sim Steward"]}])
        self.assertEqual(spec["nativeLocks"]["locks"],
                         [{"room": "Marchfield Manor Hidden Chamber",
                           "holders": ["Sim Steward"]}])


class TestSecretsAreOptIn(unittest.TestCase):
    """Secret doors are the opt-in secret-passages extension: a build
    without it hides nothing and writes no mod data."""

    def test_without_the_extension_nothing_is_hidden(self):
        data = manor_plan()
        spec = worldgen.build_spec(worldgen.run(data, seed=1), data)
        self.assertEqual(spec["nativeSecrets"], [])
        tmp = tempfile.mkdtemp(prefix="worldgen-secrets-")
        try:
            summary = api._layout_and_build(manor_plan(), seed=1, out_dir=tmp)
            path = os.path.join(summary["out"],
                                summary["zip"][:-len(".zip")], "scenario.json")
            with open(path, "r", encoding="utf-8") as f:
                scn = json.load(f)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(summary["secret_doors"], 0)
        self.assertNotIn("arpgMods", scn)
        concealed = [e["name"] for e in scn["entities"]
                     for fx in e.get("statusEffects") or []
                     for m in (fx.get("def") or {}).get("mechanics") or []
                     if m.get("type") == "concealed"]
        self.assertEqual(concealed, [], "no door carries the concealed effect")
        # the priest hole is still there, behind an ordinary door
        hole, bedroom = (next(r for r in scn["regions"] if r["name"] == name)
                         for name in ("Netherby Manor Priest Hole",
                                      "Netherby Manor Master Bedroom"))
        doors = native.doors_between(scn, hole, bedroom)
        self.assertTrue(doors)
        self.assertFalse(any(native.is_secret(d) for d in doors))


class TestSecretChecks(unittest.TestCase):
    """What the shipped-scenario check says about secret trouble."""

    def test_missing_rooms_and_stray_passages_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scenario.json")
            scn = {"gridSize": [8, 8], "regions": [], "entities": [],
                   "objectTemplates": [], "itemTemplates": [],
                   "arpgMods": {"secretPassages": {"passages": {
                       "nope": {"knownBy": []}}}}}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(scn, f)
            from worldgen import checks as checks_mod
            spec = {"nativeSecrets": [{"between": ["Nowhere", "Nothing"],
                                       "knownBy": []}]}
            issues = checks_mod.check_scenario_mods(path, spec)
            self.assertIn("secret doorway between 'Nowhere' and 'Nothing' "
                          "names a room the built scenario does not have",
                          issues)
            self.assertIn("secretPassages passage 'nope' is no door with "
                          "the concealed effect", issues)


class TestFixtureWorldSecrets(unittest.TestCase):
    """medieval-glm-plan.json built end to end with the extension on, the
    farmhouse's Larder rewritten in the plan as the family's priest hole:
    the build stays clean, the hole's doors ship hidden with the farmwife
    the only one who knows them, the summary counts the one secret door,
    and the vendored 1.0 checker reports nothing against the shipped
    world."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-secrets-")
        from tests.util import load_plan
        cls.data = load_plan("medieval-glm-plan.json")
        for g in cls.data["buildings"]:
            if g["name"] == "Harrow Farmhouse":
                for r in g["rooms"]:
                    if r["name"] == "Larder":
                        r["name"] = "Priest Hole"
                        r["purpose"] = ("a hidden room behind the pantry "
                                        "panelling, cool storage for the "
                                        "grain")
                g["connections"] = [[c if c != "Larder" else "Priest Hole"
                                     for c in pair]
                                    for pair in g["connections"]]
                for f in g["furniture"]:
                    if f["room"] == "Larder":
                        f["room"] = "Priest Hole"
        cls.spec = worldgen.build_spec(
            worldgen.run(cls.data, seed=1, extensions=EXT), cls.data)
        cls.summary = api._layout_and_build(cls.data, seed=1, out_dir=cls.tmp,
                                            extra_exts=EXT)
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

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_the_priest_hole_ships_hidden_and_known_to_the_farmwife(self):
        entries = self.spec["nativeSecrets"]
        self.assertEqual(len(entries), 1)
        between = entries[0]["between"]
        hole = self._region("Harrow Farmhouse Priest Hole")
        other = self._region(between[1] if between[0] == hole["name"]
                             else between[0])
        doors = native.doors_between(self.scn, hole, other)
        self.assertTrue(doors)
        passages = self.scn["arpgMods"]["secretPassages"]["passages"]
        self.assertEqual(set(passages), {d["id"] for d in doors})
        for did in passages:
            self.assertEqual(passages[did], {"knownBy": ["Maren Harrow"]})
        for door in doors:
            self.assertTrue(native.is_secret(door))
            fx = next(fx for fx in door["statusEffects"]
                      if native.is_secret_fx(fx))
            self.assertTrue(fx["id"].startswith("se_"))
            self.assertEqual({k: v for k, v in fx.items() if k != "id"},
                             {"def": {"desc": "secret passage",
                                      "emoji": "🕳️", "type": "constant",
                                      "mechanics": [{"type": "concealed"}]},
                              "appliedAt": 28800})

    def test_no_ordinary_door_is_hidden(self):
        hidden = [e for e in self.scn["entities"] if native.is_secret(e)]
        self.assertTrue(hidden)
        between = self.spec["nativeSecrets"][0]["between"]
        doors = native.doors_between(self.scn, self._region(between[0]),
                                     self._region(between[1]))
        self.assertEqual(sorted(e["name"] for e in hidden),
                         sorted(d["name"] for d in doors))

    def test_the_summary_counts_the_secret_doors(self):
        self.assertEqual(self.summary["secret_doors"], 1)

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


class TestSecretReviewFixes(unittest.TestCase):
    """Claude's review: whole-word building kinds, and no hidden doorway
    strands a room behind it (not just the two rooms either side)."""

    def test_keep_is_a_whole_word(self):
        from worldgen.spec_writer import GRAND_BUILDING_WORDS as grand
        for text in ("castle", "the old keep", "ruined tower", "manor",
                     "a fortress"):
            self.assertTrue(grand.search(text), text)
        for text in ("innkeeper's house", "shopkeeper", "beekeeper cottage",
                     "keeper's lodge"):
            self.assertFalse(grand.search(text), text)

    def test_a_hidden_doorway_never_strands_a_room_behind_it(self):
        from worldgen import checks
        data = castle_plan()
        castle = data["buildings"][0] if "buildings" in data else None
        if castle is None:
            self.skipTest("castle_plan shape changed")
        castle["rooms"].append({"name": "Vault", "share": "small",
                                "purpose": "the lord's coin"})
        castle["connections"].append(["Study", "Vault"])
        for seed in range(1, 6):
            world = worldgen.run(data, seed=seed, extensions=EXT)
            spec = worldgen.build_spec(world, data)
            openings = checks.compute_openings(world)
            blocked, _doors = checks.walkability_grid(world, openings)
            jumps = checks.portal_jumps(world)
            starts = set(world.reserved)
            for road in world.roads:
                starts |= road.cells()
            rooms = [r for r in world.regions if r.is_room
                     and r.name.startswith("Ashfell Castle ")]
            open_seen = checks.flood(world, starts, blocked, jumps)
            reach = {r.name for r in rooms
                     if r.rect.interior().cells() & open_seen}
            for entry in spec["nativeSecrets"]:
                a, b = entry["between"]
                cells = (openings.get(a) or set()) & (openings.get(b) or set())
                seen = checks.flood(world, starts, blocked | set(cells), jumps)
                still = {r.name for r in rooms
                         if r.rect.interior().cells() & seen}
                self.assertEqual(still, reach,
                                 f"seed {seed}: hiding {a} / {b} strands "
                                 f"{sorted(reach - still)}")
