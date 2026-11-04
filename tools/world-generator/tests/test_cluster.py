"""A cluster has no corridor: the doors between touching parts are the only way
past the hub, its one outside door. The first live cluster left a clear cell
round the hub, so nobody could reach the towers behind it, and the growth passes
then spent seven hours enlarging a map that room could never fix."""
import types
import unittest
from unittest import mock

import worldgen
from worldgen.layout_compound import _spine_geometry
from worldgen.model import Rect, shared_wall_cells


def part(name, kind, side="", index=0):
    return types.SimpleNamespace(building=name, slot_kind=kind, side=side, index=index,
                                 gate=False, host=None)


def compound(parts, hub_pos="center", axis="ns"):
    return types.SimpleNamespace(parts=parts, spine_width=0, axis=axis, hub_pos=hub_pos,
                                 shape="cluster", name="The Cluster")


def plans(parts, sizes):
    """Part plans with the same footprint under every entrance side."""
    every = ("north", "south", "east", "west")
    return {p.building: (None, "", {s: sizes[p.building] for s in every}) for p in parts}


def linked(placed, start):
    """Every part a walker reaches from ``start`` through shared walls."""
    seen, todo = {start}, [start]
    while todo:
        here = todo.pop()
        for name, rect in placed.items():
            if name not in seen and shared_wall_cells(placed[here], rect):
                seen.add(name)
                todo.append(name)
    return seen


class TestClusterDoors(unittest.TestCase):
    def assert_all_reached(self, parts, sizes, **kw):
        c = compound(parts, **kw)
        _size, geo, _corridors = _spine_geometry(c, plans(parts, sizes))
        placed = geo["placements"]
        self.assertEqual(linked(placed, "Hub"), set(placed), placed)
        names = list(placed)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                self.assertFalse(placed[a].intersects(placed[b]), f"{a} overlaps {b}")

    def test_both_columns_reach_the_hub(self):
        for hub_pos in ("start", "center", "end"):
            with self.subTest(hub_pos):
                self.assert_all_reached(
                    [part("Hub", "hub"), part("A", "spine", "left"), part("B", "spine", "right")],
                    {"Hub": (12, 10), "A": (40, 25), "B": (30, 19)}, hub_pos=hub_pos)

    def test_an_east_west_cluster_too(self):
        self.assert_all_reached(
            [part("Hub", "hub"), part("A", "spine", "left"), part("B", "spine", "right")],
            {"Hub": (12, 10), "A": (20, 12), "B": (20, 9)}, axis="ew")

    def test_a_second_part_in_a_column_is_not_left_behind(self):
        self.assert_all_reached(
            [part("Hub", "hub"), part("A", "spine", "left", 0), part("A2", "spine", "left", 1),
             part("B", "spine", "right")],
            {"Hub": (8, 6), "A": (10, 8), "A2": (10, 8), "B": (10, 6)})

    def test_a_narrow_hub_over_one_column(self):
        for side in ("left", "right"):
            with self.subTest(side):
                self.assert_all_reached([part("Hub", "hub"), part("A", "spine", side)],
                                        {"Hub": (5, 5), "A": (12, 10)})

    def test_end_caps_touch_the_columns(self):
        self.assert_all_reached(
            [part("Hub", "hub"), part("A", "spine", "left"), part("B", "spine", "right"),
             part("Cap", "spine_end", "end")],
            {"Hub": (8, 6), "A": (10, 8), "B": (10, 8), "Cap": (9, 6)})

    def test_a_real_spine_keeps_its_clear_cell(self):
        parts = [part("A", "spine", "left", 0), part("A2", "spine", "left", 1)]
        c = compound(parts)
        c.spine_width = 3
        _size, geo, _corridors = _spine_geometry(c, plans(parts, {"A": (8, 6), "A2": (8, 6)}))
        placed = geo["placements"]
        self.assertEqual(placed["A2"].y - placed["A"].y1, 2)


class TestGrowthStops(unittest.TestCase):
    """Growing can't fix what room doesn't cause, so a build that keeps dropping
    the same things stops after a couple of passes."""

    FAILED = [("compound Court part Tower", "not reachable")]

    def plan(self):
        zone = types.SimpleNamespace(name="Close", compounds=[],
                                     buildings=[types.SimpleNamespace(name="Tower")])
        return types.SimpleNamespace(zones=[zone], compounds=[
            types.SimpleNamespace(name="Court", zone="Close")])

    def attempts(self, failures):
        """How many builds run when build n has failures[n] (the last repeats)."""
        calls = []

        def build(plan, data, seed, exts, scale):
            failed = failures[min(len(calls), len(failures) - 1)]
            calls.append(scale)
            return types.SimpleNamespace(failures=failed)

        with mock.patch.object(worldgen, "parse_plan", return_value=self.plan()), \
                mock.patch.object(worldgen, "_build_world", side_effect=build), \
                mock.patch.object(worldgen, "_coverage_scale", return_value={}), \
                mock.patch("worldgen.extensions.expand", return_value=set()):
            worldgen.run({})
        return len(calls)

    def test_no_progress_stops_after_the_stalled_passes(self):
        self.assertEqual(self.attempts([self.FAILED]), 1 + worldgen.MAX_STALLED_PASSES)

    def test_a_clean_build_never_grows(self):
        self.assertEqual(self.attempts([[]]), 1)

    def test_progress_keeps_it_growing(self):
        two = self.FAILED + [("compound Court part Annex", "not reachable")]
        self.assertEqual(self.attempts([two, two, self.FAILED, self.FAILED, self.FAILED, []]), 5)


if __name__ == "__main__":
    unittest.main()
