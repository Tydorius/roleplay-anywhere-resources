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
        # one bed per person: Maud and the player each get their own
        beds = [o for o in self.world.objects if o.template == "Bed"]
        self.assertEqual(len(beds), 2, "expected one added Bed per bedless resident")
        self.assertEqual({b.region for b in beds}, {"Fen Croft Bedroom"})

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
        self.assertEqual(bed["walkability"], 0.3,
                         "a fallback bed is lain on, not walked around")
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


TWO_BEDROOMS_PLAN = {
    "name": "Oxbridge",
    "worldBackground": "A hamlet by a bridge.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "sparse", "climate": "mild"},
    "mapSize": "small",
    "zones": [
        {"name": "Oxbridge", "kind": "village", "sizeClass": "medium",
         "description": "The hamlet.", "ground": "grass", "adjacentTo": [],
         "outdoor": [], "buildings": [
             {"name": "Fillery Cottage", "kind": "cottage", "sizeClass": "medium",
              "purpose": "the innkeep's family home", "residents": 3, "yard": None},
         ],
         "dressing": {"paths": "dirt", "props": [], "filler": []}},
        {"name": "Oxbridge Fields", "kind": "farmland", "sizeClass": "medium",
         "description": "The ploughlands.", "ground": "grass",
         "adjacentTo": ["Oxbridge"], "outdoor": [], "buildings": [
             {"name": "Field Barn", "kind": "barn", "sizeClass": "small",
              "purpose": "hay and carts", "yard": None},
         ],
         "dressing": {"paths": "dirt", "props": [], "filler": []}},
    ],
    "roads": [{"from": "Oxbridge", "to": "Oxbridge Fields", "kind": "dirt"}],
    "templates": CATALOGUE + [_tmpl("Hearth", 2, 1, ["fire", "cook"])],
    "buildings": [
        {"name": "Fillery Cottage", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "large",
                    "purpose": "cooking and eating"},
                   {"name": "Master Bedchamber", "share": "medium",
                    "purpose": "the parents' bedchamber"},
                   {"name": "Children's Bedchamber", "share": "medium",
                    "purpose": "the children's beds"}],
         "connections": [["Main Room", "Master Bedchamber"],
                         ["Main Room", "Children's Bedchamber"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [{"template": "Hearth", "room": "Main Room", "count": 1,
                        "hint": "wall:north"},
                       {"template": "Oak Table", "room": "Main Room",
                        "count": 1, "hint": "center"},
                       {"template": "Straw Bed", "room": "Master Bedchamber",
                        "count": 2, "hint": "wall:north"},
                       {"template": "Straw Bed", "room": "Children's Bedchamber",
                        "count": 2, "hint": "wall:north"}],
         "yard": None},
        {"name": "Field Barn", "wall": "wood", "ground": "dirt",
         "rooms": [{"name": "Barn Floor", "share": "large",
                    "purpose": "hay and carts"}],
         "connections": [], "entrance": {"room": "Barn Floor", "side": "south"},
         "furniture": [], "yard": None},
    ],
    "npcs": [
        {"name": "Joram Fillery", "gender": "male", "role": "innkeep",
         "home": "Fillery Cottage", "work": "Fillery Cottage",
         "description": "The innkeep.", "physicalDescription": "stout"},
        {"name": "Petra Fillery", "gender": "female", "role": "innkeep's wife",
         "home": "Fillery Cottage", "work": "Fillery Cottage",
         "description": "The innkeep's wife.", "physicalDescription": "tall"},
        {"name": "Tilly Fillery", "gender": "female", "role": "child",
         "home": "Fillery Cottage", "work": "Oxbridge",
         "description": "Their daughter.", "physicalDescription": "small"},
    ],
    "player": {"name": "Aldous Reed", "gender": "male", "role": "pedlar",
               "home": "Field Barn", "work": "Oxbridge",
               "description": "A pedlar.", "physicalDescription": "dusty"},
}


COUPLES_PLAN = {
    # the Fillery household again, with Joram and Petra a couple: the plan
    # says so, the furniture holds no double bed, the catalogue none either
    "name": "Oxbridge",
    "worldBackground": "A hamlet by a bridge.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "sparse", "climate": "mild"},
    "mapSize": "small",
    "zones": [
        {"name": "Oxbridge", "kind": "village", "sizeClass": "medium",
         "description": "The hamlet.", "ground": "grass", "adjacentTo": [],
         "outdoor": [], "buildings": [
             {"name": "Fillery Cottage", "kind": "cottage", "sizeClass": "medium",
              "purpose": "the innkeep's family home", "residents": 3,
              "couples": 1, "yard": None},
         ],
         "dressing": {"paths": "dirt", "props": [], "filler": []}},
    ],
    "roads": [],
    "templates": CATALOGUE + [_tmpl("Hearth", 2, 1, ["fire", "cook"])],
    "buildings": [
        {"name": "Fillery Cottage", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "large",
                    "purpose": "cooking and eating"},
                   {"name": "Master Bedchamber", "share": "medium",
                    "purpose": "the parents' bedchamber"},
                   {"name": "Children's Bedchamber", "share": "medium",
                    "purpose": "the children's beds"}],
         "connections": [["Main Room", "Master Bedchamber"],
                         ["Main Room", "Children's Bedchamber"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "furniture": [{"template": "Hearth", "room": "Main Room", "count": 1,
                        "hint": "wall:north"},
                       {"template": "Oak Table", "room": "Main Room",
                        "count": 1, "hint": "center"},
                       {"template": "Straw Bed", "room": "Master Bedchamber",
                        "count": 2, "hint": "wall:north"},
                       {"template": "Straw Bed", "room": "Children's Bedchamber",
                        "count": 2, "hint": "wall:north"}],
         "yard": None},
    ],
    "npcs": TWO_BEDROOMS_PLAN["npcs"],
    "player": TWO_BEDROOMS_PLAN["player"],
}


class TestCouples(unittest.TestCase):
    """A couple shares one double bed in a bedroom nobody else sleeps in,
    added when the home's furniture holds none."""

    def _sleep_locations(self, world):
        out = {}
        for c in world.characters:
            for blk in c.schedule:
                if blk["role"] == "sleep":
                    out[c.name] = blk["location"]
        return out

    def test_a_double_bed_is_added_and_the_couple_shares_its_room(self):
        import copy
        world = worldgen.run(copy.deepcopy(COUPLES_PLAN), seed=1)
        dbl = world.templates.get("Double bed")
        self.assertIsNotNone(dbl, "a fallback Double bed joins the catalogue")
        self.assertEqual(dbl.size, (2, 2))
        self.assertEqual(dbl.walkability, 0.3)
        placed = [o for o in world.objects if o.template == "Double bed"]
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0].region, "Fillery Cottage Master Bedchamber")
        locs = self._sleep_locations(world)
        self.assertEqual(locs["Joram Fillery"], "Fillery Cottage Master Bedchamber")
        self.assertEqual(locs["Petra Fillery"], "Fillery Cottage Master Bedchamber")
        self.assertEqual(locs["Tilly Fillery"], "Fillery Cottage Children's Bedchamber")
        for what, why in world.failures:
            self.assertNotIn("double bed", f"{what} {why}".lower(),
                             f"couple failure: {what}: {why}")

    def test_the_catalogues_own_double_is_used_when_it_exists(self):
        import copy
        data = copy.deepcopy(COUPLES_PLAN)
        data["templates"].append(_tmpl("Wide bed", 2, 2, ["bed"], forSleep=True))
        cottage = data["buildings"][0]
        cottage["furniture"] = [
            f for f in cottage["furniture"] if f["room"] != "Master Bedchamber"] + [
            {"template": "Wide bed", "room": "Master Bedchamber", "count": 1,
             "hint": "wall:north"}]
        world = worldgen.run(data, seed=1)
        self.assertNotIn("Double bed", world.templates,
                         "the catalogue's own double needs no fallback")
        wide = [o for o in world.objects if o.template == "Wide bed"]
        self.assertEqual({o.region for o in wide},
                         {"Fillery Cottage Master Bedchamber"})
        locs = self._sleep_locations(world)
        self.assertEqual(locs["Joram Fillery"], "Fillery Cottage Master Bedchamber")
        self.assertEqual(locs["Petra Fillery"], "Fillery Cottage Master Bedchamber")
        self.assertEqual(locs["Tilly Fillery"], "Fillery Cottage Children's Bedchamber")


GUEST_ROOM_PLAN = {
    "name": "Calxgate",
    "worldBackground": "A market cross and an inn.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Calxgate", "kind": "village", "sizeClass": "medium",
        "description": "The crossroads.", "ground": "grass", "adjacentTo": [],
        "outdoor": [], "buildings": [
            {"name": "The Green Ox", "kind": "inn", "sizeClass": "medium",
             "purpose": "ale and lodging", "residents": 3, "yard": None},
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [],
    "templates": CATALOGUE + [_tmpl("Hearth", 2, 1, ["fire", "cook"])],
    "buildings": [
        {"name": "The Green Ox", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Common Room", "share": "large",
                    "purpose": "ale and talk"},
                   {"name": "Keeper's Room", "share": "small",
                    "purpose": "the keeper's own bed"},
                   {"name": "Guest Chamber", "share": "medium",
                    "purpose": "lodging for paying guests"}],
         "connections": [["Common Room", "Keeper's Room"],
                         ["Common Room", "Guest Chamber"]],
         "entrance": {"room": "Common Room", "side": "south"},
         "furniture": [{"template": "Hearth", "room": "Common Room", "count": 1,
                        "hint": "wall:north"},
                       {"template": "Oak Table", "room": "Common Room",
                        "count": 2, "hint": "center"},
                       {"template": "Straw Bed", "room": "Keeper's Room",
                        "count": 1, "hint": "wall:north"},
                       {"template": "Straw Bed", "room": "Guest Chamber",
                        "count": 2, "hint": "row:north"}],
         "yard": None},
    ],
    "npcs": [
        {"name": "Osric Bell", "gender": "male", "role": "innkeep",
         "home": "The Green Ox", "work": "The Green Ox",
         "description": "The keeper.", "physicalDescription": "ruddy"},
        {"name": "Hild Bell", "gender": "female", "role": "innkeep's wife",
         "home": "The Green Ox", "work": "The Green Ox",
         "description": "The keeper's wife.", "physicalDescription": "broad"},
    ],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "The Green Ox", "work": "Calxgate",
               "description": "Passing through.", "physicalDescription": "cloaked"},
}


UPSTAIRS_PLAN = {
    "name": "Hilly Lea",
    "worldBackground": "A cot on a slope.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "sparse", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Hilly Lea", "kind": "hamlet", "sizeClass": "medium",
        "description": "The slope.", "ground": "grass", "adjacentTo": [],
        "outdoor": [], "buildings": [
            {"name": "Stairfoot House", "kind": "cottage", "sizeClass": "medium",
             "purpose": "a family home", "residents": 2, "storeys": 2,
             "yard": None},
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [],
    "templates": CATALOGUE + [_tmpl("Hearth", 2, 1, ["fire", "cook"])],
    "buildings": [
        {"name": "Stairfoot House", "wall": "wood", "ground": "wood",
         "rooms": [{"name": "Main Room", "share": "large",
                    "purpose": "cooking and eating"},
                   {"name": "Downstairs Chamber", "share": "medium",
                    "purpose": "the ground-floor bed"}],
         "connections": [["Main Room", "Downstairs Chamber"]],
         "entrance": {"room": "Main Room", "side": "south"},
         "stairs": {"room": "Main Room"},
         "upper": [{"storey": 2,
                    "rooms": [{"name": "Landing", "share": "medium",
                               "purpose": "the stair head"},
                              {"name": "Bedchamber", "share": "medium",
                               "purpose": "the loft bed"}],
                    "connections": [["Landing", "Bedchamber"]],
                    "furniture": [{"template": "Straw Bed", "room": "Bedchamber",
                                   "count": 1, "hint": "wall:north"}]}],
         "furniture": [{"template": "Hearth", "room": "Main Room", "count": 1,
                        "hint": "wall:north"},
                       {"template": "Oak Table", "room": "Main Room",
                        "count": 1, "hint": "center"},
                       {"template": "Straw Bed", "room": "Downstairs Chamber",
                        "count": 2, "hint": "wall:north"}],
         "yard": None},
    ],
    "npcs": [
        {"name": "Edda Marsh", "gender": "female", "role": "shepherd",
         "home": "Stairfoot House", "work": "Hilly Lea",
         "description": "A shepherd.", "physicalDescription": "windswept"},
    ],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "Stairfoot House", "work": "Hilly Lea",
               "description": "Passing through.", "physicalDescription": "cloaked"},
}


class TestSleepRoomAssignment(unittest.TestCase):
    """A sleep room for each person: bedded rooms fill to their bed capacity
    (not the whole household into the fullest one), in the sleep_room order."""

    def _sleep_locations(self, world):
        out = {}
        for c in world.characters:
            for blk in c.schedule:
                if blk["role"] == "sleep":
                    out[c.name] = blk["location"]
        return out

    def _sleepers_per_room(self, world):
        counts = {}
        for loc in self._sleep_locations(world).values():
            counts[loc] = counts.get(loc, 0) + 1
        return counts

    def _room_capacities(self, world):
        from worldgen.schedule import room_capacity
        out = {}
        for b in world.buildings:
            for r in b.layout.rooms:
                out[r.full_name] = room_capacity(world, r)
            for f in b.floors:
                for r in f.layout.rooms:
                    out.setdefault(r.full_name, 0)
                    out[r.full_name] += room_capacity(world, r)
        return out

    def test_two_bedrooms_split_the_household(self):
        world = worldgen.run(TWO_BEDROOMS_PLAN, seed=1)
        locs = self._sleep_locations(world)
        self.assertEqual(locs["Joram Fillery"], "Fillery Cottage Master Bedchamber")
        self.assertEqual(locs["Petra Fillery"], "Fillery Cottage Master Bedchamber")
        self.assertEqual(locs["Tilly Fillery"], "Fillery Cottage Children's Bedchamber")
        counts = self._sleepers_per_room(world)
        caps = self._room_capacities(world)
        for room, n in counts.items():
            self.assertLessEqual(n, caps.get(room, 0),
                                 f"{room} holds {n} sleepers of {caps.get(room, 0)} beds")

    def test_guest_room_used_only_after_private_rooms_fill(self):
        world = worldgen.run(GUEST_ROOM_PLAN, seed=1)
        locs = self._sleep_locations(world)
        self.assertEqual(locs["Osric Bell"], "The Green Ox Keeper's Room")
        self.assertEqual(locs["Hild Bell"], "The Green Ox Guest Chamber")
        self.assertEqual(locs["The Wanderer"], "The Green Ox Guest Chamber")

    def test_a_full_home_adds_a_bed_rather_than_borrowing_a_neighbours(self):
        import copy
        data = copy.deepcopy(TWO_BEDROOMS_PLAN)
        cottage = data["buildings"][0]
        cottage["furniture"] = [f for f in cottage["furniture"]
                                if f["room"] != "Children's Bedchamber"]
        data["zones"][0]["buildings"].append(
            {"name": "Smith's House", "kind": "cottage", "sizeClass": "small",
             "purpose": "the smith's home", "residents": 1, "yard": None})
        data["buildings"].append(
            {"name": "Smith's House", "wall": "wood", "ground": "wood",
             "rooms": [{"name": "Hearth Room", "share": "large",
                        "purpose": "living and sleeping"}],
             "connections": [], "entrance": {"room": "Hearth Room", "side": "south"},
             "furniture": [{"template": "Straw Bed", "room": "Hearth Room",
                            "count": 2, "hint": "wall:north"}],
             "yard": None})
        world = worldgen.run(data, seed=1)
        locs = self._sleep_locations(world)
        self.assertTrue(locs["Tilly Fillery"].startswith("Fillery Cottage "), locs)
        caps = self._room_capacities(world)
        for room, n in self._sleepers_per_room(world).items():
            self.assertLessEqual(n, caps.get(room, 0), room)

    def test_upper_storey_bedroom_preferred(self):
        world = worldgen.run(UPSTAIRS_PLAN, seed=1, extensions=("floors",))
        locs = self._sleep_locations(world)
        self.assertEqual(locs["Edda Marsh"], "Stairfoot House (upper floor) Bedchamber")
        self.assertEqual(locs["The Wanderer"], "Stairfoot House Downstairs Chamber")


if __name__ == "__main__":
    unittest.main()
