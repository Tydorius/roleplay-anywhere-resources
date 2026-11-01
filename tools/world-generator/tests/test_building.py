import json
import os
import random
import unittest

from worldgen.layout_building import layout_building
from worldgen.model import parse_plan, shared_wall_cells

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "village.json")


def load_plan():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return parse_plan(json.load(f))


class TestBuildingLayout(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()
        self.designs = {b.name: b for z in self.plan.zones for b in z.buildings}

    def layout(self, name):
        return layout_building(self.designs[name], (100, 100), random.Random(3))

    def test_rooms_partition_the_footprint(self):
        for name in self.designs:
            b = self.layout(name)
            total = sum(r.rect.w * r.rect.h for r in b.rooms)
            self.assertEqual(total, b.rect.w * b.rect.h, f"{name}: rooms do not cover the footprint")
            for i, ra in enumerate(b.rooms):
                self.assertTrue(b.rect.contains_rect(ra.rect), f"{name}: {ra.base_name} escapes the building")
                for rb in b.rooms[i + 1:]:
                    self.assertFalse(ra.rect.intersects(rb.rect),
                                     f"{name}: {ra.base_name} overlaps {rb.base_name}")
            self.assertEqual(len({(r.rect.x, r.rect.y, r.rect.w, r.rect.h) for r in b.rooms}),
                             len(b.rooms), f"{name}: duplicate room rects")

    def test_every_connection_gets_a_door_on_a_shared_wall(self):
        for name, design in self.designs.items():
            b = self.layout(name)
            for (a_room, b_room) in design.connections:
                ra = b.room_by_base(a_room)
                rb = b.room_by_base(b_room)
                self.assertIsNotNone(ra, f"{name}: no room {a_room}")
                self.assertIsNotNone(rb, f"{name}: no room {b_room}")
                pair = shared_wall_cells(ra.rect, rb.rect)
                self.assertTrue(pair, f"{name}: {a_room} and {b_room} share no wall")
                for cell in pair:
                    on_a = cell in ra.rect.cells() and (cell[0] in (ra.rect.x, ra.rect.x1)
                                                        or cell[1] in (ra.rect.y, ra.rect.y1))
                    on_b = cell in rb.rect.cells() and (cell[0] in (rb.rect.x, rb.rect.x1)
                                                        or cell[1] in (rb.rect.y, rb.rect.y1))
                    self.assertTrue(on_a or on_b, f"{name}: door cell {cell} not on a room ring")
                # a facing pair: one cell in each wall, one step apart
                if len(pair) == 2:
                    self.assertEqual(abs(pair[0][0] - pair[1][0]) + abs(pair[0][1] - pair[1][1]), 1)

    def test_entrance_on_the_given_side(self):
        b = self.layout("The Green Dragon Inn")
        d = b.entrance_door
        self.assertEqual(d[1], b.rect.y, "inn entrance should be on the south wall")
        self.assertTrue(b.entrance_room.rect.contains_cell(d))
        b2 = self.layout("Tithe Barn")
        self.assertEqual(b2.entrance_door[1], b2.rect.y)

    def test_rooms_are_big_enough(self):
        for name in self.designs:
            b = self.layout(name)
            for r in b.rooms:
                self.assertGreaterEqual(min(r.rect.w, r.rect.h), 3, f"{name}/{r.base_name} too small")
                inter = r.rect.interior()
                self.assertGreaterEqual(inter.w * inter.h, 2)


if __name__ == "__main__":
    unittest.main()
