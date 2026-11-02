"""Start cells for characters: a crowded room spills into a sibling room or the
nearest reachable floor, never a made-up spot outside the room it names.
Found by the first live 013 run: an inn's second keeper had no free cell in
the common room, fell back to the map centre with the room still named, and
the builder refused the whole world."""
import unittest

from worldgen import World, RegionOut, ObjectOut
from worldgen.model import ObjectTemplate, Rect
from worldgen import schedule


def _world(full_room=True):
    w = World()
    w.grid = (40, 40)
    w.templates = {"Crate": ObjectTemplate("Crate", (1, 1))}
    w.regions = [
        RegionOut("Village", Rect(0, 0, 40, 40), "zone"),
        RegionOut("Inn", Rect(10, 10, 9, 5), "building", parent="Village", wall="wood"),
        RegionOut("Inn Common Room", Rect(10, 10, 5, 5), "room", parent="Inn", wall="wood"),
        RegionOut("Inn Kitchen", Rect(14, 10, 5, 5), "room", parent="Inn", wall="wood"),
    ]
    w.regions_by_name = {r.name: r for r in w.regions}
    w.objects = []
    if full_room:   # every floor cell of the common room holds a crate
        w.objects = [ObjectOut("Crate", (x, y), "Inn Common Room")
                     for x in range(11, 14) for y in range(11, 14)]
    return w


class TestStartCell(unittest.TestCase):
    def test_free_room_keeps_its_region(self):
        w = _world(full_room=False)
        cell, region = schedule.start_cell(w, "Inn Common Room")
        self.assertEqual(region, "Inn Common Room")
        self.assertTrue(11 <= cell[0] <= 13 and 11 <= cell[1] <= 13)

    def test_full_room_spills_into_a_sibling_room(self):
        w = _world()
        cell, region = schedule.start_cell(w, "Inn Common Room")
        self.assertEqual(region, "Inn Kitchen")
        self.assertTrue(15 <= cell[0] <= 17 and 11 <= cell[1] <= 13)

    def test_no_sibling_room_falls_back_to_reachable_floor_with_its_region(self):
        w = _world()
        w.regions = [r for r in w.regions if r.name != "Inn Kitchen"]
        w.regions_by_name = {r.name: r for r in w.regions}
        connected = {(5, 5), (6, 5)}
        cell, region = schedule.start_cell(w, "Inn Common Room", connected=connected)
        self.assertIn(cell, connected)
        self.assertEqual(region, "Village")


class TestObjectsFiledElsewhere(unittest.TestCase):
    """A field's fence posts are filed under the field but stand on the
    farm's ground: a farmer starting in the farm never lands on one. Found
    by Ashvale at seed 2 once the map grew past 160 (brief 012h)."""

    def test_an_object_filed_under_another_region_still_blocks(self):
        w = _world(full_room=False)
        w.objects = [ObjectOut("Crate", (x, y), "North Field")
                     for x in range(0, 40) for y in range(0, 40) if (x, y) != (30, 30)]
        cell = schedule.free_cell(w, "Village")
        self.assertEqual(cell, (30, 30))


if __name__ == "__main__":
    unittest.main()
