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


class TestTheBarnsResidentsSleepInTheFarmhouse(unittest.TestCase):
    """rl-15 on the recipe path: a farm wing's residents are never dropped —
    they move to the compound's sleeping wing, noted, so the farmhouse ships
    their beds and the barn's rooms ship none."""

    @classmethod
    def setUpClass(cls):
        plan = farm_plan()
        plan["zones"][0]["buildings"][1]["residents"] = 3
        cls.world = worldgen.run(plan, seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "Millfield Compound")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def _rooms(self, name):
        from worldgen import assembler
        bl = part(self.comp, name)
        rooms = list(bl.rooms)
        for i in range(len(getattr(bl, "upper_asm", None) or [])):
            rooms.extend(assembler.upper_layout(bl, i, bl.rect).rooms)
        return rooms

    def test_the_counts_move_to_the_farmhouse(self):
        self.assertEqual(part(self.comp, "The Barn").design.residents, 0)
        self.assertEqual(part(self.comp, "Millfield Farmhouse").design.residents,
                         3)

    def test_the_barn_keeps_no_bed(self):
        beds = [(r.base_name, t) for r in self._rooms("The Barn")
                for (t, _p) in r.furniture.placements
                if self.world.templates[t].for_sleep]
        self.assertEqual(beds, [], "a bed in a farm wing")

    def test_the_farmhouse_sleeps_the_barns_residents(self):
        from worldgen.model import bed_capacity
        beds = sum(bed_capacity(self.world.templates[t])
                   for r in self._rooms("Millfield Farmhouse")
                   for (t, _p) in r.furniture.placements
                   if self.world.templates[t].for_sleep)
        self.assertGreaterEqual(beds, 3, "the moved residents, no beds")

    def test_the_move_is_noted(self):
        self.assertIn(("compound Millfield Compound",
                       "residents of The Barn sleep elsewhere: farm building"),
                      self.world.failures, self.world.failures)


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


def manor_plan():
    plan = skeleton("Ashford",
                    "A manor round its garden, the family's chambers to one "
                    "side, the kitchens and the servants to the other.")
    plan["zones"] = [{
        "name": "Manor Green", "kind": "village crossroads",
        "sizeClass": "large",
        "description": "The manor above the green.",
        "ground": "grass", "adjacentTo": [], "outdoor": [],
        "buildings": [
            zone_entry("Ashford Manor", "manor house", "medium",
                       "the hall", "wealthy"),
            zone_entry("The Family Wing", "lord's hall", "medium",
                       "the family's chambers", "wealthy"),
            zone_entry("The Old Hall", "great house", "medium",
                       "the kitchens and servants", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["Manor Green"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["compounds"] = [{
        "name": "Ashford Compound", "zone": "Manor Green",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "Ashford Manor", "at": "edge:south:center",
             "gate": True},
            {"building": "The Family Wing", "at": "edge:west:center"},
            {"building": "The Old Hall", "at": "edge:east:center"},
        ],
    }]
    plan["buildings"] = [
        building_spec("Ashford Manor", [("Great Hall", "large", "great_hall")]),
        building_spec("The Family Wing",
                      [("Lord's Chamber", "medium", "master_bedroom")]),
        building_spec("The Old Hall",
                      [("Servants' Hall", "medium", "kitchen")]),
    ]
    plan["roads"] = [{"from": "Manor Green", "to": "Emberford", "kind": "dirt"}]
    return plan


def castle_plan():
    plan = skeleton("Ironmoat",
                    "A castle round its yard, the keep rising at the back.")
    plan["zones"] = [{
        "name": "The Castle", "kind": "village crossroads",
        "sizeClass": "large",
        "description": "The castle.",
        "ground": "grass", "adjacentTo": [], "outdoor": [],
        "buildings": [
            zone_entry("Ironmoat Hall", "castle", "large",
                       "the hall", "wealthy"),
            zone_entry("The Keep", "keep", "medium", "the donjon", "wealthy"),
            zone_entry("Garrison Range", "garrison", "medium",
                       "the guard", "wealthy"),
            zone_entry("Stable Court", "stable", "medium",
                       "the stables", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["The Castle"], "outdoor": [],
        "buildings": [], "dressing": {"paths": "dirt", "props": [], "filler": []},
    }]
    plan["compounds"] = [{
        "name": "Ironmoat Hold", "zone": "The Castle",
        "shape": "enclosure", "courtyard": "large", "walls": "solid",
        "parts": [
            {"building": "Ironmoat Hall", "at": "edge:south:center",
             "gate": True},
            {"building": "The Keep", "at": "edge:north:center"},
            {"building": "Garrison Range", "at": "edge:east:center"},
            {"building": "Stable Court", "at": "edge:west:center"},
        ],
    }]
    plan["buildings"] = [
        building_spec("Ironmoat Hall", [("Great Hall", "large", "great_hall")]),
        building_spec("The Keep", [("Lord's Chamber", "medium", "master_bedroom")]),
        building_spec("Garrison Range", [("Guard Hall", "large", "barracks")]),
        building_spec("Stable Court", [("Stables", "large", "stable")]),
    ]
    plan["roads"] = [{"from": "The Castle", "to": "Emberford", "kind": "dirt"}]
    return plan


def village_plan():
    """One medieval village world carrying three compounds: the inn at the
    crossroads, a farmstead down the lane, the manor above the green — each
    under its own storey cap (rl-12)."""
    plan = skeleton("Threepenny",
                    "A village: an inn at the crossroads, a farmstead down "
                    "the lane, the manor above the green.")
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
        "name": "Hillfoot", "kind": "village", "sizeClass": "large",
        "description": "The farmstead.", "ground": "grass",
        "adjacentTo": ["Crossroads"], "outdoor": [],
        "buildings": [
            zone_entry("Millfield Farmhouse", "farmstead", "medium",
                       "the house itself", "wealthy"),
            zone_entry("The Barn", "barn", "medium", "part", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Manor Green", "kind": "village", "sizeClass": "large",
        "description": "The manor.", "ground": "grass",
        "adjacentTo": ["Hillfoot"], "outdoor": [],
        "buildings": [
            zone_entry("Ashford Manor", "manor house", "medium",
                       "the hall", "wealthy"),
            zone_entry("The Family Wing", "lord's hall", "medium",
                       "the family's chambers", "wealthy"),
            zone_entry("The Old Hall", "great house", "medium",
                       "the kitchens and servants", "wealthy"),
        ],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "Emberford", "kind": "hamlet", "sizeClass": "small",
        "description": "A few cottages.", "ground": "grass",
        "adjacentTo": ["Manor Green"], "outdoor": [],
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
    }, {
        "name": "Millfield Compound", "zone": "Hillfoot",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "Millfield Farmhouse", "at": "edge:south:center",
             "gate": True},
            {"building": "The Barn", "at": "edge:east:center"},
        ],
    }, {
        "name": "Ashford Compound", "zone": "Manor Green",
        "shape": "enclosure", "courtyard": "medium", "walls": "solid",
        "parts": [
            {"building": "Ashford Manor", "at": "edge:south:center",
             "gate": True},
            {"building": "The Family Wing", "at": "edge:west:center"},
            {"building": "The Old Hall", "at": "edge:east:center"},
        ],
    }]
    plan["buildings"] = [
        building_spec("The Gilded Stag",
                      [("Common Room", "large", "taproom"),
                       ("Inn Kitchen", "medium", "kitchen")]),
        building_spec("Stable Range", [("Stables", "large", "stable")]),
        building_spec("Guest Range", [("Guest Hall", "medium", "hallway")]),
        building_spec("Brew House", [("Brewhouse", "medium", "kitchen")]),
        building_spec("Millfield Farmhouse",
                      [("Farmhouse Hall", "medium", "living_room")]),
        building_spec("The Barn", [("Barn Room", "large", "barn")]),
        building_spec("Ashford Manor", [("Great Hall", "large", "great_hall")]),
        building_spec("The Family Wing",
                      [("Lord's Chamber", "medium", "master_bedroom")]),
        building_spec("The Old Hall",
                      [("Servants' Hall", "medium", "kitchen")]),
    ]
    plan["roads"] = [
        {"from": "Crossroads", "to": "Hillfoot", "kind": "dirt"},
        {"from": "Hillfoot", "to": "Manor Green", "kind": "dirt"},
        {"from": "Manor Green", "to": "Emberford", "kind": "dirt"},
    ]
    return plan


def rooms_of_part(comp, name):
    """Every room of one part, ground and upper storeys alike."""
    from worldgen import assembler
    bl = part(comp, name)
    rooms = list(bl.rooms)
    for i in range(len(getattr(bl, "upper_asm", None) or [])):
        rooms.extend(assembler.upper_layout(bl, i, bl.rect).rooms)
    return rooms


def assert_storey_opens_off_the_hub(test, bl, index, hub_required=True):
    """One upper storey of a compound part: every room is reached from the
    landing or corridor over the stairs (or, when the storey is one room
    over the whole outline, from the stair itself), through the storey's
    own door pairs."""
    from worldgen import assembler
    lay = assembler.upper_layout(bl, index, bl.rect)
    rooms = list(lay.rooms)
    hub = next((r for r in rooms if r.base_name in ("Landing", "Corridor")),
               None)
    if hub is None:
        test.assertFalse(hub_required,
                         "no landing or corridor over the stairs: "
                         f"{[r.base_name for r in rooms]!r}")
        test.assertIsNotNone(lay.stair_down_cell, "no stair down into the storey")
        start = next(r.base_name for r in rooms
                     if r.rect.contains_cell(lay.stair_down_cell))
    else:
        start = hub.base_name

    def owner(cell):
        return next((r.base_name for r in rooms
                     if r.rect.contains_cell(cell)), None)

    edges = {r.base_name: set() for r in rooms}
    for a, b in getattr(lay, "door_pairs", []) or []:
        oa, ob = owner(a), owner(b)
        if oa and ob and oa != ob:
            edges[oa].add(ob)
            edges[ob].add(oa)
    seen, queue = {start}, [start]
    while queue:
        for n in edges[queue.pop(0)]:
            if n not in seen:
                seen.add(n)
                queue.append(n)
    test.assertEqual(seen, {r.base_name for r in rooms},
                     sorted((r.base_name, sorted(edges[r.base_name]))
                            for r in rooms))


class TestTheManorsWingsFurnishApartInWealth(unittest.TestCase):
    """rl-12: the wing's design-8.3 offset reaches the tier, the clearance
    and the furniture — the lord's family a tier above the hall, the
    servants' wing two below it, and their rooms measurably not the hall's."""

    @classmethod
    def setUpClass(cls):
        plan = copy.deepcopy(manor_plan())
        plan["zones"][0]["buildings"][0]["residents"] = 4
        plan["zones"][0]["buildings"][0]["couples"] = 1
        plan["zones"][0]["buildings"][2]["residents"] = 4
        cls.world = worldgen.run(plan, seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "Ashford Compound")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def test_the_three_wings_furnish_three_tiers(self):
        self.assertEqual(part(self.comp, "Ashford Manor").design.wealth,
                         "wealthy")
        self.assertEqual(part(self.comp, "The Family Wing").design.wealth,
                         "elite")
        self.assertEqual(part(self.comp, "The Old Hall").design.wealth,
                         "poor")

    def test_the_servants_wing_differs_from_the_hall_in_furniture(self):
        def templates_of(name):
            return {t for r in part(self.comp, name).rooms
                    for (t, _p) in r.furniture.placements}
        hall = templates_of("Ashford Manor")
        service = templates_of("The Old Hall")
        self.assertTrue(hall, "the hall wing furnished nothing")
        self.assertTrue(service, "the service wing furnished nothing")
        self.assertNotEqual(hall, service)
        self.assertTrue(hall - service, "the hall owns no template of its own")
        self.assertTrue(service - hall,
                        "the service wing owns no template of its own")

    def test_the_offset_reaches_the_clearance(self):
        from worldgen import assembler, library as L, model
        lib = L.load(L.LIB_DIR)
        plan = copy.deepcopy(manor_plan())
        plan["zones"][0]["buildings"][0]["residents"] = 4
        plan["zones"][0]["buildings"][0]["couples"] = 1
        plan["zones"][0]["buildings"][2]["residents"] = 4
        parsed = model.parse_plan(plan)
        ctx = assembler.activate(parsed, plan, "s", {})
        self.addCleanup(assembler.deactivate)
        by_name = {d.name: d for d in parsed.zones[0].buildings}
        hall = library_plan.wing_design(
            lib, lib.wings["manor.hall"], "Ashford Manor",
            by_name["Ashford Manor"], "medieval", 2, "manor house")
        service = library_plan.wing_design(
            lib, lib.wings["manor.service"], "The Old Hall",
            by_name["The Old Hall"], "medieval", 2, "manor house")
        self.assertEqual(assembler.clearance_of(ctx, hall, "great_hall"),
                         "grand")
        self.assertEqual(assembler.clearance_of(ctx, service, "kitchen"),
                         "roomy")
        self.assertEqual(assembler.clearance_of(ctx, service, "bedroom"),
                         "tight")

    def test_the_household_and_staff_split_over_their_wings(self):
        family = part(self.comp, "The Family Wing")
        service = part(self.comp, "The Old Hall")
        self.assertEqual(part(self.comp, "Ashford Manor").design.residents, 0)
        self.assertEqual((family.design.residents, family.design.couples),
                         (4, 1))
        self.assertEqual(service.design.residents, 4)
        self.assertIn(("compound Ashford Compound",
                       "sleepers: The Family Wing 4 residents, 1 couple, "
                       "The Old Hall 4 staff"),
                      self.world.failures, self.world.failures)

    def test_both_sleeping_wings_ship_their_beds(self):
        from worldgen.model import bed_capacity
        for name, least in (("The Family Wing", 4), ("The Old Hall", 4)):
            beds = sum(bed_capacity(self.world.templates[t])
                       for r in rooms_of_part(self.comp, name)
                       for (t, _p) in r.furniture.placements
                       if self.world.templates[t].for_sleep)
            self.assertGreaterEqual(beds, least, name)

    def test_the_checks_stay_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))


class TestTheKeepRisesFourStoreys(unittest.TestCase):
    """rl-12: the assembler lays four storeys of wing — the castle's keep
    rises to its recipe's four under the height rules' castle cap, every
    upper storey reached from its stair, and the lord's chamber a tier above
    the hall below it."""

    @classmethod
    def setUpClass(cls):
        plan = copy.deepcopy(castle_plan())
        plan["zones"][0]["buildings"][1]["residents"] = 3
        plan["zones"][0]["buildings"][1]["couples"] = 1
        plan["zones"][0]["buildings"][2]["residents"] = 6
        cls.world = worldgen.run(plan, seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "Ironmoat Hold")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def test_the_keep_rises_to_four_storeys(self):
        bl = part(self.comp, "The Keep")
        self.assertEqual(bl.design.storeys, 4)
        self.assertEqual(len(getattr(bl, "upper_asm", None) or []), 3,
                         "the assembler did not lay every upper storey")
        for i in range(3):
            assert_storey_opens_off_the_hub(self, bl, i, hub_required=False)

    def test_the_keeps_wealth_steps_up_from_the_hall(self):
        self.assertEqual(part(self.comp, "Ironmoat Hall").design.wealth,
                         "wealthy")
        self.assertEqual(part(self.comp, "The Keep").design.wealth, "elite")

    def test_the_garrison_keeps_its_own_residents(self):
        self.assertEqual(part(self.comp, "Garrison Range").design.residents, 6)
        self.assertEqual(part(self.comp, "The Keep").design.residents, 3)
        self.assertIn(("compound Ironmoat Hold",
                       "sleepers: The Keep 3 residents, 1 couple, "
                       "Garrison Range 6 residents"),
                      self.world.failures, self.world.failures)

    def test_the_checks_stay_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))


class TestTheInnsSleepersSplitByRole(unittest.TestCase):
    """rl-12: the compound's sleeper budget over its wings by role — the
    inn's traveller beds in the Rooms wing upstairs, the stablehands over
    the stables, the keepers by the guests' landing — one line noting the
    split, the beds totalling what the inn promised, and none where no one
    sleeps."""

    @classmethod
    def setUpClass(cls):
        plan = copy.deepcopy(inn_plan())
        plan["zones"][0]["buildings"][0]["units"] = {"name": "Guest room",
                                                     "count": 4}
        plan["zones"][0]["buildings"][1]["residents"] = 2
        plan["zones"][0]["buildings"][2]["residents"] = 2
        plan["zones"][0]["buildings"][2]["couples"] = 1
        cls.world = worldgen.run(plan, seed=1, room_assembler=True)
        cls.comp = compound_of(cls.world, "The Gilded Stag Inn")
        cls.assertIsNotNone(cls, cls.comp, cls.world.failures)

    def test_each_role_sleeps_in_its_own_wing(self):
        guest = part(self.comp, "Guest Range")
        stable = part(self.comp, "Stable Range")
        front = part(self.comp, "The Gilded Stag")
        self.assertEqual((guest.design.guests, guest.design.residents,
                          guest.design.couples), (4, 2, 1))
        self.assertEqual(stable.design.residents, 2)
        self.assertEqual((front.design.residents, front.design.couples,
                          front.design.guests), (0, 0, 0))

    def test_the_split_is_noted(self):
        self.assertIn(("compound The Gilded Stag Inn",
                       "sleepers: Stable Range 2 staff, Guest Range "
                       "4 guests, 2 residents, 1 couple"),
                      self.world.failures, self.world.failures)

    def test_the_beds_total_what_the_inn_promised(self):
        from worldgen.model import bed_capacity
        beds = sum(bed_capacity(self.world.templates[t])
                   for name in ("The Gilded Stag", "Stable Range",
                                "Guest Range")
                   for r in rooms_of_part(self.comp, name)
                   for (t, _p) in r.furniture.placements
                   if self.world.templates[t].for_sleep)
        self.assertEqual(beds, 8,
                         "2 keepers, 4 guests and 2 stablehands, no more")

    def test_no_bed_where_nobody_sleeps(self):
        front = [(r.base_name, t)
                 for r in rooms_of_part(self.comp, "The Gilded Stag")
                 for (t, _p) in r.furniture.placements
                 if self.world.templates[t].for_sleep]
        stable_ground = [(r.base_name, t)
                         for r in part(self.comp, "Stable Range").rooms
                         for (t, _p) in r.furniture.placements
                         if self.world.templates[t].for_sleep]
        self.assertEqual(front, [], "a bed in the taproom wing")
        self.assertEqual(stable_ground, [], "a bed on the stables' ground")

    def test_the_rooms_wing_sleeps_upstairs_off_the_landing(self):
        guest = part(self.comp, "Guest Range")
        self.assertEqual(guest.design.storeys, 2)
        assert_storey_opens_off_the_hub(self, guest, 0)
        ground = {r.base_name for r in guest.rooms}
        every = {r.base_name for r in rooms_of_part(self.comp, "Guest Range")}
        self.assertTrue({"Guest chamber", "Best chamber"} <= every, sorted(every))
        self.assertFalse({"Guest chamber", "Best chamber"} & ground,
                         "the guest chambers sleep on the ground")

    def test_the_checks_stay_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))


class TestAVillageWorldCapsEveryWing(unittest.TestCase):
    """rl-12: wings follow the height rules — a medieval village world whose
    compounds rise only as far as each building's cap, the farmstead's barn
    and hayloft held to the village's one storey while the inn and manor
    wings take their two."""

    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(village_plan(), seed=1, room_assembler=True)

    def test_every_wing_sits_within_its_building_cap(self):
        from worldgen import phases
        from worldgen.model import settlement_size
        kinds = {z["name"]: z["kind"] for z in village_plan()["zones"]}
        for comp in self.world.compounds:
            mid = (comp.rect.x + comp.rect.w // 2, comp.rect.y + comp.rect.h // 2)
            zone = next((n for n, r in self.world.zones_by_name.items()
                         if r.x <= mid[0] < r.x + r.w
                         and r.y <= mid[1] < r.y + r.h), "")
            zone_kind = kinds.get(zone, "village")
            gates = [p.layout.design.kind for p in comp.parts
                     if getattr(p, "gate", False)] or \
                [p.layout.design.kind for p in comp.parts]
            cap = phases._storey_cap("medieval", gates[0],
                                     settlement_size(zone_kind))
            for p in comp.parts:
                self.assertLessEqual(p.layout.design.storeys, cap,
                                     (comp.name, p.layout.design.name, cap))

    def test_the_storeys_land_where_the_rules_say(self):
        want = {
            ("The Gilded Stag Inn", "The Gilded Stag"): 1,
            ("The Gilded Stag Inn", "Stable Range"): 2,
            ("The Gilded Stag Inn", "Guest Range"): 2,
            ("Millfield Compound", "Millfield Farmhouse"): 1,
            ("Millfield Compound", "The Barn"): 1,
            ("Ashford Compound", "Ashford Manor"): 1,
            ("Ashford Compound", "The Family Wing"): 2,
            ("Ashford Compound", "The Old Hall"): 2,
        }
        for (comp_name, part_name), storeys in want.items():
            comp = compound_of(self.world, comp_name)
            self.assertIsNotNone(comp, comp_name)
            self.assertEqual(part(comp, part_name).design.storeys, storeys,
                             (comp_name, part_name))

    def test_the_checks_stay_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [], m.get("regions"))
        self.assertEqual(m["object_overlaps"], [], m.get("objects"))
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))


if __name__ == "__main__":
    unittest.main()
