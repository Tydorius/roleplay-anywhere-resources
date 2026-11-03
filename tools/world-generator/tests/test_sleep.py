"""Everyone sleeps in a bed: sleep templates reach the spec as forSleep, and
each person's sleep block names a room that holds a sleep object — their
home's when it has one, else the nearest bedded building of the same
household, else a bed added to the home's most private room. Work places
like a smithy or a chapel are never slept in."""
import unittest

import worldgen
from worldgen import phases
from worldgen.model import ObjectTemplate, is_sleep_name


def _tmpl(name, w, h, tags, **extra):
    d = {"name": name, "size": [w, h], "walkability": 0.0, "tags": tags,
         "description": f"A {name.lower()}.",
         "physicalDescription": f"a {name.lower()}",
         "rule": "place anywhere free"}
    d.update(extra)
    return d


CATALOGUE = [
    _tmpl("Straw Bed", 1, 2, ["rest"]),      # sleep by name, no bed tag
    _tmpl("Anvil", 1, 1, ["work", "metal"]),
    _tmpl("Stone Altar", 2, 1, ["prayer", "landmark"]),
    _tmpl("Chapel Pew", 2, 1, ["seat", "prayer"]),
    _tmpl("Oak Table", 2, 1, ["table", "eat"]),
    _tmpl("Iron Chest", 1, 1, ["storage"]),
]

WORKPLACE_HOMES_PLAN = {
    "name": "Thistledown",
    "worldBackground": "A hamlet around a ford.",
    "setting": {"era": "medieval", "technology": "iron and water",
                "density": "sparse", "climate": "wet"},
    "mapSize": "small",
    "zones": [{
        "name": "Thistledown", "kind": "village", "sizeClass": "medium",
        "description": "The hamlet green.", "ground": "grass", "adjacentTo": [],
        "outdoor": [], "buildings": [
            {"name": "Thistledown Smithy", "kind": "smithy", "sizeClass": "small",
             "purpose": "shoeing horses", "yard": None},
            {"name": "St. Brannoc's Chapel", "kind": "chapel", "sizeClass": "small",
             "purpose": "prayers for the harvest", "yard": None},
            {"name": "Smith's Cottage", "kind": "cottage", "sizeClass": "small",
             "purpose": "the smith's home", "yard": None},
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [],
    "templates": CATALOGUE,
    "buildings": [
        {"name": "Thistledown Smithy", "wall": "stone", "ground": "stone",
         "rooms": [{"name": "Smithy Floor", "share": "large",
                    "purpose": "the forge"}],
         "connections": [], "entrance": {"room": "Smithy Floor", "side": "south"},
         "furniture": [{"template": "Anvil", "room": "Smithy Floor", "count": 1,
                        "hint": "center"}],
         "yard": None},
        {"name": "St. Brannoc's Chapel", "wall": "stone", "ground": "stone",
         "rooms": [{"name": "Nave", "share": "large",
                    "purpose": "the Sunday service"}],
         "connections": [], "entrance": {"room": "Nave", "side": "south"},
         "furniture": [{"template": "Stone Altar", "room": "Nave", "count": 1,
                        "hint": "wall:north"},
                       {"template": "Chapel Pew", "room": "Nave", "count": 2,
                        "hint": "row:south"}],
         "yard": None},
        {"name": "Smith's Cottage", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "medium",
                    "purpose": "cooking and eating"},
                   {"name": "Bedroom", "share": "small",
                    "purpose": "the smith's bedchamber"}],
         "connections": [["Main Room", "Bedroom"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [{"template": "Oak Table", "room": "Main Room", "count": 1,
                        "hint": "center"},
                       {"template": "Straw Bed", "room": "Bedroom", "count": 1,
                        "hint": "wall:north"}],
         "yard": None},
    ],
    "npcs": [
        {"name": "Hamond Gower", "gender": "male", "role": "smith",
         "home": "Thistledown Smithy", "work": "Thistledown Smithy",
         "description": "The village smith.", "physicalDescription": "burly"},
        {"name": "Father Odo", "gender": "male", "role": "priest",
         "home": "St. Brannoc's Chapel", "work": "St. Brannoc's Chapel",
         "description": "The village priest.", "physicalDescription": "thin"},
    ],
    "player": {"name": "Aldous Reed", "gender": "male", "role": "pedlar",
               "home": "Smith's Cottage", "work": "Thistledown",
               "description": "A pedlar.", "physicalDescription": "dusty"},
}


BEDLESS_HOME_PLAN = {
    "name": "Lone Croft",
    "worldBackground": "One croft in the fens.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "sparse", "climate": "cold"},
    "mapSize": "small",
    "zones": [{
        "name": "The Croft", "kind": "farm", "sizeClass": "medium",
        "description": "A lone stead.", "ground": "grass", "adjacentTo": [],
        "outdoor": [], "buildings": [
            {"name": "Fen Croft", "kind": "house", "sizeClass": "small",
             "purpose": "a farmer's home", "yard": None},
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [],
    "templates": [
        _tmpl("Hearth", 2, 1, ["fire", "cook"]),
        _tmpl("Trestle Table", 2, 1, ["table", "eat"]),
        _tmpl("Stool", 1, 1, ["seat"]),
    ],
    "buildings": [
        {"name": "Fen Croft", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "large",
                    "purpose": "cooking and eating"},
                   {"name": "Bedroom", "share": "small",
                    "purpose": "sleeping"}],
         "connections": [["Main Room", "Bedroom"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [{"template": "Hearth", "room": "Main Room", "count": 1,
                        "hint": "wall:north"},
                       {"template": "Trestle Table", "room": "Main Room",
                        "count": 1, "hint": "center"},
                       {"template": "Stool", "room": "Main Room", "count": 2,
                        "hint": "around:Trestle Table"}],
         "yard": None},
    ],
    "npcs": [
        {"name": "Maud Fenner", "gender": "female", "role": "farmer",
         "home": "Fen Croft", "work": "The Croft",
         "description": "A fen farmer.", "physicalDescription": "weathered"},
    ],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "Fen Croft", "work": "The Croft",
               "description": "Passing through.", "physicalDescription": "cloaked"},
}


class TestSleepNames(unittest.TestCase):
    def test_name_and_tags_decide_for_sleep(self):
        cases = [
            ("Straw Bed", ["rest"], True),
            ("Bunk", [], True),
            ("Wicker Cot", ["seat"], True),
            ("Ship's Hammock", [], True),
            ("Pallet", [], True),
            ("Oak Table", ["table"], False),
            ("Altar", ["prayer"], False),
        ]
        for name, tags, want in cases:
            t = ObjectTemplate(name=name, tags=tags)
            self.assertEqual(t.for_sleep, want, f"{name} for_sleep should be {want}")

    def test_explicit_flag_wins(self):
        t = ObjectTemplate(name="Bed", tags=["bed"], extras={"forSleep": False})
        self.assertFalse(t.for_sleep)
        t2 = ObjectTemplate(name="Sofa", extras={"forSleep": True})
        self.assertTrue(t2.for_sleep)

    def test_is_sleep_name(self):
        self.assertTrue(is_sleep_name("Pallet"))
        self.assertFalse(is_sleep_name("Well"))
        self.assertTrue(is_sleep_name("Crate", ["bed"]))
        self.assertFalse(is_sleep_name("Crate", ["storage"]))


class TestP2Contract(unittest.TestCase):
    def test_check_p2_accepts_bool_forsleep(self):
        d = {"templates": [dict(t, forSleep=True) for t in CATALOGUE]}
        self.assertEqual(phases.check_p2(d), [])

    def test_check_p2_rejects_non_bool(self):
        d = {"templates": [dict(CATALOGUE[0], forSleep="yes")]}
        self.assertTrue(any("forSleep" in e for e in phases.check_p2(d)))

    def test_sanitize_defaults_forsleep_from_name(self):
        d = {"templates": [dict(t) for t in CATALOGUE]}   # no forSleep anywhere
        log = []
        phases.sanitize_p2(d, log)
        flags = {t["name"]: t["forSleep"] for t in d["templates"]}
        self.assertTrue(flags["Straw Bed"])
        self.assertFalse(flags["Anvil"])
        self.assertEqual(log, [])   # a missing flag defaults quietly


class TestWorkplaceHomes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = WORKPLACE_HOMES_PLAN
        cls.world = worldgen.run(cls.data, seed=3)

    def _sleep_locations(self):
        out = {}
        for c in self.world.characters:
            for blk in c.schedule:
                if blk["role"] == "sleep":
                    out[c.name] = blk["location"]
        return out

    def test_everyone_sleeps_in_a_room_with_a_bed(self):
        bedded = set()
        for o in self.world.objects:
            if self.world.templates[o.template].for_sleep:
                bedded.add(o.region)
        for name, loc in self._sleep_locations().items():
            self.assertIn(loc, bedded,
                          f"{name} sleeps in {loc} which has no forSleep object")

    def test_nobody_sleeps_at_a_work_place(self):
        work_rooms = {f"Thistledown Smithy {r}" for r in ("Smithy Floor",)}
        work_rooms |= {f"St. Brannoc's Chapel {r}" for r in ("Nave",)}
        for name, loc in self._sleep_locations().items():
            self.assertNotIn(loc, work_rooms, f"{name} sleeps at work: {loc}")

    def test_household_bed_is_used(self):
        # the smith and the priest both borrow the cottage's bed
        self.assertEqual(self._sleep_locations()["Hamond Gower"],
                         "Smith's Cottage Bedroom")
        self.assertEqual(self._sleep_locations()["Father Odo"],
                         "Smith's Cottage Bedroom")

    def test_no_bed_failures_recorded(self):
        for what, why in self.world.failures:
            self.assertNotIn("bed", what.lower() + why.lower(),
                             f"bed failure: {what}: {why}")


class TestBedlessHome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = BEDLESS_HOME_PLAN
        cls.world = worldgen.run(cls.data, seed=1)

    def test_generic_bed_added_to_the_private_room(self):
        beds = [o for o in self.world.objects if o.template == "Bed"]
        self.assertEqual(len(beds), 1, "expected exactly one added Bed")
        self.assertEqual(beds[0].region, "Fen Croft Bedroom")

    def test_sleep_location_is_the_bedded_room(self):
        for c in self.world.characters:
            for blk in c.schedule:
                if blk["role"] == "sleep":
                    self.assertEqual(blk["location"], "Fen Croft Bedroom")

    def test_added_bed_reaches_the_spec(self):
        spec = worldgen.build_spec(self.world, self.data)
        bed = next(t for t in spec["objectTemplates"] if t["name"] == "Bed")
        self.assertEqual(bed["size"], [1, 2])
        self.assertTrue(bed["forSleep"])
        self.assertTrue(bed["placements"])

    def test_bed_does_not_block_the_room(self):
        room = next(r for r in self.world.regions
                    if r.name == "Fen Croft Bedroom")
        bed = next(o for o in self.world.objects if o.template == "Bed")
        w, h = self.world.templates["Bed"].size
        cells = {(x, y) for x in range(bed.pos[0], bed.pos[0] + w)
                 for y in range(bed.pos[1], bed.pos[1] + h)}
        self.assertTrue(cells <= room.rect.interior().cells())
        for (t, pos) in next(b for b in self.world.buildings
                             if b.layout.design.name == "Fen Croft").layout \
                .room_by_base("Bedroom").furniture.placements:
            if t == "Bed":
                continue
            tw, th = self.world.templates[t].size
            other = {(x, y) for x in range(pos[0], pos[0] + tw)
                     for y in range(pos[1], pos[1] + th)}
            self.assertFalse(cells & other, "Bed overlaps existing furniture")


if __name__ == "__main__":
    unittest.main()
