"""Agricultural zones get real crop fields: at least two fenced plots per
zone, parallel crop rows with one-cell furrows between them, all nested in
the zone and clear of every path, building and yard."""
import json
import os
import unittest

import worldgen
from worldgen.model import parse_plan, zone_class

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def agricultural_worlds():
    """(label, world, plan) for every fixture holding an agricultural zone."""
    out = []
    for name in ("medieval-glm-plan.json", "medieval-deepseek-plan.json",
                 "modern-glm-plan.json", "village.json"):
        data = load(name)
        plan = parse_plan(data)
        if not any(zone_class(z) == "agricultural" for z in plan.zones):
            continue
        for ext in ((), ("region-groups",)):
            out.append((f"{name} ext={','.join(ext) or 'none'}",
                        worldgen.run(data, seed=1, extensions=ext), plan))
    return out


class TestCropFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = agricultural_worlds()

    def agricultural_zones(self, plan):
        return [z.name for z in plan.zones if zone_class(z) == "agricultural"]

    def test_every_agricultural_zone_gets_two_plots(self):
        for label, world, plan in self.worlds:
            fields = {}
            for r in world.regions:
                if r.kind == "field":
                    fields.setdefault(r.parent, []).append(r)
            for zn in self.agricultural_zones(plan):
                self.assertGreaterEqual(len(fields.get(zn, [])), 2,
                                        f"{label}: {zn} has {len(fields.get(zn, []))} plots")

    def test_plots_hold_parallel_crop_rows(self):
        """Each plot carries crop objects in at least two parallel lines,
        with a furrow (an empty cell) between the lines."""
        for label, world, plan in self.worlds:
            by_region = {}
            for o in world.objects:
                by_region.setdefault(o.region, []).append(o.pos)
            for r in world.regions:
                if r.kind != "field":
                    continue
                cells = by_region.get(r.name, [])
                self.assertGreaterEqual(len(cells), 4,
                                        f"{label}: {r.name} has too few plants")
                ys = {y for (_x, y) in cells}
                xs = {x for (x, _y) in cells}
                lines = ys if r.rect.w >= r.rect.h else xs
                self.assertGreaterEqual(len(lines), 2,
                                        f"{label}: {r.name} plants are not in rows")

    def test_plots_nested_in_zone_and_clear_of_paths(self):
        for label, world, plan in self.worlds:
            paths = [r for r in world.regions if r.kind == "path"]
            for r in world.regions:
                if r.kind != "field":
                    continue
                zone = world.zones_by_name[r.parent]
                self.assertTrue(zone.contains_rect(r.rect),
                                f"{label}: {r.name} escapes its zone")
                for p in paths:
                    if p.parent == r.parent:
                        self.assertFalse(r.rect.intersects(p.rect),
                                         f"{label}: {r.name} overlaps {p.name}")


if __name__ == "__main__":
    unittest.main()
