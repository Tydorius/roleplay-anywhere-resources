"""Room library step 10: a compound whose kind names a building recipe is
laid out from that recipe. Each wing becomes a part design — rooms by the
wing's purposes and shares, the entry side the recipe's shape asks for,
storeys within the height rules, wealth off the building's tier with the
wing's own step applied — assembled in wing mode where the closers can
meet the rectangle, falling back to the plain build with the reason
recorded where they cannot, and the compound still builds: gates, walls
and courtyard placed by the machinery that already did it. The coaching
inn closes round a furnished courtyard, its stables two wealth tiers
below the gate range, the P1 rooms whose purposes match keeping their
names and the one that matches no wing dropped with a note; the
merchant's house and the farmstead take their recipes' shapes; a
compound no recipe names lays out exactly as it did before, on or off;
and a block recipe stands a single building for its one wing while the
switch is off leaves it as the plan drew it."""
import copy
import json
import unittest
from unittest import mock

import worldgen
from worldgen import library_plan

CHECKS = ("region_overlaps", "object_overlaps", "reachability",
          "doors_clear", "walkways_clear")


def skeleton(name, background):
    """The shared plan frame: one crossroads zone for the compound, one
    hamlet down the road so the world has a road and a start."""
    return {
        "name": name, "worldBackground": background, "mapSize": "medium",
        "setting": {"era": "medieval", "technology": "stone and iron",
                    "density": "sparse", "climate": "temperate"},
        "zones": [], "roads": [], "templates": [], "buildings": [],
        "npcs": [], "player": {"name": "Traveller"}, "extensions": [],
    }


def zone_entry(name, kind, size, purpose, wealth=""):
    entry = {"name": name, "kind": kind, "sizeClass": size,
             "purpose": purpose, "storeys": 2, "yard": None}
    if wealth:
        entry["wealth"] = wealth
    return entry


def building_spec(name, rooms):
    return {"name": name, "wall": "timber", "ground": "wood",
            "rooms": [{"name": rn, "share": rs, "purpose": "p", "use": ru}
                      for (rn, rs, ru) in rooms],
            "connections": [], "entrance": {"room": rooms[0][0],
                                            "side": "south"},
            "furniture": []}


def inn_plan():
    plan = skeleton("Innvale",
                    "A coaching inn at the crossroads, its yard open to the "
                    "road, stables behind, and beds upstairs.")
    plan["zones"] = [{
        "name": "Crossroads", "kind": "village crossroads", "sizeClass": "large",
        "description": "The inn round its yard at the meeting of two roads.",
        "ground": "grass", "adjacentTo": [], "outdoor": [],
        "buildings": [
            zone_entry("The Gilded Stag", "coaching inn", "medium",
                       "the inn itself, taproom and kitchen", "wealthy"),
            zone_entry("Stable Range", "stable", "medium",
                       "the stables and tack", "wealthy"),
            zone_entry("Guest Range", "posting house", "medium",
                       "the guest chambers", "wealthy"),
            zone_entry("Brew House", "brewery", "hut",
                       "the brewer's shed", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages down the road from the inn.",
        "ground": "grass", "adjacentTo": ["Crossroads"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["compounds"] = [{
        "name": "The Gilded Stag Inn", "zone": "Crossroads",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "The Gilded Stag", "at": "edge:south:center",
             "gate": True},
            {"building": "Stable Range", "at": "edge:east:center"},
            {"building": "Guest Range", "at": "edge:west:center"},
            {"building": "Brew House", "at": "edge:north:center"},
        ],
    }]
    plan["buildings"] = [
        building_spec("The Gilded Stag",
                      [("Common Room", "large", "taproom"),
                       ("Inn Kitchen", "medium", "kitchen")]),
        building_spec("Stable Range", [("Stables", "large", "stable")]),
        building_spec("Guest Range", [("Guest Hall", "medium", "hallway")]),
        building_spec("Brew House", [("Brewhouse", "medium", "kitchen")]),
    ]
    plan["roads"] = [{"from": "Crossroads", "to": "Emberford", "kind": "dirt"}]
    return plan


def merchant_plan():
    plan = skeleton("Shapevale", "A compound at the crossroads.")
    plan["zones"] = [{
        "name": "Crossroads", "kind": "village crossroads", "sizeClass": "large",
        "description": "The compound.", "ground": "grass", "adjacentTo": [],
        "outdoor": [],
        "buildings": [
            zone_entry("The Merchant's House", "merchant's house", "medium",
                       "the house itself", "wealthy"),
            zone_entry("Shop Front", "shop", "medium", "part", "wealthy"),
            zone_entry("Family Range", "house", "medium", "part", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["Crossroads"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["compounds"] = [{
        "name": "The Merchant's House Compound", "zone": "Crossroads",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "The Merchant's House", "at": "edge:south:center",
             "gate": True},
            {"building": "Shop Front", "at": "edge:west:center"},
            {"building": "Family Range", "at": "edge:east:center"},
        ],
    }]
    plan["buildings"] = [
        building_spec("The Merchant's House", [("Bar", "large", "taproom")]),
        building_spec("Shop Front", [("Shop", "medium", "shop")]),
        building_spec("Family Range", [("Hall", "medium", "living_room")]),
    ]
    plan["roads"] = [{"from": "Crossroads", "to": "Emberford", "kind": "dirt"}]
    return plan


def farm_plan():
    plan = skeleton("Fieldvale", "A farmstead under the hill.")
    plan["zones"] = [{
        "name": "Hillfoot", "kind": "village crossroads", "sizeClass": "large",
        "description": "The farmstead.", "ground": "grass", "adjacentTo": [],
        "outdoor": [],
        "buildings": [
            zone_entry("Millfield Farmhouse", "farmstead", "medium",
                       "the house itself", "wealthy"),
            zone_entry("The Barn", "barn", "medium", "part", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["Hillfoot"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["compounds"] = [{
        "name": "Millfield Compound", "zone": "Hillfoot",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "Millfield Farmhouse", "at": "edge:south:center",
             "gate": True},
            {"building": "The Barn", "at": "edge:east:center"},
        ],
    }]
    plan["buildings"] = [
        building_spec("Millfield Farmhouse",
                      [("Farmhouse Hall", "medium", "living_room")]),
        building_spec("The Barn", [("Barn Room", "large", "barn")]),
    ]
    plan["roads"] = [{"from": "Hillfoot", "to": "Emberford", "kind": "dirt"}]
    return plan


def hold_plan():
    """A compound whose gate names no recipe: nothing about it changes."""
    plan = skeleton("Holdvale", "A hold behind a gatehouse.")
    plan["zones"] = [{
        "name": "The Holding", "kind": "village crossroads", "sizeClass": "large",
        "description": "The hold.", "ground": "grass", "adjacentTo": [],
        "outdoor": [],
        "buildings": [
            zone_entry("The Gate House", "gatehouse", "medium",
                       "the gate and its room"),
            zone_entry("Store Shed", "storehouse", "small", "part"),
            zone_entry("Hall Block", "hall", "medium", "part"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["The Holding"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["compounds"] = [{
        "name": "The Hold", "zone": "The Holding",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "The Gate House", "at": "edge:south:center",
             "gate": True},
            {"building": "Store Shed", "at": "edge:east:center"},
            {"building": "Hall Block", "at": "edge:west:center"},
        ],
    }]
    plan["buildings"] = [
        {"name": "The Gate House", "wall": "timber", "ground": "wood",
         "rooms": [{"name": "Gate Room", "share": "medium",
                    "purpose": "the gate"}],
         "connections": [], "entrance": {"room": "Gate Room", "side": "south"},
         "furniture": []},
        {"name": "Store Shed", "wall": "timber", "ground": "dirt",
         "rooms": [{"name": "Stores", "share": "large",
                    "purpose": "the stores"}],
         "connections": [], "entrance": {"room": "Stores", "side": "west"},
         "furniture": []},
        {"name": "Hall Block", "wall": "timber", "ground": "wood",
         "rooms": [{"name": "Hall", "share": "large",
                    "purpose": "the hall"}],
         "connections": [], "entrance": {"room": "Hall", "side": "east"},
         "furniture": []},
    ]
    plan["roads"] = [{"from": "The Holding", "to": "Emberford", "kind": "dirt"}]
    return plan


def hostel_plan():
    plan = skeleton("Wayfare",
                    "A single hostelry on the road, one room behind the door.")
    plan["zones"] = [{
        "name": "The Street", "kind": "village", "sizeClass": "medium",
        "description": "The hostelry.", "ground": "grass", "adjacentTo": [],
        "outdoor": [],
        "buildings": [zone_entry("The Wayfarer's Rest", "hostelry", "medium",
                                 "the common room", "wealthy")],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["The Street"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["buildings"] = [
        building_spec("The Wayfarer's Rest",
                      [("Common Room", "large", "taproom")]),
    ]
    plan["roads"] = [{"from": "The Street", "to": "Emberford", "kind": "dirt"}]
    return plan


def compound_of(world, name):
    for comp in world.compounds:
        if comp.name == name:
            return comp
    return None


def part(comp, name):
    for b in comp.parts:
        if b.layout.design.name == name:
            return b.layout
    return None


def names_of(bl):
    return [r.base_name for r in bl.rooms]


def structure(comp):
    """Everything the compound's placement decides, named so two runs of
    the same plan can be compared cell for cell."""
    return (comp.compound.shape, str(comp.courtyard),
            tuple((b.layout.design.name, str(b.layout.rect))
                  for b in comp.parts))


class TestCourtyardInnFromRecipe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(inn_plan(), seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "The Gilded Stag Inn")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def test_the_recipe_decides_the_part_list(self):
        self.assertEqual([b.layout.design.name for b in self.comp.parts],
                         ["The Gilded Stag", "Stable Range", "Guest Range"])
        self.assertIn(("compound The Gilded Stag Inn",
                       "part Brew House dropped: recipe inn.courtyard "
                       "has no wing for a brewery"),
                      self.world.failures, self.world.failures)

    def test_the_front_range_assembles_with_the_p1_names(self):
        bl = part(self.comp, "The Gilded Stag")
        self.assertTrue(getattr(bl, "assembled", False),
                        self.world.fallbacks)
        self.assertEqual(set(names_of(bl)),
                         {"Common Room", "Inn Kitchen", "Pantry"})
        self.assertEqual(bl.design.wealth, "wealthy")
        self.assertEqual(bl.design.storeys, 1)

    def test_the_stables_sit_two_tiers_down_and_say_why(self):
        bl = part(self.comp, "Stable Range")
        self.assertEqual(bl.design.wealth, "poor")
        self.assertEqual(bl.design.storeys, 2)
        self.assertEqual(set(names_of(bl)), {"Stables", "Tack room"})
        if not getattr(bl, "assembled", False):
            self.assertTrue([f for f in self.world.fallbacks
                             if f[0] == "building Stable Range"],
                            self.world.fallbacks)

    def test_the_guest_range_keeps_its_p1_name(self):
        bl = part(self.comp, "Guest Range")
        self.assertIn("Guest Hall", names_of(bl))
        self.assertEqual(bl.design.wealth, "wealthy")
        if not getattr(bl, "assembled", False):
            self.assertTrue([f for f in self.world.fallbacks
                             if f[0] == "building Guest Range"],
                            self.world.fallbacks)

    def test_the_courtyard_is_furnished_and_the_checks_clean(self):
        self.assertIsNotNone(self.comp.courtyard)
        self.assertEqual(self.comp.court_family, "courtyard")
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))

    def test_the_recipes_courtyard_shape_maps_onto_the_enclosure(self):
        self.assertEqual(self.comp.compound.shape, "enclosure")
        self.assertEqual(self.comp.compound.walls, "none")


class TestMerchantsHouseFromRecipe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(merchant_plan(), seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "The Merchant's House Compound")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def test_the_recipe_decides_the_part_list(self):
        self.assertEqual([b.layout.design.name for b in self.comp.parts],
                         ["The Merchant's House", "Family Range"])
        self.assertIn(("compound The Merchant's House Compound",
                       "part Shop Front dropped: recipe merchant.house "
                       "has no wing for a shop"),
                      self.world.failures, self.world.failures)

    def test_both_wings_assemble(self):
        for name in ("The Merchant's House", "Family Range"):
            bl = part(self.comp, name)
            self.assertTrue(getattr(bl, "assembled", False),
                            (name, self.world.fallbacks))

    def test_the_p1_names_survive_where_the_family_matches(self):
        self.assertIn("Hall", names_of(part(self.comp, "Family Range")))
        self.assertIn("Shop", names_of(part(self.comp, "The Merchant's House")))

    def test_the_village_caps_both_wings_at_one_storey(self):
        for name in ("The Merchant's House", "Family Range"):
            self.assertEqual(part(self.comp, name).design.storeys, 1, name)

    def test_the_checks_stay_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))


class TestFarmsteadFromRecipe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(farm_plan(), seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "Millfield Compound")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def test_the_recipe_decides_the_part_list(self):
        self.assertEqual([b.layout.design.name for b in self.comp.parts],
                         ["Millfield Farmhouse", "The Barn"])

    def test_both_wings_assemble_with_the_p1_names(self):
        house = part(self.comp, "Millfield Farmhouse")
        barn = part(self.comp, "The Barn")
        self.assertTrue(getattr(house, "assembled", False),
                        self.world.fallbacks)
        self.assertTrue(getattr(barn, "assembled", False),
                        self.world.fallbacks)
        self.assertIn("Farmhouse Hall", names_of(house))
        self.assertIn("Barn Room", names_of(barn))

    def test_the_barn_sits_two_tiers_down(self):
        self.assertEqual(part(self.comp, "Millfield Farmhouse").design.wealth,
                         "wealthy")
        self.assertEqual(part(self.comp, "The Barn").design.wealth, "poor")

    def test_the_checks_stay_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))


class TestCompoundWithoutARecipe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan = hold_plan()
        cls.on = worldgen.run(copy.deepcopy(plan), seed=1, room_assembler=True)
        cls.off = worldgen.run(copy.deepcopy(plan), seed=1,
                               room_assembler=False)

    def _comp(self, world):
        comp = compound_of(world, "The Hold")
        self.assertIsNotNone(comp, world.failures)
        return comp

    def test_the_structure_is_unchanged_on_and_off(self):
        self.assertEqual(structure(self._comp(self.on)),
                         structure(self._comp(self.off)))

    def test_the_compound_was_never_expanded(self):
        for world in (self.on, self.off):
            self.assertFalse(getattr(self._comp(world).compound,
                                     "from_recipe", None))

    def test_the_parts_stay_the_plans_own(self):
        comp = self._comp(self.on)
        self.assertEqual([b.layout.design.name for b in comp.parts],
                         ["The Gate House", "Store Shed", "Hall Block"])
        self.assertEqual([names_of(b.layout) for b in comp.parts],
                         [["Gate Room"], ["Stores"], ["Hall"]])

    def test_the_checks_stay_clean_both_ways(self):
        for world in (self.on, self.off):
            m = world.metrics
            self.assertEqual(m["reachability"], 1.0, m.get("objects"))
            self.assertTrue(m["doors_clear"], m.get("doors"))


class TestBlockRecipeForASingleBuilding(unittest.TestCase):
    RECIPE = {"id": "test.hostel", "shape": "block",
              "wings": [{"wing": "inn.front"}]}

    @classmethod
    def setUpClass(cls):
        real = library_plan.building_by_kind

        def by_kind(lib, kind, band):
            if kind == "hostelry":
                return cls.RECIPE
            return real(lib, kind, band)
        with mock.patch.object(library_plan, "building_by_kind",
                               side_effect=by_kind):
            cls.on = worldgen.run(hostel_plan(), seed=1, room_assembler=True)
            cls.off = worldgen.run(hostel_plan(), seed=1,
                                   room_assembler=False)
        cls.bl = next(b.layout for b in cls.on.buildings
                      if b.layout.design.name == "The Wayfarer's Rest")

    def test_the_one_wing_is_the_buildings_design(self):
        self.assertTrue(getattr(self.bl, "assembled", False),
                        self.on.fallbacks)
        self.assertIn("Common Room", names_of(self.bl),
                      "the P1 name survived onto the wing's matching room")
        self.assertEqual(self.bl.design.wealth, "wealthy")
        self.assertEqual(self.bl.design.kind, "hostelry")

    def test_the_switch_off_leaves_the_building_as_drawn(self):
        off_bl = next(b.layout for b in self.off.buildings
                      if b.layout.design.name == "The Wayfarer's Rest")
        self.assertFalse(getattr(off_bl, "assembled", False))


if __name__ == "__main__":
    unittest.main()
