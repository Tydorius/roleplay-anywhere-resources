import json
import os
import random
import unittest

import worldgen

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

    def test_every_zone_has_its_spine(self):
        for name in self.world.zones_by_name:
            spine = next((r for r in self.world.regions if r.name == f"{name} Path"), None)
            self.assertIsNotNone(spine, f"zone {name} has no path spine")


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
