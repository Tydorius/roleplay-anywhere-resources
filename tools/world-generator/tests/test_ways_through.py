"""What Meridian Block's first look found on 2026-11-04: seven market stalls stood
side by side and walled the lane off from the clinic, and the whole Rosewater
complex, baths and all, had one door to the street."""
import json
import os
import types
import unittest

import worldgen
from worldgen import checks, exits
from worldgen.layout_zone import ZoneOut, _place_props, _ring_loop, _splits_ground
from worldgen.model import ObjectTemplate, PropPlan, Rect

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def footprint(x, y, w=2, h=2):
    return {(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)}


class TestSplitsGround(unittest.TestCase):
    RECT = Rect(0, 0, 30, 30)

    def test_the_ring_goes_all_the_way_round(self):
        loop = _ring_loop(footprint(5, 5))
        self.assertEqual(len(loop), 12)
        self.assertEqual(len(set(loop)), 12)
        for a, b in zip(loop, loop[1:] + loop[:1]):
            self.assertEqual(abs(a[0] - b[0]) + abs(a[1] - b[1]), 1)

    def test_a_piece_may_stand_alone(self):
        self.assertFalse(_splits_ground(footprint(5, 5), set(), self.RECT))

    def test_a_piece_may_lean_on_one_obstacle(self):
        self.assertFalse(_splits_ground(footprint(5, 5), footprint(7, 5), self.RECT))

    def test_a_piece_may_not_close_a_gap(self):
        walls = footprint(3, 5) | footprint(7, 5)
        self.assertTrue(_splits_ground(footprint(5, 5), walls, self.RECT))

    def test_two_corners_count_as_a_gap_closed(self):
        walls = {(4, 4), (7, 7)}
        self.assertTrue(_splits_ground(footprint(5, 5), walls, self.RECT))

    def test_a_piece_may_run_along_the_zone_edge(self):
        self.assertFalse(_splits_ground(footprint(0, 5), footprint(0, 7), self.RECT))


class TestStallRows(unittest.TestCase):
    def place(self, count, rect=Rect(0, 0, 12, 12), walkability=0.0, blocked=()):
        zone = types.SimpleNamespace(name="Lane", exterior="open")
        out = ZoneOut(zone, rect)
        out.ground_blocked = set(blocked)
        stall = ObjectTemplate(name="Stall", size=(2, 2), walkability=walkability)
        prop = PropPlan(template="Stall", count=count, hint="cluster")
        _place_props(out, prop, rect, {"Stall": stall}, __import__("random").Random(1), set(),
                     {}, "Lane", zone=zone)
        return out

    def test_solid_stalls_leave_a_gap_between_them(self):
        out = self.place(6)
        self.assertEqual(len(out.props), 6)
        spots = [p.pos for p in out.props]
        for i, a in enumerate(spots):
            for b in spots[i + 1:]:
                self.assertGreater(max(abs(a[0] - b[0]), abs(a[1] - b[1])), 2, (a, b))

    def test_pieces_you_can_walk_over_may_touch(self):
        out = self.place(9, Rect(0, 0, 6, 6), walkability=0.5)
        self.assertEqual(len(out.props), 9)

    def test_when_space_runs_out_they_touch_but_never_close_a_gap(self):
        """A lane two cells wide between two buildings: nothing may fill it."""
        rect = Rect(0, 0, 20, 8)
        blocked = {(x, y) for x in range(20) for y in range(8) if y not in (3, 4)}
        out = self.place(3, rect, blocked=blocked)
        for p in out.props:
            self.assertFalse(footprint(*p.pos) <= {(x, y) for x in range(20) for y in (3, 4)}
                             and p.pos[0] not in (0, 18), p.pos)


class TestSideExits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(FIXTURES, "hospital-spine.plan.json"), encoding="utf-8") as f:
            cls.world = worldgen.run(json.load(f), seed=1)

    def outside_doors(self, world):
        solid = set()
        for b in world.buildings:
            solid |= b.layout.rect.cells()
        walled = [r for r in world.regions if r.wall]
        doors = set()
        for b in world.buildings:
            for d in exits._doors(b):
                near = [(d[0] + 1, d[1]), (d[0] - 1, d[1]), (d[0], d[1] + 1), (d[0], d[1] - 1)]
                if any(n not in solid and not any(r.rect.contains_cell(n) for r in walled)
                       for n in near):
                    doors.add(d)
        return doors

    def test_a_complex_has_more_than_one_way_out(self):
        self.assertGreaterEqual(len(self.outside_doors(self.world)), 2)
        self.assertTrue(self.world.side_exits)

    def test_a_side_door_opens_onto_ground_people_can_reach(self):
        openings = checks.compute_openings(self.world)
        blocked, _doors = checks.walkability_grid(self.world, openings)
        reached = checks.flood(self.world, [self.world.player.pos], blocked,
                               checks.portal_jumps(self.world))
        for (_name, _room, cell) in self.world.side_exits:
            self.assertIn(cell, reached)
            self.assertNotIn(cell, blocked)

    def test_a_side_door_is_a_real_opening_on_its_building(self):
        for (_name, _room, cell) in self.world.side_exits:
            self.assertTrue(any(cell in (getattr(b.layout, "extra_doors", None) or ())
                                for b in self.world.buildings))

    def test_nobody_is_cut_off(self):
        self.assertEqual(self.world.metrics["open_cells_cut_off"]["total"], 0)


class TestSmallBuildings(unittest.TestCase):
    def test_a_room_within_reach_needs_no_second_door(self):
        rooms = [(None, None, {(x, 1) for x in range(1, 9)})]
        cells = rooms[0][2]
        self.assertLessEqual(exits._worst(rooms, exits._walk({(1, 1)}, cells)), exits.EXIT_REACH)


if __name__ == "__main__":
    unittest.main()
