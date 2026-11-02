import json
import os
import random
import unittest

import worldgen
from worldgen import layout_zone
from worldgen.model import Rect

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "village.json")


def load_world(seed=1):
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return worldgen.run(json.load(f), seed=seed)


class TestZoneLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = load_world(1)

    def test_buildings_keep_spacing(self):
        buildings = self.world.buildings
        self.assertGreaterEqual(len(buildings), 5)
        for i, a in enumerate(buildings):
            for b in buildings[i + 1:]:
                gap = a.layout.rect.gap(b.layout.rect)
                self.assertGreaterEqual(gap, 2,
                                        f"{a.layout.design.name} and {b.layout.design.name} closer than 2 cells")

    def test_lots_and_yards_stay_inside_their_zone(self):
        for b in self.world.buildings:
            placed_zones = [r for r in self.world.regions
                            if r.kind == "zone" and r.rect.contains_rect(b.layout.rect)]
            self.assertEqual(len(placed_zones), 1,
                             f"{b.layout.design.name} not inside exactly one zone")

    def test_zone_paths_clear_of_objects(self):
        # every reserved path/door cell is free of blocking objects
        metrics = self.world.metrics
        self.assertTrue(metrics["walkways_clear"])
        self.assertTrue(metrics["doors_clear"])

    def test_zone_props_not_on_paths_or_buildings(self):
        for o in self.world.objects:
            region = self.world.regions_by_name.get(o.region)
            if region is None or region.kind != "zone":
                continue
            t = self.world.templates[o.template]
            w, h = t.size
            fp = {(x, y) for x in range(o.pos[0], o.pos[0] + w) for y in range(o.pos[1], o.pos[1] + h)}
            self.assertFalse(fp & self.world.reserved,
                             f"{o.template} at {o.pos} sits on a path or door approach")
            for b in self.world.buildings:
                self.assertFalse(fp & b.layout.rect.cells(),
                                 f"{o.template} at {o.pos} overlaps building {b.layout.design.name}")

    def test_every_built_zone_has_its_spine(self):
        for name, area in self.world.zone_building_area.items():
            if not area:
                continue   # an empty wild zone may have no path at all
            spine = next((r for r in self.world.regions if r.name == f"{name} Path"), None)
            self.assertIsNotNone(spine, f"zone {name} has no path spine")

    def test_empty_wild_zone_gets_one_track_or_none(self):
        # a wild zone with nothing in it has either no path (fewer than two
        # road mouths) or one track joining its mouths — never parallel
        # full-length streets through empty ground
        empty = [name for name, area in self.world.zone_building_area.items()
                 if not area]
        self.assertTrue(empty, "the fixture has no empty wild zone to check")
        for name in empty:
            paths = [r.rect for r in self.world.regions
                     if r.kind == "path" and r.parent == name]
            if not paths:
                continue
            cells = set()
            for r in paths:
                cells |= r.cells()
            seen = set()
            todo = [next(iter(cells))]
            while todo:
                c = todo.pop()
                if c in seen:
                    continue
                seen.add(c)
                x, y = c
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in cells:
                        todo.append(n)
            self.assertEqual(len(seen), len(cells),
                             f"zone {name}'s track is not one connected run")


class TestWildZoneTrack(unittest.TestCase):
    """A wild zone's path is one track between its road mouths, or nothing."""

    def layout(self, rect, reserved):
        from worldgen.model import Zone
        zone = Zone("Whisperwood", kind="old-growth forest")
        return layout_zone.layout_zone(zone, rect, {}, random.Random(4),
                                       road_reserved=reserved)

    def test_two_mouths_get_one_track_joining_them(self):
        rect = Rect(0, 0, 30, 26)
        out = self.layout(rect, {(0, y) for y in range(11, 14)} |
                          {(29, y) for y in range(19, 22)})
        self.assertEqual(out.feature, None)
        self.assertTrue(out.spine_rects)
        cells = set()
        for r in out.spine_rects:
            cells |= r.cells()
        self.assertTrue((0, 12) in cells and (29, 20) in cells,
                        "the track does not reach both road mouths")

    def test_one_mouth_gets_no_path_at_all(self):
        out = self.layout(Rect(0, 0, 30, 26), {(0, y) for y in range(11, 14)})
        self.assertIsNone(out.street)
        self.assertEqual(out.spine_rects, [])


class TestZoneFillMetric(unittest.TestCase):
    """zone_fill measures every zone: area, content (buildings, compound
    blocks with their courtyards, yards, fields, the green, one lot ring each)
    and the ratio between them."""

    @classmethod
    def setUpClass(cls):
        from tests.util import build_world
        cls.world = build_world("ashvale-compound.plan.json")

    def test_every_zone_measured(self):
        names = set(self.world.zones_by_name)
        self.assertEqual(set(self.world.metrics["zone_fill"]), names)

    def test_values_are_sane(self):
        for zn, f in self.world.metrics["zone_fill"].items():
            self.assertGreater(f["area"], 0, zn)
            self.assertGreaterEqual(f["content"], 0, zn)
            self.assertLessEqual(f["content"], f["area"], zn)
            self.assertAlmostEqual(f["ratio"], round(f["content"] / float(f["area"]), 3),
                                   places=3, msg=zn)

    def test_wild_zone_without_buildings_has_no_content(self):
        self.assertEqual(self.world.metrics["zone_fill"]["Whisperwood"]["content"], 0)


if __name__ == "__main__":
    unittest.main()
