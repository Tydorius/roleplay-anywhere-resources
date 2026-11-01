"""Map-level layout: the zones fill the grid and read as one world."""
import json
import os
import random
import unittest

import worldgen
from worldgen.layout_map import layout_map
from worldgen.model import parse_plan

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "village.json")

# Rect.gap() counts a shared edge as 1, so a margin of N empty cells reads N+1
TOUCHING = 4     # at most 3 empty cells between neighbouring zones
NEARBY = 7       # pairs closer than this are neighbours, not far apart


def load_world(seed=1):
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return worldgen.run(json.load(f), seed=seed)


def load_plan():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return parse_plan(json.load(f))


class TestMapFillsTheGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = load_world(1)

    def test_zones_cover_most_of_the_grid(self):
        # the settlement-centred map keeps a thin margin of open country
        # round the zones (roads walk it), so coverage sits just under 0.9
        W, H = self.world.grid
        covered = sum(r.w * r.h for rs in self.world.zone_pieces.values() for r in rs)
        self.assertGreaterEqual(covered / float(W * H), 0.85)

    def test_no_gap_wider_than_three_cells(self):
        zones = list(self.world.zones_by_name.values())
        for i, a in enumerate(zones):
            for b in zones[i + 1:]:
                gap = a.gap(b)
                if gap <= NEARBY:
                    self.assertLessEqual(gap, TOUCHING,
                                         f"{gap - 1} empty cells between neighbouring zones")

    def test_adjacent_zones_share_an_edge(self):
        for z in load_plan().zones:
            a = self.world.zones_by_name[z.name]
            for n in z.adjacentTo:
                b = self.world.zones_by_name[n]
                self.assertLessEqual(a.gap(b), TOUCHING,
                                     f"{z.name} and {n} do not touch across a shared edge")

    def test_zones_stay_inside_the_grid(self):
        W, H = self.world.grid
        for name, r in self.world.zones_by_name.items():
            self.assertTrue(0 <= r.x and r.x1 < W and 0 <= r.y and r.y1 < H,
                            f"zone {name} outside the grid")

    def test_roads_cross_the_margin_between_their_zones(self):
        for road in self.world.roads:
            a = self.world.zones_by_name[road.a]
            b = self.world.zones_by_name[road.b]
            self.assertLessEqual(a.gap(b), TOUCHING,
                                 f"road {road.a}-{road.b} spans a wide gap")
            for seg in road.rects:
                self.assertTrue(0 <= seg.x and seg.y >= 0
                                and seg.x1 < self.world.grid[0] and seg.y1 < self.world.grid[1])


class TestBuildingsLineThePath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = load_world(1)

    def _street(self, zone_name):
        paths = [r for r in self.world.regions
                 if r.kind == "path" and r.parent == zone_name]
        self.assertTrue(paths, f"zone {zone_name} has no path")
        return max(paths, key=lambda r: max(r.rect.w, r.rect.h)).rect

    def test_buildings_span_the_path(self):
        for zname, zrect in self.world.zones_by_name.items():
            blds = [b for b in self.world.buildings if zrect.contains_rect(b.layout.rect)]
            if len(blds) < 2:
                continue
            street = self._street(zname)
            vertical = street.h >= street.w
            proj = [(b.layout.rect.y, b.layout.rect.y1) if vertical
                    else (b.layout.rect.x, b.layout.rect.x1) for b in blds]
            length = (street.y1 - street.y) if vertical else (street.x1 - street.x)
            span = max(e for _s, e in proj) - min(s for s, _e in proj)
            self.assertGreaterEqual(span, 0.6 * length,
                                    f"{zname} buildings hug one end of the path")

    def test_buildings_line_both_sides_of_the_path(self):
        for zname, zrect in self.world.zones_by_name.items():
            blds = [b for b in self.world.buildings if zrect.contains_rect(b.layout.rect)]
            if len(blds) < 2:
                continue
            street = self._street(zname)
            vertical = street.h >= street.w
            sides = set()
            for b in blds:
                if vertical:
                    sides.add("west" if b.layout.rect.x1 < street.x else "east")
                else:
                    sides.add("south" if b.layout.rect.y1 < street.y else "north")
            self.assertGreaterEqual(len(sides), 2,
                                    f"{zname} buildings all sit on one side of the path")

    def test_entrances_face_a_street(self):
        """Every entrance opens straight onto a street (the main street, a
        side street or the short branch up to one)."""
        for zname, zrect in self.world.zones_by_name.items():
            blds = [b for b in self.world.buildings if zrect.contains_rect(b.layout.rect)]
            if not blds:
                continue
            streets = set()
            for r in self.world.regions:
                if r.kind == "path" and r.parent == zname:
                    streets |= r.rect.cells()
            streets |= self.world.reserved
            for b in blds:
                bl = b.layout
                dx, dy = {"north": (0, 1), "south": (0, -1),
                          "east": (1, 0), "west": (-1, 0)}[bl.entrance_side]
                approach = (bl.entrance_door[0] + dx, bl.entrance_door[1] + dy)
                self.assertIn(approach, streets,
                              f"{bl.design.name} entrance does not open onto a street")


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_map(self):
        plan = load_plan()
        a = layout_map(plan, random.Random(5))
        b = layout_map(plan, random.Random(5))
        self.assertEqual(a.grid, b.grid)
        self.assertEqual({n: r.as_tuple() for n, r in a.zones.items()},
                         {n: r.as_tuple() for n, r in b.zones.items()})
        self.assertEqual([[(r.as_tuple()) for r in road.rects] for road in a.roads],
                         [[(r.as_tuple()) for r in road.rects] for road in b.roads])

    def test_different_seed_moves_something(self):
        plan = load_plan()
        a = layout_map(plan, random.Random(1))
        b = layout_map(plan, random.Random(2))
        marks = ({n: r.as_tuple() for n, r in a.zones.items()},
                 [[r.as_tuple() for r in road.rects] for road in a.roads])
        other = ({n: r.as_tuple() for n, r in b.zones.items()},
                 [[r.as_tuple() for r in road.rects] for road in b.roads])
        self.assertNotEqual(marks, other)


if __name__ == "__main__":
    unittest.main()
