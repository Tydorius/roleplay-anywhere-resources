"""rl-14a: the farming vocabulary — categories, roles, families and purposes —
and the 18 medieval farm objects: they load, the shipped library still checks
clean, every object reaches at least one purpose role, and the barn purpose
now names the barn family. rl-14b lands the farm families' own rooms: every
band of each family's table has a stored room, a barn holds the farm pieces
rather than a cellar of sacks, a hayloft is hay and never beds, and the barn
gap is closed on both furnishing paths (the assembler's stored rooms and the
old P3 layouts). rl-14c adds the industrial and modern equipment: every new
object loads and binds, the horse-drawn medieval set is reused by the
industrial band (an industrial look where the material changes), the
machine shed and milking parlour recipes have stored rooms whose machine
slots only the new equipment fills, and no medieval room changed. rl-14d
adds the scifi set: every new object loads and binds to a farm purpose
role in the scifi band, the vat farm and gene bank recipes have stored
rooms, and no room that shipped before rl-14d stands changed. rl-14f adds
the farmsteads of every era: five new wings, three buildings and three
suites load and check clean, the barn wings stand two storeys with a
hayloft upstairs (design 8.1g), the farmhouse wing's Dairy is the dairy
purpose, and the flat suites match planner kinds in their own bands. rl-14g
replaces the 3x2 parlour stalls object with one 1x2 milking stall set in
rows by a furniture group: the old id is gone, the sprite index points at
the new id, the regenerated dairy rooms hold rows of two and three stalls
each reachable from its rear, and the medieval dairy builds without one."""
import json
import random
import unittest

import worldgen
from worldgen import fixed_rooms as FR
from worldgen import library as L
from worldgen import room_groups as RG
from worldgen.library_rooms import Templates, compile_room, pick_layout

# the medieval set the industrial band reuses (everything but the dovecote
# and the straw skep the frame beehive replaces); churn, plough, harrow and
# the hurdle also change material class for their industrial look
INDUSTRIAL_REUSE = {
    "pen.hurdle": {"wattle": "wood"},
    "pen.gate": {},
    "coop.henhouse": {},
    "coop.hutch": {},
    "feed.hay_rack": {},
    "feed.rick": {},
    "feed.loft_stack": {},
    "dairy.churn": {"churn": "metal"},
    "dairy.milk_cans": {},
    "dairy.butter_worker": {},
    "granary.bin": {},
    "farm_machine.plough": {"beam": "metal"},
    "farm_machine.harrow": {"frame": "metal"},
    "farm_machine.cart": {},
    "farm_machine.wagon": {},
    "muck.heap": {},
}

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
                # the industrial band reuses all but the dovecote and skep
                self.assertEqual(
                    o["bands"],
                    ["medieval", "industrial"] if oid in INDUSTRIAL_REUSE
                    else ["medieval"])
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
    # case-insensitive: an object whose contents are fixed words (hay, straw)
    # has no material prefix, so its template is just the capitalised noun
    low = name.lower()
    return any(low == n.lower() or low.endswith(" " + n.lower()) for n in names)


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
                # no farm family's room ever ships a bed: the residents of
                # an all-farm building sleep in the farmhouse, noted
                self.assertFalse([t.name for t in placed if t.for_sleep],
                                 "a bed in a farm building")

    def test_the_farm_buildings_residents_sleep_in_the_farmhouse(self):
        # the plan's only building is all farm families, so its residents
        # sleep elsewhere: the note says so and nothing in the world sleeps
        self.assertFalse([o for o in self.world.objects
                          if self.world.templates[o.template].for_sleep],
                         "a bed in an all-farm world")
        self.assertIn(("bed for The Miller",
                       "residents of Millbrook Farm sleep elsewhere: "
                       "farm building"),
                      self.world.notes, self.world.notes)

    def test_the_medieval_dairy_builds_without_a_milking_stall(self):
        """rl-14g: the stall is a modern object, so a band without it keeps
        its dairy rooms — the medieval farmstead's Dairy still furnishes and
        no stall template enters the world."""
        placed = [self.world.templates[o.template]
                  for o in self.world.objects if o.region.endswith("Dairy")]
        self.assertTrue(placed, "the Dairy shipped empty")
        self.assertFalse([t.name for t in placed
                          if "milking stall" in t.name.lower()],
                         [t.name for t in placed])


class TestTheIndustrialFarmsteadAssembles(unittest.TestCase):
    """rl-15 on the industrial band: the same all-farm farmstead — its barn,
    byre and dairy kitted with the industrial set — ships no bed either, the
    residents noted as sleeping elsewhere."""

    @classmethod
    def setUpClass(cls):
        plan = json.loads(json.dumps(FARMSTEAD_PLAN))
        plan["setting"]["band"] = "industrial"
        cls.world = worldgen.run(plan, seed=7, room_assembler=True)
        cls.farm = farm_names(L.load(L.LIB_DIR))

    def test_no_farm_room_ships_a_bed(self):
        for room in ("Barn", "Byre", "Dairy"):
            placed = [self.world.templates[o.template]
                      for o in self.world.objects if o.region.endswith(room)]
            with self.subTest(room=room):
                self.assertTrue(placed, "the room shipped empty")
                self.assertTrue(any(is_farm_template(t.name, self.farm)
                                    for t in placed),
                                [t.name for t in placed])
                self.assertFalse([t.name for t in placed if t.for_sleep],
                                 "a bed in a farm building")

    def test_the_residents_still_sleep_elsewhere(self):
        self.assertIn(("bed for The Miller",
                       "residents of Millbrook Farm sleep elsewhere: "
                       "farm building"),
                      self.world.notes, self.world.notes)


# the P1 stand-in the longhouse wing is built from: a longhouse of mixed
# house and farm rooms, its residents on the zone's building entry
LONGHOUSE_WING_PLAN = {
    "name": "Thornfield",
    "worldBackground": "A longhouse under the hill, cows in the byre end.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Thornfield", "kind": "village", "sizeClass": "small",
        "description": "The green.", "ground": "grass",
        "adjacentTo": ["The Ford"], "outdoor": [], "buildings": [
            {"name": "Thornfield Longhouse", "kind": "longhouse",
             "sizeClass": "medium", "purpose": "the house and its byre",
             "residents": 4, "yard": None}],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "The Ford", "kind": "farmland", "sizeClass": "medium",
        "description": "Meadows.", "ground": "grass",
        "adjacentTo": ["Thornfield"], "outdoor": [], "buildings": [],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [{"from": "Thornfield", "to": "The Ford", "kind": "dirt"}],
    "templates": [],
    "buildings": [
        {"name": "Thornfield Longhouse", "wall": "wood", "ground": "wood",
         "residents": 4, "couples": 1, "wealth": "modest", "condition": "kept",
         "rooms": [
             {"name": "Hall", "share": "medium", "use": "living_room",
              "purpose": "hearth and table"},
             {"name": "Kitchen", "share": "small", "use": "kitchen",
              "purpose": "cooking"},
             {"name": "Bedchamber", "share": "small", "use": "master_bedroom",
              "purpose": "the bed"},
             {"name": "Byre", "share": "medium", "use": "byre",
              "purpose": "the cows"},
             {"name": "Barn", "share": "small", "use": "barn",
              "purpose": "stores"},
             {"name": "Hayloft", "share": "small", "use": "hayloft",
              "purpose": "hay"}],
         "connections": [["Hall", "Kitchen"], ["Hall", "Bedchamber"],
                         ["Hall", "Byre"], ["Byre", "Barn"],
                         ["Byre", "Hayloft"]],
         "entrance": {"room": "Hall", "side": "south"},
         "furniture": [], "yard": None},
    ],
    "npcs": [],
    "player": {"name": "The Husbandman", "gender": "male", "role": "farmer",
               "home": "Thornfield Longhouse", "work": "The Ford",
               "description": "Working the fields.",
               "physicalDescription": "weathered"},
}


class TestTheLonghouseKeepsItsBedsInTheHouseRooms(unittest.TestCase):
    """rl-15: the longhouse wing mixes house rooms with farm rooms, and its
    beds stay where its families allow them — the bedchamber's own, never the
    byre's or the barn's."""

    def test_the_wing_design_sleeps_in_the_bedchamber_only(self):
        from worldgen import assembler, library_plan, model
        lib = L.load(L.LIB_DIR)
        plan = json.loads(json.dumps(LONGHOUSE_WING_PLAN))
        parsed = model.parse_plan(plan)
        b = next(d for d in parsed.zones[0].buildings
                 if d.name == "Thornfield Longhouse")
        ctx = assembler.activate(parsed, plan, "s", {})
        self.addCleanup(assembler.deactivate)
        design = library_plan.wing_design(
            lib, lib.wings["farm.longhouse"], "Thornfield Longhouse", b,
            "medieval", 2, "longhouse")
        bl = assembler.build(design, (0, 0))
        self.assertIsNotNone(bl, ctx.fallbacks)
        rooms = list(bl.rooms)
        for i in range(len(bl.upper_asm or [])):
            rooms.extend(assembler.upper_layout(bl, i, bl.rect).rooms)
        beds = sorted(r.base_name for r in rooms
                      if any(ctx.world_templates[t].for_sleep
                             for (t, _p) in r.furniture.placements))
        self.assertEqual(beds, ["Bedchamber"], beds)
        for name in ("Byre", "Barn"):
            room = next((r for r in rooms if r.base_name == name), None)
            self.assertIsNotNone(room, f"no {name} in the longhouse")
            self.assertFalse(
                [t for (t, _p) in room.furniture.placements
                 if ctx.world_templates[t].for_sleep],
                f"a bed in the {name}")

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


# (id, category, size, back, wealth)
INDUSTRIAL_FARM_OBJECTS = (
    ("dairy.separator", "dairy", [1, 1], None, ["modest", "wealthy", "elite"]),
    ("farm_machine.seed_drill", "farm_machine", [3, 2], None,
     ["modest", "wealthy", "elite"]),
    ("farm_machine.reaper", "farm_machine", [3, 2], None,
     ["modest", "wealthy", "elite"]),
    ("farm_machine.thresher", "farm_machine", [2, 2], None,
     ["modest", "wealthy", "elite"]),
    ("farm_machine.traction_engine", "farm_machine", [3, 3], None,
     ["wealthy", "elite"]),
    ("coop.beehive", "coop", [1, 1], None, ["modest", "wealthy", "elite"]),
    ("farm_machine.hay_rake", "farm_machine", [2, 1], None, ["poor", "modest"]),
    ("farm_machine.muck_spreader", "farm_machine", [2, 2], None,
     ["poor", "modest"]),
    ("utility.wind_pump", "utility", [2, 2], None, ["poor", "modest"]),
)

MODERN_FARM_OBJECTS = (
    ("farm_machine.tractor", "farm_machine", [2, 3], None, ["poor", "modest"]),
    ("farm_machine.combine", "farm_machine", [4, 3], None, ["wealthy", "elite"]),
    ("dairy.milking_stall", "milking_stall", [1, 2], "north", ["poor", "modest"]),
    ("dairy.milk_tank", "dairy", [2, 1], "north", ["poor", "modest"]),
    ("granary.silo", "granary", [2, 2], None, ["poor", "modest"]),
    ("feed.tube_feeder", "feed", [1, 1], None, ["poor", "modest"]),
    ("coop.perch_rack", "coop", [2, 1], "north", ["poor", "modest"]),
    ("coop.nest_box", "coop", [1, 1], "north", ["poor", "modest"]),
    ("farm_machine.baler", "farm_machine", [2, 2], None, ["poor", "modest"]),
    ("farm_machine.drill_modern", "farm_machine", [3, 2], None,
     ["poor", "modest"]),
    ("pen.panel", "pen", [2, 1], "north", ["poor", "modest"]),
    ("granary.hopper_bin", "granary", [2, 2], None, ["poor", "modest"]),
)

# each farm category's own purpose and role (the wind pump serves any yard
# through the wildcard purpose's utility role)
FARM_PURPOSE_ROLE = {
    "dairy": ("dairy", "dairy"),
    "milking_stall": ("milking_parlour", "milking.stall"),
    "farm_machine": ("barn", "machine"),
    "coop": ("byre", "animal"),
    "feed": ("byre", "animal"),
    "pen": ("paddock", "animal.pen"),
    "granary": ("granary", "storage.bulk"),
    "utility": ("*", "utility"),
}


class TestIndustrialModernFarmObjects(unittest.TestCase):
    """rl-14c: the 9 industrial and 12 modern objects load with their band,
    wealth and top-down text, every one binds to a farm purpose role in its
    band, and the medieval set the industrial band reuses carries its
    industrial look where the material class changes."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)

    def test_every_new_farm_object_loads(self):
        for table, band in ((INDUSTRIAL_FARM_OBJECTS, "industrial"),
                            (MODERN_FARM_OBJECTS, "modern")):
            for oid, category, size, back, wealth in table:
                with self.subTest(object=oid):
                    o = self.lib.objects[oid]
                    self.assertEqual(o["category"], category)
                    self.assertEqual(o["size"], size)
                    self.assertEqual(o["back"], back)
                    self.assertEqual(o["wealth"], wealth)
                    self.assertEqual(o["bands"], [band])
                    self.assertEqual(o["sources"], ["claude-authored"])
                    self.assertTrue(o["text"]["physical"])

    def test_every_new_object_binds_to_a_farm_purpose_role(self):
        for table, band in ((INDUSTRIAL_FARM_OBJECTS, "industrial"),
                            (MODERN_FARM_OBJECTS, "modern")):
            for oid, category, *_ in table:
                purpose, role = FARM_PURPOSE_ROLE[category]
                ids = set()
                for tier in self.lib.tiers:
                    ids |= {o["id"] for o in L.candidates(
                        self.lib, purpose, role, None, band, tier)}
                with self.subTest(object=oid, purpose=purpose, role=role):
                    self.assertIn(oid, ids, f"no {band} binding for {oid}")

    def test_the_medieval_set_is_reused_by_the_industrial_band(self):
        for oid, look in INDUSTRIAL_REUSE.items():
            o = self.lib.objects[oid]
            with self.subTest(object=oid):
                self.assertEqual(o["bands"], ["medieval", "industrial"])
                # the look changes only where the material class does
                self.assertEqual(o["partsByBand"],
                                 {"industrial": look} if look else {})
        for oid in ("coop.dovecote", "coop.skep"):
            with self.subTest(object=oid):
                self.assertEqual(self.lib.objects[oid]["bands"], ["medieval"])
        # the reused pieces really do furnish the industrial band: the
        # butter worker and the churn fill a dairy's slots
        for role_size, want in (((2, 1), "dairy.butter_worker"),
                                ((1, 1), "dairy.churn")):
            with self.subTest(reused=want):
                ids = {o["id"] for o in L.candidates(
                    self.lib, "dairy", "dairy", list(role_size),
                    "industrial", "modest")}
                self.assertIn(want, ids)


def _piece_sizes(room, role):
    """The role's piece sizes as sorted (w, h) pairs, orientation-free."""
    return {tuple(sorted(p["size"])) for p in room["pieces"] if p["role"] == role}


class TestMachineShedAndParlourRooms(unittest.TestCase):
    """rl-14c: the machine shed and milking parlour recipes have stored
    rooms whose machine slots only the new equipment fills — the industrial
    sheds hold the traction engine and thresher, the modern ones the tractor
    and combine, the parlour the milking stalls — while every room
    that shipped before rl-14c stands unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        by_family = {}
        for r in FR.load():
            if not r.get("retired"):
                by_family.setdefault(r["family"], []).append(r)
        cls.rooms = by_family

    def test_the_machine_sheds_hold_their_era_machines(self):
        sheds = [r for r in self.rooms["barn"]
                 if r["recipe"] in ("barn.machine_shed.a", "barn.machine_shed.b")]
        self.assertTrue(sheds, "no machine shed room was stored")
        cases = (
            ("barn.machine_shed.a", (3, 3), "industrial", "wealthy",
             "farm_machine.traction_engine"),
            ("barn.machine_shed.a", (2, 2), "industrial", "modest",
             "farm_machine.thresher"),
            ("barn.machine_shed.b", (2, 3), "modern", "poor",
             "farm_machine.tractor"),
            ("barn.machine_shed.b", (3, 4), "modern", "wealthy",
             "farm_machine.combine"),
        )
        for recipe, shape, band, tier, want in cases:
            rooms = [r for r in sheds if r["recipe"] == recipe
                     and shape in _piece_sizes(r, "machine")]
            with self.subTest(recipe=recipe, machine=want):
                self.assertTrue(rooms, f"no {recipe} room holds a {shape} machine")
                ids = {o["id"] for o in L.candidates(
                    self.lib, "machine_shed", "machine", list(shape), band, tier)}
                self.assertIn(want, ids)

    def test_the_parlour_holds_the_modern_machines(self):
        parlours = [r for r in self.rooms["dairy"]
                    if r["recipe"] == "dairy.parlour.b"]
        self.assertTrue(parlours, "no milking parlour room was stored")
        rooms = [r for r in parlours
                 if (1, 2) in _piece_sizes(r, "milking.stall")]
        self.assertTrue(rooms, "no parlour room holds a 1x2 milking stall")
        ids = {o["id"] for o in L.candidates(
            self.lib, "dairy", "milking.stall", [1, 2], "modern", "poor")}
        self.assertIn("dairy.milking_stall", ids)

    def test_the_industrial_dairy_separates_in_its_stored_rooms(self):
        """The dairy rooms rl-14b shipped need no new recipe: their dairy
        slots take the separator at the industrial band."""
        dairies = [r for r in self.rooms["dairy"] if r["recipe"] != "dairy.parlour.b"]
        self.assertTrue(dairies)
        self.assertTrue(any((1, 1) in _piece_sizes(r, "dairy") for r in dairies),
                        [(r["id"], sorted(_piece_sizes(r, "dairy")))
                         for r in dairies])
        ids = {o["id"] for o in L.candidates(
            self.lib, "dairy", "dairy", [1, 1], "industrial", "modest")}
        self.assertIn("dairy.separator", ids)

    def test_no_room_that_shipped_before_rl_14c_changed(self):
        for rid, recipe, size, pieces in PRE_RL14C_ROOMS:
            with self.subTest(room=rid):
                room = next((r for fam in self.rooms.values() for r in fam
                             if r["id"] == rid), None)
                self.assertIsNotNone(room, f"{rid} was dropped")
                self.assertEqual(room["recipe"], recipe)
                self.assertEqual(room["size"], size)
                self.assertEqual(len(room["pieces"]), pieces)


# the barn and dairy rooms as rl-14b shipped them: (id, recipe, size, pieces)
PRE_RL14C_ROOMS = (
    ("barn.large.a.grand.flush", "barn.hayloft.a", [7, 10], 6),
    ("barn.large.a.roomy.flush", "barn.hayloft.a", [6, 9], 6),
    ("barn.large.a.tight.flush", "barn.hayloft.a", [6, 9], 6),
    ("barn.large.b.roomy.open", "barn.large.a", [15, 8], 14),
    ("barn.large.c.grand.flush", "barn.large.a", [7, 17], 14),
    ("barn.large.c.roomy.flush", "barn.large.a", [8, 12], 14),
    ("barn.large.c.tight.flush", "barn.large.a", [7, 10], 14),
    ("barn.small.a.roomy.flush", "barn.shed.a", [9, 5], 6),
    ("barn.small.a.tight.flush", "barn.hayloft.a", [8, 5], 6),
    ("barn.small.a.tight.open", "barn.shed.a", [8, 6], 7),
    ("barn.small.b.tight.flush", "barn.shed.a", [8, 5], 6),
    ("barn.small.c.tight.flush", "barn.small.a", [7, 6], 7),
    ("dairy.medium.a.tight.flush", "dairy.creamery.a", [8, 4], 12),
    ("dairy.medium.b.tight.flush", "dairy.parlour.a", [6, 4], 9),
    ("dairy.small.a.roomy.flush", "dairy.small.a", [4, 4], 6),
    ("dairy.small.a.tight.flush", "dairy.small.a", [5, 3], 6),
)


# (id, category, size, back, wealth)
SCIFI_FARM_OBJECTS = (
    ("hydroponics.tower", "hydroponics", [1, 1], None,
     ["modest", "wealthy", "elite"]),
    ("hydroponics.algae_tank", "hydroponics", [2, 2], None, ["poor", "modest"]),
    ("hydroponics.vat_meat", "hydroponics", [2, 2], None,
     ["modest", "wealthy", "elite"]),
    ("granary.gene_bank", "granary", [2, 1], "north", ["wealthy", "elite"]),
    ("farm_machine.drone_feeder", "farm_machine", [1, 1], None,
     ["poor", "modest"]),
    ("farm_machine.auto_harvester", "farm_machine", [3, 3], None,
     ["wealthy", "elite"]),
)

# each scifi category's purpose and role under the vat farm (the gene bank
# also furnishes the granary purpose's own storage role)
SCIFI_FARM_PURPOSE_ROLE = {
    "hydroponics": ("vat_farm", "grow"),
    "granary": ("vat_farm", "storage.bulk"),
    "farm_machine": ("vat_farm", "machine"),
}


class TestScifiFarmObjects(unittest.TestCase):
    """rl-14d: the 6 scifi objects load with their band, wealth and top-down
    text, and every one binds to a farm purpose role in the scifi band."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)

    def test_every_scifi_farm_object_loads(self):
        for oid, category, size, back, wealth in SCIFI_FARM_OBJECTS:
            with self.subTest(object=oid):
                o = self.lib.objects[oid]
                self.assertEqual(o["category"], category)
                self.assertEqual(o["size"], size)
                self.assertEqual(o["back"], back)
                self.assertEqual(o["wealth"], wealth)
                self.assertEqual(o["bands"], ["scifi"])
                self.assertEqual(o["sources"], ["claude-authored"])
                self.assertTrue(o["text"]["physical"])

    def test_every_scifi_object_binds_to_a_farm_purpose_role(self):
        for oid, category, size, *_ in SCIFI_FARM_OBJECTS:
            purpose, role = SCIFI_FARM_PURPOSE_ROLE[category]
            ids = set()
            for tier in self.lib.tiers:
                ids |= {o["id"] for o in L.candidates(
                    self.lib, purpose, role, size, "scifi", tier)}
            with self.subTest(object=oid, purpose=purpose, role=role):
                self.assertIn(oid, ids, f"no scifi binding for {oid}")

    def test_the_gene_bank_also_furnishes_the_granary_purpose(self):
        ids = {o["id"] for o in L.candidates(
            self.lib, "granary", "storage.bulk", [2, 1], "scifi", "wealthy")}
        self.assertIn("granary.gene_bank", ids)


class TestVatFarmAndGeneBankRooms(unittest.TestCase):
    """rl-14d: the vat farm recipes have stored greenhouse rooms holding the
    2x2 grow tanks and the machines only the scifi set fills (the drone dock
    and the 3x3 harvester bay), the gene bank recipe has stored granary
    rooms at wealthy tiers, and every room that shipped before rl-14d
    stands unchanged (greenhouse stored none before rl-14d)."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        by_family = {}
        for r in FR.load():
            if not r.get("retired"):
                by_family.setdefault(r["family"], []).append(r)
        cls.rooms = by_family

    def test_the_vat_farm_has_stored_rooms(self):
        vats = [r for r in self.rooms["greenhouse"]
                if r["recipe"] in ("greenhouse.vat_farm.a",
                                   "greenhouse.vat_farm.b")]
        self.assertTrue(vats, "no vat farm room was stored")
        for r in vats:
            with self.subTest(room=r["id"]):
                self.assertIn((2, 2), _piece_sizes(r, "grow"))
                self.assertIn("machine", roles_of(r))
        self.assertTrue(any((3, 3) in _piece_sizes(r, "machine")
                            for r in vats
                            if r["recipe"] == "greenhouse.vat_farm.b"),
                        "no vat farm room holds a harvester bay")

    def test_the_vat_farm_slots_take_the_scifi_set(self):
        cases = (
            ("grow", (2, 2), "poor", "hydroponics.algae_tank"),
            ("grow", (2, 2), "modest", "hydroponics.vat_meat"),
            ("grow", (1, 1), "modest", "hydroponics.tower"),
            ("machine", (1, 1), "poor", "farm_machine.drone_feeder"),
            ("machine", (3, 3), "wealthy", "farm_machine.auto_harvester"),
        )
        for role, shape, tier, want in cases:
            with self.subTest(role=role, piece=want):
                ids = {o["id"] for o in L.candidates(
                    self.lib, "vat_farm", role, list(shape), "scifi", tier)}
                self.assertIn(want, ids)

    def test_the_gene_bank_has_stored_rooms(self):
        banks = [r for r in self.rooms["granary"]
                 if r["recipe"] == "granary.gene_bank.a"]
        self.assertTrue(banks, "no gene bank room was stored")
        for r in banks:
            with self.subTest(room=r["id"]):
                self.assertTrue(set(r["wealth"]) & {"wealthy", "elite"},
                                r["wealth"])
                self.assertIn((1, 2), _piece_sizes(r, "storage.bulk"))
        ids = {o["id"] for o in L.candidates(
            self.lib, "granary", "storage.bulk", [2, 1], "scifi", "wealthy")}
        self.assertIn("granary.gene_bank", ids)

    def test_no_room_that_shipped_before_rl_14d_changed(self):
        for rid, recipe, size, pieces in PRE_RL14D_ROOMS:
            with self.subTest(room=rid):
                room = next((r for fam in self.rooms.values() for r in fam
                             if r["id"] == rid), None)
                self.assertIsNotNone(room, f"{rid} was dropped")
                self.assertEqual(room["recipe"], recipe)
                self.assertEqual(room["size"], size)
                self.assertEqual(len(room["pieces"]), pieces)


# the granary rooms as rl-14b shipped them (the family rl-14d adds a recipe
# to; greenhouse stored no rooms before rl-14d): (id, recipe, size, pieces)
PRE_RL14D_ROOMS = (
    ("granary.medium.a.tight.flush", "granary.long.a", [8, 6], 14),
    ("granary.small.a.tight.flush", "granary.small.a", [6, 4], 8),
)


# rl-14f's wings: (id, band, purpose, storeys)
FARMSTEAD_WINGS = (
    ("farm.longhouse", "medieval", "common_rooms", 2),
    ("farm.sheds.industrial", "industrial", "stables", 2),
    ("ranch.house", "modern", "common_rooms", 1),
    ("ranch.sheds", "modern", "stables", 1),
    ("agri.dome", "scifi", "workshop", 1),
)

# rl-14f's buildings: (id, band, shape)
FARMSTEAD_BUILDINGS = (
    ("farmstead.industrial", "industrial", "l"),
    ("ranch.courtyard", "modern", "courtyard"),
    ("agri.station", "scifi", "spine"),
)

# rl-14f's suites: (id, band, a planner kind that finds it, room purposes)
FARMSTEAD_SUITES = (
    ("farm.mixed", "industrial", "steading",
     ("barn", "dairy", "granary", "kitchen", "living_room", "master_bedroom")),
    ("farm.ranch", "modern", "farmhouse",
     ("bedroom", "kitchen", "living_room", "machine_shed", "master_bedroom",
      "washroom")),
    ("farm.agridome", "scifi", "agri dome",
     ("hydroponics_bay", "laboratory", "storage", "vat_farm")),
)


class TestFarmsteadRecipesPerEra(unittest.TestCase):
    """rl-14f: the farmstead wings, buildings and suites of every era load
    and check clean; the barn wings stand two storeys with a hayloft upstairs
    (design 8.1g); and the farmhouse wing's Dairy is the dairy purpose."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        cls.errors, cls.warnings = L.check(cls.lib)

    def test_the_shipped_library_still_checks_clean(self):
        self.assertEqual(self.errors, [], "\n".join(self.errors[:40]))

    def test_every_new_wing_loads_as_declared(self):
        for wid, band, purpose, storeys in FARMSTEAD_WINGS:
            with self.subTest(wing=wid):
                w = self.lib.wings[wid]
                self.assertEqual(w["bands"], [band])
                self.assertEqual(w["purpose"], purpose)
                self.assertEqual(w["storeys"], storeys)

    def test_the_barn_wings_stand_two_storeys_with_a_hayloft(self):
        for wid in ("farm.longhouse", "farm.sheds.industrial"):
            with self.subTest(wing=wid):
                w = self.lib.wings[wid]
                self.assertEqual(w["storeys"], 2)
                lofts = [r for r in w["rooms"] if r["purpose"] == "hayloft"]
                self.assertEqual(len(lofts), 1, [r["purpose"] for r in w["rooms"]])
                self.assertEqual(self.lib.family_of("hayloft"), "barn")

    def test_every_new_wing_rooms_resolve_to_farm_families(self):
        for wid, families in (
                ("farm.longhouse",
                 ("barn", "barn", "bedroom", "common_room", "kitchen", "stable")),
                ("farm.sheds.industrial",
                 ("barn", "barn", "dairy", "granary")),
                ("ranch.house",
                 ("bedroom", "bedroom.master", "common_room", "kitchen",
                  "washroom")),
                ("ranch.sheds", ("barn", "dairy", "granary")),
                ("agri.dome",
                 ("greenhouse", "greenhouse", "laboratory", "storage"))):
            with self.subTest(wing=wid):
                fams = sorted(self.lib.family_of(r["purpose"])
                              for r in self.lib.wings[wid]["rooms"])
                self.assertEqual(fams, sorted(families), fams)

    def test_the_farm_house_dairy_is_the_dairy_purpose(self):
        rooms = {r["name"]: r for r in self.lib.wings["farm.house"]["rooms"]}
        self.assertEqual(rooms["Dairy"]["purpose"], "dairy")
        self.assertEqual(self.lib.family_of("dairy"), "dairy")
        # the industrial farmstead reuses the farmhouse wing
        self.assertEqual(self.lib.wings["farm.house"]["bands"],
                         ["medieval", "industrial"])

    def test_every_new_building_loads_and_names_its_wings(self):
        for bid, band, shape in FARMSTEAD_BUILDINGS:
            with self.subTest(building=bid):
                b = self.lib.buildings[bid]
                self.assertEqual(b["bands"], [band])
                self.assertEqual(b["shape"], shape)
                for e in b["wings"]:
                    self.assertIn(e["wing"], self.lib.wings)
                    self.assertIn(band, self.lib.wings[e["wing"]]["bands"])

    def test_the_ranch_and_station_outdoors_are_farm_grounds(self):
        ranch = self.lib.buildings["ranch.courtyard"]
        self.assertEqual({o["purpose"] for o in ranch["outdoor"]},
                         {"paddock", "farmyard"})
        station = self.lib.buildings["agri.station"]
        self.assertEqual([o["purpose"] for o in station["outdoor"]], ["garden"])
        for b in (ranch, station):
            for o in b["outdoor"]:
                with self.subTest(outdoor=o["name"]):
                    self.assertIn(self.lib.family_of(o["purpose"]),
                                  self.lib.outdoor_families())

    def test_every_new_suite_loads_and_matches_its_planner_kinds(self):
        from worldgen import library_plan as LP
        for sid, band, kind, purposes in FARMSTEAD_SUITES:
            s = self.lib.suites[sid]
            with self.subTest(suite=sid):
                self.assertEqual(s["bands"], [band])
                self.assertEqual(sorted(r["purpose"] for r in s["rooms"]),
                                 sorted(purposes))
                found = LP.suite_by_kind(
                    self.lib, {"kind": kind, "sizeClass": "large",
                               "residents": 4 if band != "scifi" else 0}, band)
                self.assertEqual((found or {}).get("id"), sid)


FRONT_OF = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _front_cell(piece):
    """The open cell a piece's front (the side opposite its back) is used
    from: the middle cell of that side — of two middle cells the lower-left
    one — the same cell fixed_rooms derives from the role's access rule."""
    x, y = piece["at"]
    w, h = piece["size"]
    side = FRONT_OF[piece["back"]]
    if side == "north":
        return (x + (w - 1) // 2, y - 1)
    if side == "south":
        return (x + (w - 1) // 2, y + h)
    if side == "west":
        return (x - 1, y + h // 2)
    return (x + w, y + h // 2)


class TestTheMilkingStall(unittest.TestCase):
    """rl-14g: the 3x2 parlour stalls object became one 1x2 milking stall —
    the old id is gone, the new object loads with its role and access rule,
    the sprite index points at the new id, the regenerated dairy rooms set
    the stalls in rows of two and three with each stall's rear cell open
    floor, and the bands without the stall keep their dairy rooms."""

    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)

    def test_parlour_stalls_is_gone_and_the_stall_loads(self):
        self.assertNotIn("dairy.parlour_stalls", self.lib.objects)
        o = self.lib.objects["dairy.milking_stall"]
        self.assertEqual(o["aliases"],
                         ["milking stall", "milking stalls", "parlour stalls"])
        access = self.lib.vocab["roleAccess"]
        self.assertEqual(access.get("milking.stall"), "front")
        self.assertEqual(L.check_role_access(self.lib.vocab), [])

    def test_the_stall_binds_only_where_it_exists(self):
        for purpose in ("dairy", "milking_parlour"):
            ids = {o["id"] for t in self.lib.tiers for o in L.candidates(
                self.lib, purpose, "milking.stall", [1, 2], "modern", t)}
            with self.subTest(purpose=purpose):
                self.assertIn("dairy.milking_stall", ids)
        for band in ("medieval", "industrial", "scifi"):
            ids = {o["id"] for t in self.lib.tiers for o in L.candidates(
                self.lib, "dairy", "milking.stall", None, band, t)}
            self.assertEqual(ids, set(), f"a {band} milking stall exists")

    def test_the_stall_rooms_hold_rows_reachable_from_the_rear(self):
        rows = []
        for room in FR.load():
            stalls = [p for p in room["pieces"]
                      if p["role"] == "milking.stall" and not p.get("optional")]
            if not stalls:
                continue
            with self.subTest(room=room["id"]):
                # two or three stalls, one row side by side, backs alike
                self.assertIn(len(stalls), (2, 3), [p["at"] for p in stalls])
                backs = {p["back"] for p in stalls}
                self.assertEqual(backs, {stalls[0]["back"]}, [p["back"] for p in stalls])
                step = (1, 0) if stalls[0]["back"] in ("north", "south") else (0, 1)
                starts = sorted((p["at"][0] * step[0] + p["at"][1] * step[1],
                                 p["at"][0] * (1 - step[0]) + p["at"][1] * (1 - step[1]))
                                for p in stalls)
                self.assertEqual([s[0] for s in starts], list(range(starts[0][0], starts[0][0] + len(stalls))),
                                 [p["at"] for p in stalls])
                self.assertEqual(len({s[1] for s in starts}), 1,
                                 "the stalls are not in one row")
                # each stall is reached from its open rear: the front cell is
                # open floor inside the room
                W, H = room["size"]
                covered = {(x, y) for p in room["pieces"]
                           for x in range(p["at"][0], p["at"][0] + p["size"][0])
                           for y in range(p["at"][1], p["at"][1] + p["size"][1])}
                for p in stalls:
                    cx, cy = _front_cell(p)
                    self.assertTrue(0 <= cx < W and 0 <= cy < H,
                                    (p["at"], (cx, cy), room["size"]))
                    self.assertNotIn((cx, cy), covered,
                                     f"stall at {p['at']} has its rear blocked")
            rows.append(room)
        self.assertTrue(rows, "no stored room holds a row of milking stalls")
        bands = {r["sizeBand"] for r in rows}
        self.assertIn("medium", bands, "no parlour-sized stall room")
        self.assertIn("small", bands, "no small stall room")

    def test_the_sprite_index_points_at_the_new_stall(self):
        import os
        from worldgen import library_art
        idx = library_art.load_index("modern")
        self.assertNotIn("dairy.parlour_stalls", idx)
        entry = idx.get("dairy.milking_stall")
        self.assertIsNotNone(entry, "the modern index has no milking stall")
        self.assertTrue(entry.get("reviewed"))
        self.assertIn("milking stall", entry.get("physical", ""))
        o = self.lib.objects["dairy.milking_stall"]
        self.assertEqual(set(entry.get("materials", {})), set(o["parts"]))
        self.assertTrue(os.path.exists(
            library_art.sprite_path("modern", "dairy.milking_stall")))
        self.assertFalse(os.path.exists(
            library_art.sprite_path("modern", "dairy.parlour_stalls")))


if __name__ == "__main__":
    unittest.main()
