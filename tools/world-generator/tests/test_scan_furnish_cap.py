"""A hang from the live Bramblewick Barony plan at seed 2 (2026-11-03). The
Bent Antler Inn's common room never furnished cleanly, so every spot the
fallback scan tried was furnished twice and rolled back: thousands of spots per
layout, and a zone is laid out dozens of times while it is measured. A room
that will not furnish fails the same way everywhere; the scan now settles
after a few such spots."""
import collections
import random
import unittest

from tests import util

from worldgen import layout_zone as lz
from worldgen.layout_map import tmap_of
from worldgen.model import Rect, parse_plan


class TestScanFurnishCap(unittest.TestCase):
    def test_unfurnishable_rooms_do_not_scan_the_whole_zone(self):
        plan = parse_plan(util.load_plan("live/bramblewick-barony.plan.json"))
        tmap = tmap_of(plan)
        zone = next(z for z in plan.zones if z.name == "Nettlebrook Village")
        calls = collections.Counter()
        real = lz._furnish

        def never_clean(out, b, zone, templates, rng):
            real(out, b, zone, templates, rng)
            calls[b.layout.design.name] += 1
            return [(f"room in {b.layout.design.name}", "test: never furnishes")]

        lz._furnish = never_clean
        try:
            out = lz.layout_zone(zone, Rect(0, 0, 120, 120), tmap, random.Random(2))
        finally:
            lz._furnish = real
        self.assertEqual(len(out.buildings), len(zone.buildings))
        # a slot or street frontage tries a few dozen spots at most; the whole
        # 120x120 zone would be thousands
        for name, n in calls.items():
            with self.subTest(name):
                self.assertLess(n, 600, f"{name} furnished {n} times")


if __name__ == "__main__":
    unittest.main()
