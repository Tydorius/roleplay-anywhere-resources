"""Wing and building recipes (rl-08, design 8.1-8.3): the shipped files load
and check clean, the checker rejects the recipes it exists to reject,
building_by_kind matches kind words the suite way, and design 8.3's default
wealth offsets apply."""
import copy
import json
import os
import tempfile
import unittest

from worldgen import library as L
from worldgen import library_plan as LP


def shipped():
    return L.load(L.LIB_DIR)


def bare():
    """A library with only the vocabulary, to break recipes in on purpose."""
    lib = L.Library("memory")
    lib.vocab = copy.deepcopy(shipped().vocab)
    return lib


GOOD_WING = {
    "id": "test.chamber", "purpose": "sleeping", "kinds": ["test house"],
    "bands": ["medieval"], "storeys": 1, "entry": "south",
    "rooms": [{"name": "Chamber", "purpose": "bedroom", "share": "small"}],
    "connections": [], "entrance": {"room": "Chamber"}, "sleeps": "residents"}


def yard_lib():
    """A library with three one-room wings to build a courtyard from."""
    lib = bare()
    for wid, purpose in (("a.front", "common_rooms"), ("a.east", "stables"),
                         ("a.west", "sleeping")):
        lib.wings[wid] = {
            "id": wid, "purpose": purpose, "kinds": ["test house"], "bands": ["medieval"],
            "storeys": 1, "entry": "south",
            "rooms": [{"name": "Room", "purpose": "storage", "share": "small"}],
            "connections": [], "entrance": {"room": "Room"}, "sleeps": "none"}
    return lib


GOOD_BUILDING = {
    "id": "test.yard", "kinds": ["test house"], "bands": ["medieval"], "shape": "courtyard",
    "wings": [{"wing": "a.front", "side": "south"}, {"wing": "a.east", "side": "east"},
              {"wing": "a.west", "side": "west"}],
    "outdoor": [{"name": "Yard", "purpose": "courtyard", "between": "all"}],
    "entrance": {"wing": "a.front"}}


class TestShippedRecipes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = shipped()
        cls.errors, cls.warnings = L.check(cls.lib)

    def test_no_errors(self):
        self.assertEqual(self.errors, [], "\n".join(self.errors[:40]))

    def test_every_band_has_wings_and_buildings(self):
        for band in self.lib.bands:
            self.assertTrue([w for w in self.lib.wings.values()
                             if band in w.get("bands", [])], band)
            self.assertTrue([b for b in self.lib.buildings.values()
                             if band in b.get("bands", [])], band)

    def test_the_first_recipes_ship(self):
        for bid in ("inn.courtyard", "merchant.house", "manor.u", "farmstead.l",
                    "castle.courtyard", "clinic.spine", "station.research"):
            self.assertIn(bid, self.lib.buildings)
        for wid in ("inn.front", "sleeping.inn", "stables.yard", "manor.service",
                    "castle.barracks"):
            self.assertIn(wid, self.lib.wings)

    def test_the_good_recipe_checks_clean(self):
        lib = yard_lib()
        lib.buildings["test.yard"] = copy.deepcopy(GOOD_BUILDING)
        self.assertEqual([e for e in L.check(lib, sources_path=None)[0]
                          if "wing " in e or "building " in e], [])

    def test_duplicate_ids_are_reported_first_wins(self):
        # the temp folder must share a drive with the library: relpath cannot
        # span drives on Windows
        with tempfile.TemporaryDirectory(dir=".") as d:
            os.makedirs(os.path.join(d, "wings"))
            for name in ("a.json", "b.json"):
                with open(os.path.join(d, "wings", name), "w", encoding="utf-8") as f:
                    json.dump({"wings": [{"id": "dup.wing"}]}, f)
            lib = L.load(d)
        self.assertEqual(list(lib.wings), ["dup.wing"])
        self.assertTrue(any("wing id 'dup.wing'" in e for e in lib.dupes))


class TestWingChecker(unittest.TestCase):
    def errs(self, lib):
        return L.check(lib, sources_path=None)[0]

    def wing(self, **over):
        lib = bare()
        w = copy.deepcopy(GOOD_WING)
        w.update(over)
        lib.wings[w["id"]] = w
        return lib

    def test_a_room_purpose_must_exist(self):
        lib = self.wing(sleeps="none",
                        rooms=[{"name": "X", "purpose": "flying_room", "share": "small"}])
        self.assertTrue(any("unknown purpose 'flying_room'" in e for e in self.errs(lib)))

    def test_a_connection_must_name_a_room(self):
        lib = self.wing(connections=[["Chamber", "Nowhere"]])
        self.assertTrue(any("connection ['Chamber', 'Nowhere'] names a missing room"
                            in e for e in self.errs(lib)))

    def test_the_entrance_room_must_exist(self):
        lib = self.wing(entrance={"room": "Porch"})
        self.assertTrue(any("entrance room 'Porch' is not a room" in e for e in self.errs(lib)))

    def test_an_offset_outside_the_tiers_is_an_error(self):
        lib = self.wing(wealth=-4)
        self.assertTrue(any("wealth must be an offset -3..1" in e for e in self.errs(lib)))


class TestBuildingChecker(unittest.TestCase):
    def errs(self, lib):
        return L.check(lib, sources_path=None)[0]

    def building(self, **over):
        lib = yard_lib()
        b = copy.deepcopy(GOOD_BUILDING)
        b.update(over)
        lib.buildings[b["id"]] = b
        return lib

    def test_a_wing_missing_from_the_library_is_an_error(self):
        lib = self.building()
        del lib.wings["a.west"]
        self.assertTrue(any("wing 'a.west' is not in the wing library"
                            in e for e in self.errs(lib)))

    def test_a_side_the_shape_does_not_have(self):
        lib = self.building(shape="l",
                            wings=[{"wing": "a.front", "side": "south"},
                                   {"wing": "a.east", "side": "north"}],
                            outdoor=[{"name": "Yard", "purpose": "yard", "between": "wings"}])
        e = self.errs(lib)
        self.assertTrue(any("shape l wants two wings on perpendicular sides" in x for x in e), e)

    def test_a_courtyard_has_an_outdoor_room(self):
        lib = self.building(outdoor=[])
        self.assertTrue(any("a courtyard has an outdoor room" in e for e in self.errs(lib)))

    def test_the_entrance_must_name_a_wing(self):
        lib = self.building(entrance={"wing": "a.north"})
        self.assertTrue(any("entrance wing 'a.north' is not a wing of this building"
                            in e for e in self.errs(lib)))

    def test_a_kind_word_belongs_to_one_recipe_per_band(self):
        lib = self.building()
        lib.buildings["other.yard"] = copy.deepcopy(GOOD_BUILDING)
        lib.buildings["other.yard"]["id"] = "other.yard"
        self.assertTrue(any("kind 'test house' is claimed by" in e for e in self.errs(lib)))


class TestBuildingByKind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = shipped()

    def test_coaching_inn_finds_the_courtyard_inn(self):
        r = LP.building_by_kind(self.lib, "coaching inn", "medieval")
        self.assertEqual((r or {}).get("id"), "inn.courtyard")

    def test_keep_finds_the_castle(self):
        r = LP.building_by_kind(self.lib, "keep", "medieval")
        self.assertEqual((r or {}).get("id"), "castle.courtyard")

    def test_teapot_finds_nothing(self):
        self.assertIsNone(LP.building_by_kind(self.lib, "teapot", "medieval"))

    def test_the_band_must_match(self):
        self.assertIsNone(LP.building_by_kind(self.lib, "coaching inn", "scifi"))

    def test_the_most_specific_recipe_wins(self):
        lib = bare()
        lib.buildings = {
            "a.inn": {"id": "a.inn", "kinds": ["inn"], "bands": ["medieval"]},
            "b.inn": {"id": "b.inn", "kinds": ["coaching inn"], "bands": ["medieval"]}}
        self.assertEqual(LP.building_by_kind(lib, "coaching inn", "medieval")["id"], "b.inn")
        self.assertEqual(LP.building_by_kind(lib, "inn", "medieval")["id"], "a.inn")

    def test_a_tie_names_no_winner(self):
        lib = bare()
        lib.buildings = {
            "a.inn": {"id": "a.inn", "kinds": ["inn"], "bands": ["medieval"]},
            "b.inn": {"id": "b.inn", "kinds": ["inn"], "bands": ["medieval"]}}
        self.assertIsNone(LP.building_by_kind(lib, "inn", "medieval"))


class TestWealthOffsets(unittest.TestCase):
    def test_design_83_defaults(self):
        self.assertEqual(L.WING_WEALTH_OFFSETS,
                         {"servants": -2, "barracks": -1, "kitchen_storage": -1, "stables": -2})

    def test_wing_wealth_defaults_and_overrides(self):
        self.assertEqual(L.wing_wealth({"purpose": "stables"}), -2)
        self.assertEqual(L.wing_wealth({"purpose": "servants"}), -2)
        self.assertEqual(L.wing_wealth({"purpose": "barracks"}), -1)
        self.assertEqual(L.wing_wealth({"purpose": "sleeping"}), "building")
        self.assertEqual(L.wing_wealth({"purpose": "stables", "wealth": "poor"}), "poor")
        self.assertEqual(L.wing_wealth({"purpose": "stables", "wealth": -1}), -1)

    def test_the_shipped_wings_default_as_the_design_says(self):
        lib = shipped()
        self.assertEqual(L.wing_wealth(lib.wings["stables.yard"]), -2)
        self.assertEqual(L.wing_wealth(lib.wings["castle.barracks"]), -1)
        self.assertEqual(L.wing_wealth(lib.wings["manor.service"]), -2)
        self.assertEqual(L.wing_wealth(lib.wings["sleeping.inn"]), "building")

    def test_the_checker_reports_an_applied_default(self):
        _, warnings = L.check(shipped())
        self.assertTrue(any("stables.yard" in w and "defaults to -2" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
