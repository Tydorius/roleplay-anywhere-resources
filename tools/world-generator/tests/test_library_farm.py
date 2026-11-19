"""rl-14a: the farming vocabulary — categories, roles, families and purposes —
and the 18 medieval farm objects: they load, the shipped library still checks
clean, every object reaches at least one purpose role, and the barn purpose
now names the barn family."""
import unittest

from worldgen import library as L
from worldgen import room_groups as RG

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


if __name__ == "__main__":
    unittest.main()
