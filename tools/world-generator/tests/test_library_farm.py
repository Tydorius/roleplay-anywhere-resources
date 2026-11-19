"""rl-14a: the farming vocabulary — categories, roles, families and purposes —
and the 18 medieval farm objects: they load, the shipped library still checks
clean, every object reaches at least one purpose role, and the barn purpose
now names the barn family. rl-14b lands the farm families' own rooms: every
band of each family's table has a stored room, a barn holds the farm pieces
rather than a cellar of sacks, a hayloft is hay and never beds, and the barn
gap is closed on both furnishing paths (the assembler's stored rooms and the
old P3 layouts)."""
import json
import random
import unittest

import worldgen
from worldgen import fixed_rooms as FR
from worldgen import library as L
from worldgen import room_groups as RG
from worldgen.library_rooms import Templates, compile_room, pick_layout

# (id, category, size, back, wealth)
MEDIEVAL_FARM_OBJECTS = (
    ("pen.hurdle", "pen", [2, 1], "north", ["poor", "modest"]),
    ("pen.gate", "pen", [1, 1], None, ["poor", "modest"]),
    ("coop.henhouse", "coop", [2, 2], "north", ["poor", "modest"]),
    ("coop.hutch", "coop", [1, 1], "north", ["poor", "modest"]),
    ("coop.dovecote", "coop", [2, 2], None, ["wealthy", "elite"]),
    ("coop.skep", "coop", [1, 1], None, ["poor", "modest"]),
    ("feed.hay_rack", "feed", [2, 1], "north", ["poor", "modest"]),
    ("feed.rick", "feed", [3, 2], None, ["poor", "modest"]),
    ("feed.loft_stack", "feed", [2, 2], None, ["poor", "modest"]),
    ("dairy.churn", "dairy", [1, 1], None, ["poor", "modest"]),
    ("dairy.milk_cans", "dairy", [1, 1], None, ["modest", "wealthy", "elite"]),
    ("dairy.butter_worker", "dairy", [2, 1], "north", ["modest", "wealthy", "elite"]),
    ("granary.bin", "granary", [2, 1], "north", ["poor", "modest"]),
    ("farm_machine.plough", "farm_machine", [2, 1], None, ["poor", "modest"]),
    ("farm_machine.harrow", "farm_machine", [2, 1], None, ["poor", "modest"]),
    ("farm_machine.cart", "farm_machine", [3, 2], None, ["poor", "modest"]),
    ("farm_machine.wagon", "farm_machine", [4, 2], None, ["modest", "wealthy", "elite"]),
    ("muck.heap", "muck", [2, 2], None, ["poor", "modest"]),
)


class TestFarmVocabulary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        cls.errors, cls.warnings = L.check(cls.lib)

    def test_the_shipped_library_still_checks_clean(self):
        self.assertEqual(self.errors, [], "\n".join(self.errors[:40]))

    def test_the_new_categories_load(self):
        cats = self.lib.vocab["categories"]
        for c in ("pen", "coop", "dairy", "farm_machine", "granary", "muck"):
            with self.subTest(category=c):
                self.assertIn(c, cats)

    def test_the_new_roles_carry_access_rules(self):
        roles = self.lib.vocab["roles"]
        access = self.lib.vocab["roleAccess"]
        for role, rule in (("animal.pen", "none"), ("storage.hay", "front"),
                           ("dairy", "front"), ("machine", "none")):
            with self.subTest(role=role):
                self.assertIn(role, roles)
                self.assertEqual(access.get(role), rule)
        self.assertEqual(L.check_role_access(self.lib.vocab), [])

    def test_the_new_families_have_own_size_bands(self):
        families = self.lib.vocab["families"]
        bands = self.lib.vocab["familySizeBands"]
        for fam in ("barn", "dairy", "granary", "pigsty", "henhouse"):
            with self.subTest(family=fam):
                self.assertIn(fam, families)
                self.assertTrue(bands[fam]["bands"])
                self.assertNotIn(fam, self.lib.outdoor_families())

    def test_the_farming_purposes_load(self):
        purposes = self.lib.vocab["purposes"]
        for purpose, family in (
                ("barn", "barn"), ("threshing_floor", "barn"),
                ("cart_shed", "barn"), ("implement_shed", "barn"),
                ("machine_shed", "barn"), ("hayloft", "barn"),
                ("dairy", "dairy"), ("creamery", "dairy"),
                ("milk_house", "dairy"), ("milking_parlour", "dairy"),
                ("granary", "granary"), ("silo_room", "granary"),
                ("pigsty", "pigsty"), ("pig_pen", "pigsty"),
                ("henhouse", "henhouse"), ("chicken_house", "henhouse"),
                ("coop_room", "henhouse"),
                ("byre", "stable"), ("cowshed", "stable"), ("oxhouse", "stable"),
                ("paddock", "yard"), ("fold", "yard"), ("pen_room", "yard"),
                ("apiary", "garden"), ("orchard", "garden"),
                ("kitchen_garden", "garden"), ("vegetable_garden", "garden"),
                ("vat_farm", "greenhouse"), ("tack_room", "storage")):
            with self.subTest(purpose=purpose):
                self.assertEqual(purposes.get(purpose), family)
                self.assertIn(purpose, self.lib.purposes)

    def test_the_barn_purpose_maps_to_the_barn_family(self):
        self.assertEqual(self.lib.vocab["purposes"]["barn"], "barn")
        self.assertEqual(self.lib.family_of("barn"), "barn")


class TestFarmObjects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)

    def test_every_medieval_farm_object_loads(self):
        for oid, category, size, back, wealth in MEDIEVAL_FARM_OBJECTS:
            with self.subTest(object=oid):
                o = self.lib.objects[oid]
                self.assertEqual(o["category"], category)
                self.assertEqual(o["size"], size)
                self.assertEqual(o["back"], back)
                self.assertEqual(o["wealth"], wealth)
                self.assertEqual(o["bands"], ["medieval"])
                self.assertEqual(o["sources"], ["claude-authored"])
                self.assertTrue(o["text"]["physical"])

    def test_every_farm_object_binds_to_a_purpose_role(self):
        entries = set()
        for entry in self.lib.purposes.values():
            if not isinstance(entry, dict):
                continue      # the file's _readme
            for cs in ((entry or {}).get("roles") or {}).values():
                entries.update(cs)
        for oid, *_ in MEDIEVAL_FARM_OBJECTS:
            o = self.lib.objects[oid]
            with self.subTest(object=oid):
                self.assertTrue(any(L.binding_matches(c, o) for c in entries),
                                "no purpose role binding names it")

    def test_the_new_roles_pick_farm_objects(self):
        cases = (
            ("byre", "animal", "medieval", "poor", "feed.hay_rack"),
            ("stable", "animal", "medieval", "poor", "feed.hay_rack"),
            ("barn", "machine", "medieval", "modest", "farm_machine.plough"),
            ("barn", "storage.hay", "medieval", "poor", "feed.rick"),
            ("hayloft", "storage.hay", "medieval", "poor", "feed.loft_stack"),
            ("dairy", "dairy", "medieval", "poor", "dairy.churn"),
            ("creamery", "dairy", "medieval", "modest", "dairy.butter_worker"),
            ("granary", "storage.bulk", "medieval", "poor", "granary.bin"),
            ("paddock", "animal.pen", "medieval", "poor", "pen.hurdle"),
            ("henhouse", "animal", "medieval", "poor", "coop.henhouse"),
            ("apiary", "animal", "medieval", "poor", "coop.skep"),
            ("pigsty", "waste", "medieval", "poor", "muck.heap"),
            ("byre", "waste", "medieval", "poor", "muck.heap"),
        )
        for purpose, role, band, tier, want in cases:
            with self.subTest(purpose=purpose, role=role, want=want):
                ids = {o["id"] for o in L.candidates(self.lib, purpose, role,
                                                     None, band, tier)}
                self.assertIn(want, ids)

    def test_no_coverage_gap_comes_from_the_farm_bindings(self):
        hard = [g for g in L.coverage(self.lib) if not g[7]]
        self.assertEqual(hard, [], "\n".join(map(str, hard[:20])))


class TestFarmGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        cls.data = RG.load()

    def test_the_byre_row_and_pen_fold_groups_load(self):
        for gid, family in (("byre.stall.row", "stable"), ("pen.fold", "yard")):
            with self.subTest(group=gid):
                g = self.data["groups"][gid]
                self.assertEqual(g["family"], family)
                self.assertTrue(g["pieces"])
        self.assertEqual(RG.check(self.data, self.lib), [])


FARM_FAMILIES = ("barn", "dairy", "granary", "pigsty", "henhouse")
SLEEP_ROLES = ("sleep", "sleep.couple", "sleep.child", "med.bed", "cell.bed")


def farm_names(lib):
    """The display names the medieval farm objects fill to — their base
    names, which a material prefix may front ('Ash plough')."""
    names = set()
    for oid, *_ in MEDIEVAL_FARM_OBJECTS:
        names.update(lib.objects[oid]["names"].values())
    return names


def is_farm_template(name, names):
    return name in names or any(name.endswith(" " + n) for n in names)


def roles_of(room):
    return {p["role"] for p in room["pieces"]}


class TestFarmStoredRooms(unittest.TestCase):
    """rl-14b: the farm families' stored rooms — every band of the family's
    own table is furnished, a barn holds the farm pieces (machine, hay and
    animal) rather than a cellar of sacks, and a hayloft room is hay and
    never beds."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        by_family = {}
        for r in FR.load():
            if not r.get("retired"):
                by_family.setdefault(r["family"], []).append(r)
        cls.rooms = by_family

    def test_every_family_has_rooms_in_every_band_it_names(self):
        for fam in FARM_FAMILIES:
            have = {r["sizeBand"] for r in self.rooms.get(fam, ())}
            for band in [b["name"] for b in FR.family_bands(fam)]:
                with self.subTest(family=fam, band=band):
                    self.assertIn(band, have)

    def test_a_barn_room_holds_the_farm_pieces(self):
        barns = self.rooms["barn"]
        self.assertTrue(barns)
        # the barn is machine, hay and livestock, not a sacks-only cellar
        self.assertTrue(any({"machine", "storage.hay", "animal"} <= roles_of(r)
                            for r in barns),
                        [sorted(roles_of(r)) for r in barns])
        for r in barns:
            with self.subTest(room=r["id"]):
                self.assertFalse(roles_of(r) <= {"storage.bulk"})

    def test_the_hayloft_recipe_rooms_are_hay_and_never_beds(self):
        lofts = [r for r in self.rooms["barn"]
                 if r["recipe"] == "barn.hayloft.a"]
        self.assertTrue(lofts, "no hayloft room was stored")
        for r in lofts:
            with self.subTest(room=r["id"]):
                self.assertIn("storage.hay", roles_of(r))
                self.assertNotIn("machine", roles_of(r))
        for fam in FARM_FAMILIES:
            for r in self.rooms.get(fam, ()):
                with self.subTest(family=fam, room=r["id"]):
                    self.assertFalse(roles_of(r) & set(SLEEP_ROLES))


FARMSTEAD_PLAN = {
    "name": "Millbrook",
    "worldBackground": "A mill hamlet among the fields.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Millbrook", "kind": "village", "sizeClass": "small",
        "description": "The mill and its yard.", "ground": "grass",
        "adjacentTo": ["The Fields"], "outdoor": [], "buildings": [
            {"name": "Millbrook Farm", "kind": "farmhouse",
             "sizeClass": "medium", "purpose": "the home farm",
             "residents": 1, "yard": None}],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "The Fields", "kind": "farmland", "sizeClass": "large",
        "description": "Plough and meadow.", "ground": "grass",
        "adjacentTo": ["Millbrook"], "outdoor": [], "buildings": [],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [{"from": "Millbrook", "to": "The Fields", "kind": "dirt"}],
    "templates": [],
    "buildings": [
        {"name": "Millbrook Farm", "wall": "wood", "ground": "wood",
         "residents": 1, "couples": 0, "wealth": "modest", "condition": "kept",
         "rooms": [
             {"name": "Barn", "share": "large", "use": "barn",
              "purpose": "threshing floor and rick"},
             {"name": "Byre", "share": "medium", "use": "byre",
              "purpose": "the cows at their stalls"},
             {"name": "Dairy", "share": "small", "use": "dairy",
              "purpose": "milk and butter"}],
         "connections": [["Barn", "Byre"], ["Barn", "Dairy"]],
         "entrance": {"room": "Barn", "side": "south"},
         "furniture": [], "yard": None},
    ],
    "npcs": [],
    "player": {"name": "The Miller", "gender": "male", "role": "farmer",
               "home": "Millbrook Farm", "work": "The Fields",
               "description": "Working the farm.",
               "physicalDescription": "sunburnt"},
}


class TestTheFarmsteadAssembles(unittest.TestCase):
    """The barn gap closed on the assembler path: a medieval farmstead's
    barn (stored rooms), byre (the stable family's recipes, composed live)
    and dairy (stored rooms) all furnish without a fallback."""

    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(json.loads(json.dumps(FARMSTEAD_PLAN)),
                                 seed=7, room_assembler=True)
        cls.farm = farm_names(L.load(L.LIB_DIR))

    def test_the_farmstead_assembles(self):
        bl = next((b.layout for b in self.world.buildings
                   if b.layout.design.name == "Millbrook Farm"), None)
        self.assertIsNotNone(bl, "no building in the world")
        self.assertTrue(getattr(bl, "assembled", False),
                        self.world.fallbacks)
        self.assertFalse([f for f in self.world.fallbacks
                          if f[0] == "building Millbrook Farm"],
                         self.world.fallbacks)
        self.assertEqual(self.world.metrics["reachability"], 1.0,
                         self.world.metrics.get("objects"))
        names = {r.base_name for r in bl.rooms}
        self.assertTrue({"Barn", "Byre", "Dairy"} <= names, sorted(names))

    def test_each_farm_room_holds_farm_pieces_and_no_beds(self):
        for room in ("Barn", "Byre", "Dairy"):
            placed = [self.world.templates[o.template]
                      for o in self.world.objects if o.region.endswith(room)]
            with self.subTest(room=room):
                self.assertTrue(placed, "the room shipped empty")
                self.assertTrue(any(is_farm_template(t.name, self.farm)
                                    for t in placed),
                                [t.name for t in placed])
                if room != "Byre":
                    # the byre is the stable family's room and keeps that
                    # family's own bindings; never-beds is the barn's rule
                    self.assertFalse([t.name for t in placed if t.for_sleep],
                                     "a bed in a farm building")


class TestTheBarnOnTheOldLayoutPath(unittest.TestCase):
    """The barn gap closed on the old layout path too: pick_layout finds the
    barn family's own layouts, and compile_room furnishes one under the barn
    purpose with no gaps and the farm templates placed."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        cls.farm = farm_names(cls.lib)

    def test_pick_layout_finds_a_barn_layout(self):
        lay = pick_layout(self.lib, "barn", (8, 8), random.Random(1))
        self.assertIsNotNone(lay, "no barn layout fits an 8x8 interior")
        self.assertEqual(lay["family"], "barn")

    def test_the_old_path_furnishes_a_barn(self):
        reg = Templates(self.lib, 1)
        room = compile_room(self.lib, reg, "barn", (8, 8), "medieval", "modest",
                            "kept", random.Random(3))
        self.assertIsNotNone(room.layout_id)
        self.assertTrue(room.layout_id.startswith("barn."), room.layout_id)
        self.assertEqual(room.gaps, [])
        names = {f.template for f in room.furniture}
        self.assertTrue(any(is_farm_template(n, self.farm) for n in names),
                        names)


if __name__ == "__main__":
    unittest.main()
