"""Review fixes on top of the nature pass: every water lookup sees the zone
kinds the world carries, whichever runs first (the checks run before the
spec is written and must not leave a stale, kind-less answer behind), and a
vehicle word beside a part or fixture names no vehicle."""
import unittest

import worldgen
from worldgen import native
from worldgen.model import Rect


def _world(*regions, grid=(24, 12)):
    w = worldgen.World()
    w.grid = grid
    for r in regions:
        w.regions.append(r)
        w.regions_by_name[r.name] = r
    return w


class TestZoneKindWater(unittest.TestCase):

    def _river_zone_world(self):
        meadow = worldgen.RegionOut("Meadow", Rect(0, 0, 24, 12), "zone")
        # no water word in its name: it is water only by its zone's kind
        race = worldgen.RegionOut("Millrace", Rect(10, 0, 2, 12), "zone")
        world = _world(meadow, race)
        world.reserved = {(2, 2)}
        world.zone_kinds = {"Meadow": "meadow", "Millrace": "river"}
        return world

    def test_a_river_zone_is_water_with_no_kinds_passed(self):
        world = self._river_zone_world()
        self.assertEqual(native.final_water(world), {"Millrace": "shallow"})

    def test_the_checks_running_first_leave_no_stale_answer(self):
        world = self._river_zone_world()
        native.final_water(world, refresh=True)        # as run_checks does
        kinds = {"Meadow": "meadow", "Millrace": "river"}
        self.assertEqual(native.final_water(world, kinds),
                         {"Millrace": "shallow"},
                         "the spec writer's lookup sees the river zone")

    def test_a_lookup_with_other_kinds_is_not_served_from_the_cache(self):
        world = self._river_zone_world()
        native.final_water(world)
        self.assertEqual(native.final_water(world, {"Millrace": "village"}), {})


class TestVehicleWords(unittest.TestCase):

    def test_parts_and_fixtures_are_not_vehicles(self):
        for name in ("Bike rack", "Bicycle rack", "Wagon wheel", "Carriage clock",
                     "Car park sign", "Cart shed", "Toy cart", "Model boat"):
            self.assertEqual(native.vehicle_fields(name), {}, name)
        for name in ("Boat hook", "Rowboat oars", "Model boat"):
            self.assertFalse(native.is_boat(name), name)

    def test_real_vehicles_still_are(self):
        self.assertEqual(native.vehicle_fields("Hay cart")["vehicle"], "drive")
        self.assertEqual(native.vehicle_fields("Bicycle")["sheet"], "bicycle")
        self.assertTrue(native.is_boat("Rowboat"))


if __name__ == "__main__":
    unittest.main()
