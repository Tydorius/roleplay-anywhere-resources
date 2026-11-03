"""Spine and cluster compounds hold their attached parts inside their own
block. The zombie town's "Maintenance Annex" hangs off the Emergency
Department; it used to be placed after the block was sized, so it poked out
of the compound region and the builder refused the world (brief 012h2)."""
import unittest

from tests import util
from worldgen.layout_compound import _spine_geometry, part_plans
from worldgen.layout_map import tmap_of
from worldgen.model import parse_plan


def _overlap(a, b):
    return not (a.x1 < b.x or b.x1 < a.x or a.y1 < b.y or b.y1 < a.y)


class TestSpineAttachedParts(unittest.TestCase):
    def setUp(self):
        self.plan = parse_plan(util.load_plan("zombie-town.plan.json"))
        self.tmap = tmap_of(self.plan)

    def _geometry(self, name):
        for z in self.plan.zones:
            for c in getattr(z, "compounds", None) or []:
                if c.name == name:
                    return c, _spine_geometry(c, part_plans(z, c, self.tmap))
        self.fail(f"no compound {name}")

    def test_the_annex_sits_inside_the_spine_block(self):
        compound, ((w, h), geo, _corr) = self._geometry("Kettle Spine")
        placed = geo["placements"]
        self.assertIn("Maintenance Annex", placed)
        for name, r in placed.items():
            with self.subTest(name):
                self.assertTrue(r.x >= 0 and r.y >= 0 and r.x1 < w and r.y1 < h,
                                f"{name} {r} outside the {w}x{h} block")

    def test_no_part_overlaps_another_or_the_corridor(self):
        _compound, ((_w, _h), geo, corridors) = self._geometry("Kettle Spine")
        rects = list(geo["placements"].items()) + \
            [(f"corridor {i}", r) for i, r in enumerate(corridors)]
        for i, (na, a) in enumerate(rects):
            for nb, b in rects[i + 1:]:
                with self.subTest(f"{na} / {nb}"):
                    self.assertFalse(_overlap(a, b), f"{na} {a} overlaps {nb} {b}")


if __name__ == "__main__":
    unittest.main()
