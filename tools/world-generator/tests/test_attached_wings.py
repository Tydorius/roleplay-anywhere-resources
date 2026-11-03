"""Two bugs from the live Bramblewick Barony run, the first world built from
the editor (2026-11-02). Thornrose Court is an enclosure with the Old Hall
inside and an East Wing and West Wing attached to its sides; the builder
refused the world.
- A part attached east or west of an inside part was counted into its host's
  row group twice, so the Old Hall shifted east by a West Wing and the East
  Wing went through the courtyard wall (its upper floor then fell off the map).
- The East Wing is a unit building whose design names a shared room
  "Corridor", and the unit layout adds its own "Corridor" spine: two regions
  named "East Wing Corridor"."""
import random
import unittest

from tests import util

from worldgen.layout_building import layout_building
from worldgen.layout_compound import _row_groups, _inside_rows, compound_footprint, \
    part_plans, place_compound
from worldgen.layout_map import tmap_of
from worldgen.model import Rect, parse_plan


def _overlap(a, b):
    return not (a.x1 < b.x or b.x1 < a.x or a.y1 < b.y or b.y1 < a.y)


class TestAttachedWings(unittest.TestCase):
    def setUp(self):
        self.plan = parse_plan(util.load_plan("live/bramblewick-barony.plan.json"))
        self.tmap = tmap_of(self.plan)
        self.zone, self.court = next((z, c) for z in self.plan.zones
                                     for c in (getattr(z, "compounds", None) or [])
                                     if c.name == "Thornrose Court")

    def test_each_attached_part_rides_once_with_its_host(self):
        plans = part_plans(self.zone, self.court, self.tmap)
        groups = _row_groups(_inside_rows(self.court)["middle"], plans)
        self.assertEqual([g["part"].building for g in groups], ["Old Hall"])
        g = groups[0]
        self.assertEqual([p.building for p in g["east"]], ["East Wing"])
        self.assertEqual([p.building for p in g["west"]], ["West Wing"])
        fp = {name: plans[name][2][plans[name][1]] for name in plans}
        self.assertEqual(g["width"], fp["Old Hall"][0] + fp["East Wing"][0] + fp["West Wing"][0])

    def test_the_wings_stay_inside_the_courtyard(self):
        w, h = compound_footprint(self.zone, self.court, self.tmap)
        out = place_compound(self.zone, self.court, Rect(0, 0, w, h), self.tmap,
                             random.Random(1), furnish=lambda b: None)
        self.assertEqual(out.failures, [])
        parts = {b.layout.design.name: b.lot for b in out.parts}
        for name in ("Old Hall", "East Wing", "West Wing"):
            with self.subTest(name):
                r, c = parts[name], out.courtyard
                self.assertTrue(c.x <= r.x and r.x1 <= c.x1 and c.y <= r.y and r.y1 <= c.y1,
                                f"{name} {r} leaves the courtyard {c}")
        names = sorted(parts)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                with self.subTest(pair=(a, b)):
                    self.assertFalse(_overlap(parts[a], parts[b]), f"{a} overlaps {b}")
        for corr in out.corridors:
            for name, r in parts.items():
                if name in ("Old Hall", "East Wing", "West Wing"):
                    self.assertFalse(_overlap(corr.rect, r), f"{name} overlaps {corr.name}")

    def test_a_design_room_called_corridor_is_the_spine(self):
        design = next(b for z in self.plan.zones for b in z.buildings if b.name == "East Wing")
        self.assertIn("Corridor", [r.name for r in design.rooms])
        b = layout_building(design, (0, 0), random.Random(1), self.tmap)
        names = [r.base_name for r in b.rooms]
        self.assertEqual(names.count("Corridor"), 1, names)
        self.assertIn("Common Room", names)
        self.assertIn("Linen Store", names)


if __name__ == "__main__":
    unittest.main()
