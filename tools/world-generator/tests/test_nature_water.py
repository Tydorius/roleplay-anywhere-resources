"""Anywhere RPG 1.0 natural shapes, water and vehicles on a generated world:
greens and fields big enough ship with shape "natural" unless something the
generator placed sits within 2 cells of a corner (the blob may leave no
ground there — the shape drops, with a note), water regions ship with
surface "water" (shallow water is waded, deep water blocks and nothing
placed may stand on it), and carts, wagons and bikes ship as vehicles with
takingIsTheft — boats only on or beside water, and a boat high and dry is
scenery."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api, native
from worldgen.model import ObjectTemplate, Rect
from worldgen import spec_writer
from worldgen.vendor import scenario_checks
from tests.test_locks_theft import WATCH_HOUSE_PLAN
from tests.test_sleep import CATALOGUE, _tmpl
from tests.util import load_plan


def _world(*regions, grid=(24, 12)):
    """A bare world of just regions, for the classifier and the flood."""
    w = worldgen.World()
    w.grid = grid
    for r in regions:
        w.regions.append(r)
        w.regions_by_name[r.name] = r
    return w


def _template(name, w=1, h=1):
    return ObjectTemplate(name=name, size=(w, h), walkability=0.0,
                          description=f"A {name.lower()}.",
                          physicalDescription=f"a {name.lower()}",
                          tags=["prop"], rule="place anywhere free")


class TestNaturalShapes(unittest.TestCase):
    """Which regions ship with shape "natural"."""

    def test_an_8x8_green_is_natural(self):
        green = worldgen.RegionOut("Weffling Green", Rect(2, 2, 8, 8), "square")
        self.assertEqual(native.natural_regions(_world(green)),
                         ["Weffling Green"])

    def test_a_4x10_green_is_not(self):
        strip = worldgen.RegionOut("Weffling Green", Rect(0, 0, 10, 4), "square")
        self.assertEqual(native.natural_regions(_world(strip)), [],
                         "the game keeps the rectangle below 5 on a side")

    def test_a_walled_garden_is_not(self):
        garden = worldgen.RegionOut("Herb Garden", Rect(0, 0, 6, 6), "square",
                                    wall="stone")
        self.assertEqual(native.natural_regions(_world(garden)), [])

    def test_a_road_is_not(self):
        road = worldgen.RegionOut("Green Road", Rect(0, 0, 9, 6), "road")
        self.assertEqual(native.natural_regions(_world(road)), [])

    def test_a_zone_of_woodland_is_natural_but_a_village_is_not(self):
        zone = worldgen.RegionOut("Weffling", Rect(0, 0, 7, 7), "zone")
        kinds = {"Weffling": "woodland"}
        self.assertEqual(native.natural_regions(_world(zone), kinds),
                         ["Weffling"])
        self.assertEqual(native.natural_regions(
            _world(zone), {"Weffling": "village"}), [])

    def test_the_corner_danger_zone_is_two_cells_off_each_corner(self):
        cells = native.corner_cells(Rect(0, 0, 8, 8))
        self.assertIn((0, 0), cells)
        self.assertIn((2, 2), cells)
        self.assertNotIn((3, 3), cells)
        self.assertNotIn((4, 4), cells, "the middle of the green is safe")
        self.assertNotIn((5, 4), cells)


class TestWater(unittest.TestCase):
    """Water surfaces, depth and what deep water blocks."""

    def test_a_2_wide_stream_is_shallow_and_walkable(self):
        meadow = worldgen.RegionOut("Meadow", Rect(0, 0, 24, 12), "zone")
        stream = worldgen.RegionOut("Mill Stream", Rect(10, 0, 2, 12), "zone")
        world = _world(meadow, stream)
        water = native.water_regions(world)
        self.assertEqual(water, {"Mill Stream": "shallow"})
        self.assertEqual(native.deep_cells(world, water), set())
        blocked, _doors = worldgen.checks.walkability_grid(
            world, worldgen.checks.compute_openings(world))
        from worldgen import checks
        reach = checks.flood(world, [(2, 2)], blocked)
        self.assertIn((21, 2), reach,
                      "a stream two cells wide is waded, not blocked")

    def test_a_6x6_pond_is_deep_and_blocks(self):
        meadow = worldgen.RegionOut("Meadow", Rect(0, 0, 24, 12), "zone")
        pond = worldgen.RegionOut("Duck Pond", Rect(9, 3, 6, 6), "zone")
        world = _world(meadow, pond)
        water = native.water_regions(world)
        self.assertEqual(water, {"Duck Pond": "deep"})
        self.assertEqual(native.deep_cells(world, water), pond.rect.cells())
        blocked, _doors = worldgen.checks.walkability_grid(
            world, worldgen.checks.compute_openings(world))
        from worldgen import checks
        reach = checks.flood(world, [(2, 2)], blocked)
        self.assertNotIn((12, 6), reach, "nobody stands on the pond")
        self.assertIn((8, 6), reach, "its bank stays walkable")

    def test_a_road_is_never_water_and_a_bridge_stays_dry(self):
        road = worldgen.RegionOut("Mill Stream Road", Rect(0, 0, 24, 3), "road")
        world = _world(road)
        self.assertEqual(native.water_regions(world), {})
        river = worldgen.RegionOut("Mill Stream", Rect(0, 0, 24, 3), "zone")
        bridge = worldgen.RegionOut("Causeway", Rect(10, 1, 4, 1), "path")
        world = _world(river, bridge)
        wet = native.wet_cells(world, native.water_regions(world))
        self.assertEqual(wet["Mill Stream"],
                         river.rect.cells() - bridge.rect.cells(),
                         "a region without a surface that sits in the water "
                         "is dry ground — a bridge, a jetty")

    def test_a_pond_that_cuts_the_map_loses_its_surface(self):
        meadow = worldgen.RegionOut("Meadow", Rect(0, 0, 24, 12), "zone")
        band = worldgen.RegionOut("Mill Pool", Rect(9, 0, 6, 12), "zone")
        hut = worldgen.RegionOut("Mill Hut", Rect(18, 4, 4, 4), "room",
                                 wall="wood", doors={(20, 4)})
        world = _world(meadow, band, hut)
        world.reserved = {(2, 2)}
        self.assertEqual(native.final_water(world), {},
                         "the only way west to east runs over the pool, so "
                         "it ships without its surface")
        self.assertEqual(native.water_drops(world), ["Mill Pool"])

    def test_a_prop_on_a_deep_pond_moves_to_dry_ground(self):
        meadow = worldgen.RegionOut("Meadow", Rect(0, 0, 24, 12), "zone")
        pond = worldgen.RegionOut("Duck Pond", Rect(9, 3, 6, 6), "zone")
        world = _world(meadow, pond)
        world.templates["Market Stall"] = _template("Market Stall")
        stall = worldgen.ObjectOut("Market Stall", (12, 6), "Meadow")
        world.objects.append(stall)
        spec_writer._clear_deep_water(world, native.water_regions(world), {})
        self.assertNotIn(tuple(stall.pos), pond.rect.cells(),
                         "the stall moves off the pond")
        self.assertIn(tuple(stall.pos), meadow.rect.cells())
        self.assertEqual(len(world.failures), 0)

    def test_a_prop_with_nowhere_dry_to_go_is_dropped_and_noted(self):
        pond = worldgen.RegionOut("Duck Pond", Rect(9, 3, 6, 6), "zone")
        world = _world(pond)
        world.templates["Market Stall"] = _template("Market Stall")
        stall = worldgen.ObjectOut("Market Stall", (12, 6), "Duck Pond")
        world.objects.append(stall)
        spec_writer._clear_deep_water(world, native.water_regions(world), {})
        self.assertEqual(world.objects, [],
                         "nothing placed stands on deep water")
        self.assertIn(("Market Stall at [12, 6]",
                       "dropped: it stands on deep water and no dry cell "
                       "near it is free"),
                      world.failures)


def _nature_plan(templates=None, with_pond=False, cart_home=False):
    """The watch-house village, plus the vehicle templates and a mill pond."""
    data = json.loads(json.dumps(WATCH_HOUSE_PLAN))
    data["templates"] = (templates if templates is not None
                         else CATALOGUE + [
                             _tmpl("Market Cart", 2, 1, ["cart", "storage"]),
                             _tmpl("Bicycle", 1, 2, ["cart"]),
                             _tmpl("Rowboat", 1, 2, ["boat"]),
                             _tmpl("Oak Bench", 2, 1, ["seat"])])
    if cart_home:
        for g in data["buildings"]:
            if g["name"] == "The Green Ox":
                g["furniture"].append({"template": "Market Cart",
                                       "room": "Common Room", "count": 1})
    if with_pond:
        data["zones"].append({
            "name": "Mill Pond", "kind": "pond", "sizeClass": "small",
            "description": "The mill pond.", "ground": "dirt",
            "adjacentTo": ["Weffling"], "outdoor": [], "buildings": [],
            "dressing": {"paths": "dirt",
                         "props": [{"template": "Rowboat", "count": 1}],
                         "filler": []},
        })
        data["roads"] = [{"from": "Weffling", "to": "Mill Pond"}]
    return data


class TestNatureSpec(unittest.TestCase):
    """What the spec carries, at spec level."""

    def _spec(self, data):
        world = worldgen.run(data, seed=1)
        return world, worldgen.build_spec(world, data)

    def test_carts_wagons_and_bikes_drive_and_are_theft(self):
        _world_, spec = self._spec(_nature_plan())
        self.assertEqual(spec["nativeNature"]["vehicles"], {
            "Market Cart": {"vehicle": "drive", "takingIsTheft": True},
            "Bicycle": {"vehicle": "drive", "sheet": "bicycle",
                        "takingIsTheft": True},
        })

    def test_a_boat_far_from_water_is_scenery(self):
        _world_, spec = self._spec(_nature_plan())
        self.assertNotIn("Rowboat", spec["nativeNature"]["vehicles"])
        self.assertNotIn("Oak Bench", spec["nativeNature"]["vehicles"])

    def test_the_players_own_cart_is_not_theft(self):
        _world_, spec = self._spec(_nature_plan(cart_home=True))
        self.assertEqual(spec["nativeNature"]["vehicles"]["Market Cart"],
                         {"vehicle": "drive"},
                         "the cart stands in the player's own inn")

    def test_the_pond_ships_water_and_carries_the_boat(self):
        _world_, spec = self._spec(_nature_plan(with_pond=True))
        nature = spec["nativeNature"]
        self.assertIn("Mill Pond", nature["water"])
        self.assertEqual(nature["vehicles"]["Rowboat"],
                         {"vehicle": "drive", "takingIsTheft": True})

    def test_the_water_reaches_the_metrics(self):
        world, _spec_ = self._spec(_nature_plan(with_pond=True))
        regions = world.metrics["water"]["regions"]
        pond = next(r for r in regions if r["name"] == "Mill Pond")
        self.assertIn(pond["depth"], ("deep", "shallow"))
        self.assertIn(pond["draw"], ("river", "pool"))


class TestFixtureWorldNature(unittest.TestCase):
    """medieval-glm-plan.json built end to end: the build stays clean, every
    natural shape and water surface lands unwalled, no vehicle fields go
    missing, and the vendored 1.0 checker reports nothing against the
    shipped world."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-nature-water-")
        cls.data = load_plan("medieval-glm-plan.json")
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

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_the_summary_lists_the_nature(self):
        nature = self.summary["nature"]
        self.assertIn("natural_regions", nature)
        self.assertIn("water_regions", nature)
        self.assertIn("vehicles", nature)
        for key in ("water_deep", "water_shallow", "water_rivers",
                    "water_pools"):
            self.assertIsInstance(nature[key], int)

    def test_shapes_and_surfaces_land_unwalled(self):
        nature = self.spec["nativeNature"]
        by_name = {r.get("name"): r for r in self.scn["regions"]}
        for name in nature["shape"]:
            area = by_name[name]
            self.assertFalse(area.get("wall"))
            self.assertIn(area.get("shape"), ("natural", "organic"))
            w, h = area.get("size", [0, 0])
            self.assertGreaterEqual(min(w, h), 5)
        for name in nature["water"]:
            area = by_name[name]
            self.assertFalse(area.get("wall"))
            self.assertEqual(area.get("surface"), "water")

    def test_nothing_placed_sits_on_a_natural_regions_corner(self):
        tpl = {t.get("id"): t for t in self.scn["objectTemplates"]}
        for area in self.scn["regions"]:
            if area.get("shape") not in ("natural", "organic"):
                continue
            x, y = area.get("position", (0, 0))
            w, h = area.get("size", (0, 0))
            danger = native.corner_cells(Rect(x, y, w, h))
            for e in self.scn["entities"]:
                if e.get("type") == "object":
                    hit = set(scenario_checks.footprint(e, tpl)) & danger
                    self.assertFalse(
                        hit, f"{e.get('name')!r} sits on {sorted(hit)} at "
                             f"the corner of {area.get('name')!r}")
                else:
                    self.assertNotIn(
                        tuple(e.get("pos") or ()), danger,
                        f"{e.get('name')!r} starts at the corner of "
                        f"{area.get('name')!r}")

    def test_nobody_stands_on_deep_water(self):
        tpl = {t.get("id"): t for t in self.scn["objectTemplates"]}
        wet = scenario_checks.liquid_cells(self.scn, self.scn["regions"])
        if not wet:
            return
        for e in self.scn["entities"]:
            if e.get("type") == "object":
                t = tpl.get(e.get("templateId")) or {}
                if t.get("vehicle"):
                    continue
                self.assertFalse(
                    set(scenario_checks.footprint(e, tpl)) & wet,
                    f"{e.get('name')!r} stands on deep water")
            else:
                self.assertNotIn(tuple(e.get("pos") or ()), wet,
                                 f"{e.get('name')!r} starts on deep water")

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)

    def test_the_shipped_scenario_mods_check_is_clean(self):
        from worldgen import checks as checks_mod
        self.assertEqual(checks_mod.check_scenario_mods(self.path, self.spec),
                         [])


class TestPondWorldNature(unittest.TestCase):
    """The watch-house village with a mill pond built end to end: the pond
    ships with both its natural shape and its water surface, the rowboat is
    a vehicle, and the vendored 1.0 checker reports nothing against a world
    that carries all three."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-pond-")
        cls.data = _nature_plan(with_pond=True)
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

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_the_pond_ships_its_shape_and_surface(self):
        pond = self._region("Mill Pond")
        self.assertFalse(pond.get("wall"))
        self.assertEqual(pond.get("surface"), "water")
        self.assertIn(pond.get("shape"), ("natural", "organic"))

    def test_the_boat_and_the_cart_ship_as_vehicles(self):
        tpl = {t.get("name"): t for t in self.scn["objectTemplates"]}
        self.assertEqual(tpl["Rowboat"].get("vehicle"), "drive")
        self.assertTrue(tpl["Rowboat"].get("takingIsTheft"))
        self.assertEqual(tpl["Market Cart"].get("vehicle"), "drive")

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
