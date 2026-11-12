"""Review fixes on top of the populations: rats match a region's own name, not
its building's (a shop called "Harrow's Store" is no storeroom, and its
bedrooms are not either), nest once per building and in at most RAT_HOMES
places, and a here-and-now town's watch is the police."""
import unittest

import worldgen
from worldgen import populations
from worldgen.model import Rect, Zone
from tests.test_populations import _patrol_world, _plan, _world


def _room(name, rect, parent, kind="room"):
    return worldgen.RegionOut(name, rect, kind, parent=parent, wall="wood")


def _rats(pops):
    return next((p["homes"] for p in pops if p["name"] == "Rats"), [])


class TestRatsByOwnName(unittest.TestCase):

    def test_a_shop_called_store_and_its_rooms_get_no_rats(self):
        ground = worldgen.RegionOut("Weffling", Rect(0, 0, 40, 40), "zone")
        shop = _room("Harrow's Store", Rect(4, 4, 12, 12), "Weffling",
                     kind="building")
        floor = _room("Harrow's Store Shop Floor", Rect(4, 4, 8, 12),
                      "Harrow's Store")
        bed = _room("Harrow's Store Master Bedroom", Rect(12, 4, 4, 6),
                    "Harrow's Store")
        world = _world(ground, shop, floor, bed)
        self.assertEqual(_rats(populations.choose(
            world, _plan(Zone(name="Weffling", kind="village")))), [])

    def test_a_shops_own_store_room_does_get_rats(self):
        ground = worldgen.RegionOut("Weffling", Rect(0, 0, 40, 40), "zone")
        shop = _room("Harrow's Store", Rect(4, 4, 12, 12), "Weffling",
                     kind="building")
        store = _room("Harrow's Store Store Room", Rect(4, 4, 6, 6),
                      "Harrow's Store")
        world = _world(ground, shop, store)
        homes = _rats(populations.choose(
            world, _plan(Zone(name="Weffling", kind="village"))))
        self.assertEqual([h["region"] for h in homes],
                         ["Harrow's Store Store Room"])

    def test_one_nest_per_building_and_at_most_rat_homes_in_all(self):
        regions = [worldgen.RegionOut("Weffling", Rect(0, 0, 60, 60), "zone")]
        granary = _room("Granary", Rect(2, 2, 10, 10), "Weffling",
                        kind="building")
        regions += [granary,
                    _room("Granary Grain Floor", Rect(2, 2, 5, 10), "Granary"),
                    _room("Granary Seed Store", Rect(7, 2, 5, 10), "Granary")]
        for i in range(5):
            regions.append(_room(f"Cottage {i} Cellar", Rect(20 + i * 6, 30, 5, 5),
                                 "Weffling"))
        world = _world(*regions, grid=(60, 60))
        homes = _rats(populations.choose(
            world, _plan(Zone(name="Weffling", kind="village"))))
        names = [h["region"] for h in homes]
        self.assertEqual(len(names), populations.RAT_HOMES)
        self.assertEqual(sum(1 for n in names if n.startswith("Granary")), 1,
                         "the granary nests once, not in every room of it")


class TestModernWatch(unittest.TestCase):

    def test_a_modern_town_watch_is_the_police(self):
        world, plan = _patrol_world()
        plan.setting["band"] = "modern"
        watch = next(p for p in populations.choose(world, plan)
                     if p["name"] == "Town watch")
        self.assertIn(watch["animationId"], ("police-man", "police-woman"))

    def test_a_medieval_town_watch_is_the_town_guard(self):
        world, plan = _patrol_world()
        plan.setting["band"] = "medieval"
        watch = next(p for p in populations.choose(world, plan)
                     if p["name"] == "Town watch")
        self.assertIn(watch["animationId"], ("town-guard-man", "town-guard-woman"))


if __name__ == "__main__":
    unittest.main()
