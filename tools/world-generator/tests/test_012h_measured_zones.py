"""Brief 012h change 1: a zone is measured, not estimated. measure_zone
lays each built zone out in its own frame — road mouths on the sides its
roads arrive on, read from adjacency the way _assign_sides assigns bands —
and returns the size the real layout needed. Every built zone in every
fixture measures at least its content minimums, a re-layout in a rect of
exactly the measured size places everything, and the same seed measures
the same size twice.

Brief 012h change 2: the map places each built zone at that measured size,
so no fixture drops a building for want of zone space."""
import os
import random
import unittest

import worldgen
from tests import util
from worldgen.layout_map import (_assign_sides, _grid_size, _settlement_group,
                                 _zone_mins, _zone_weight, tmap_of)
from worldgen.layout_zone import _entry_mouths, layout_zone, measure_zone
from worldgen.model import Rect, parse_plan

PLANS = sorted(f for f in os.listdir(util.FIXTURES) if f.endswith(".json"))


def measured_table():
    """{(fixture, zone name): ((w, h), entry sides)} for every built zone in
    every fixture, measured once with the entry sides its adjacency points
    at."""
    out = {}
    for name in PLANS:
        plan = parse_plan(util.load_plan(name))
        tmap = tmap_of(plan)
        weights = {z.name: _zone_weight(z, tmap) for z in plan.zones}
        settle, outer = _settlement_group(plan, weights)
        _sides, entry = _assign_sides(plan, settle, outer, weights,
                                      random.Random(1), *_grid_size(weights))
        for z in plan.zones:
            size = measure_zone(z, tmap, random.Random(1), entry[z.name])
            if size is not None:
                out[(name, z.name)] = (size, entry[z.name])
    return out


class TestMeasuredZones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = measured_table()

    def test_every_built_zone_in_every_fixture_is_measured(self):
        built = 0
        for name in PLANS:
            plan = parse_plan(util.load_plan(name))
            for z in plan.zones:
                if z.buildings or getattr(z, "compounds", None):
                    built += 1
                    self.assertIn((name, z.name), self.table,
                                  f"{name}: {z.name} was not measured")
        self.assertGreater(built, 20)

    def test_a_wild_zone_is_not_measured(self):
        for name in PLANS:
            plan = parse_plan(util.load_plan(name))
            tmap = tmap_of(plan)
            for z in plan.zones:
                if z.buildings or getattr(z, "compounds", None):
                    continue
                self.assertIsNone(measure_zone(z, tmap, random.Random(1), ("east",)),
                                  f"{name}: {z.name} should fill leftover space")
                return
        self.fail("no fixture has a wild zone to measure")

    def test_every_measurement_meets_the_content_minimums(self):
        for name in PLANS:
            plan = parse_plan(util.load_plan(name))
            tmap = tmap_of(plan)
            for z in plan.zones:
                got = self.table.get((name, z.name))
                if got is None:
                    continue
                size, _entry = got
                min_w, min_h = _zone_mins(z, tmap)
                self.assertGreaterEqual(size, (min_w, min_h),
                                        f"{name}: {z.name} measured {size} "
                                        f"under its minimums {(min_w, min_h)}")

    def test_a_relayout_at_exactly_the_measured_size_places_everything(self):
        """The same rng state that measured the zone lays it out again, in a
        rect of exactly the measured size: the mouths land on the same sides
        at the same positions, and everything places."""
        for (name, zname), (size, entry) in sorted(self.table.items()):
            with self.subTest(f"{name} {zname}"):
                plan = parse_plan(util.load_plan(name))
                z = next(zz for zz in plan.zones if zz.name == zname)
                w, h = size
                # the same inner rng stream the measurement laid out with:
                # the seed it drew, then the mouths from that seed
                inner = random.Random(random.Random(1).randrange(1 << 30))
                mouths = _entry_mouths(w, h, entry, inner)
                out = layout_zone(z, Rect(0, 0, w, h), tmap_of(plan),
                                  inner, road_reserved=mouths)
                lost = [r for (_what, r) in out.failures if "no space in zone" in r]
                self.assertTrue(
                    not lost and len(out.buildings) == len(z.buildings)
                    and len(out.compounds) == len(getattr(z, "compounds", None) or []),
                    f"{zname}: {lost}")

    def test_the_same_seed_measures_the_same_size(self):
        plan = parse_plan(util.load_plan("ashvale-compound.plan.json"))
        tmap = tmap_of(plan)
        z = next(zz for zz in plan.zones if zz.name == "Emberwick Village")
        a = measure_zone(z, tmap, random.Random(3), ("east", "north"))
        b = measure_zone(z, tmap, random.Random(3), ("east", "north"))
        self.assertEqual(a, b)


class TestTheMapPlacesMeasuredZones(unittest.TestCase):
    """Brief 012h change 2: a built zone's rect is the size its own layout
    measured, so nothing is dropped for want of zone space — the two Ashvale
    builds and the zombie town that the estimate-sized map squeezed at
    seed 2, and every other fixture at both seeds."""

    def test_no_fixture_has_a_no_space_failure_at_seeds_1_and_2(self):
        for name in PLANS:
            for seed in (1, 2):
                with self.subTest(f"{name} seed {seed}"):
                    world = worldgen.run(util.load_plan(name), seed=seed)
                    lost = [f for f in world.failures if "no space in zone" in f[1]]
                    self.assertEqual(lost, [], f"{name} seed {seed}: {lost}")


if __name__ == "__main__":
    unittest.main()
