"""Review fix: a stair goes on a cell someone coming through the room's door
can walk to. In a model-test world (Dots 3's "Mill Hospital", the plan in
tests/data) the nurses' home's upper corridor is one cell wide, a lamp stands
across it, and the stair landed in the dead-end tail beyond the lamp, so the
upper Lobby and Common Room could not be reached from the stairs."""
import json
import os
import unittest

import worldgen
from worldgen.extensions import floors
from worldgen.model import Rect

DATA = os.path.join(os.path.dirname(__file__), "data", "mill-hospital-dots.plan.json")


class TestMillHospitalStairs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as f:
            cls.world = worldgen.run(json.load(f), seed=1)

    def test_every_upper_room_is_reachable_from_the_stairs(self):
        self.assertEqual(self.world.metrics["floors"]["issues"], [])

    def test_every_room_is_reachable(self):
        rooms = self.world.metrics["rooms"]
        self.assertEqual(rooms["reachable"], rooms["total"], rooms["unreachable"])


class _Furniture:
    def __init__(self, placements):
        self.placements = placements
        self.reserved = []

    def size_of(self, name, pos, templates):
        return templates[name].size


class _Room:
    def __init__(self, rect, doors, placements):
        self.rect, self.doors = rect, set(doors)
        self.furniture = _Furniture(placements)


class _Tmpl:
    def __init__(self, size, walkability):
        self.size, self.walkability = size, walkability


class _World:
    templates = {"Lamp": _Tmpl((1, 1), 0.0), "Rug": _Tmpl((1, 1), 1.0)}


class TestDoorReachable(unittest.TestCase):
    """A one-cell corridor (interior x=1, y=1..8) with its door at the north
    end (1, 9)."""

    def test_a_lamp_across_the_corridor_cuts_off_its_tail(self):
        room = _Room(Rect(0, 0, 3, 10), [(1, 9)], [("Lamp", (1, 3))])
        cells = floors._door_reachable(_World, room)
        self.assertIn((1, 8), cells)
        self.assertIn((1, 4), cells)
        self.assertNotIn((1, 2), cells, "beyond the lamp, boxed in")
        self.assertNotIn((1, 3), cells, "the lamp's own cell")

    def test_walkable_furniture_does_not_cut_it(self):
        room = _Room(Rect(0, 0, 3, 10), [(1, 9)], [("Rug", (1, 3))])
        self.assertIn((1, 1), floors._door_reachable(_World, room))

    def test_the_free_stair_cells_skip_the_tail(self):
        room = _Room(Rect(0, 0, 3, 10), [(1, 9)], [("Lamp", (1, 3))])
        free = floors._free_stair_cells(_World, [room], relax=True)
        self.assertFalse(free & {(1, 1), (1, 2)})
        self.assertIn((1, 5), free)


if __name__ == "__main__":
    unittest.main()
