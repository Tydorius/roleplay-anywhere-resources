"""Zones are sized to what is built, not the other way round (2026-11-03).
Bramblewick Barony at seed 3 dropped seven buildings: with region-groups,
Thornrose Estate wrapped round a corner, and its contentless piece on the
north band claimed the estate's whole measured size. The band grew 73 tall,
the village was cut to 73x54 of its measured 73x73 and Hollyfields to a 12-wide
strip of its 40x40, and the buildings that no longer fitted were dropped.
A wrap's far piece is open land now, and the map grows until every measured
zone holds its own layout."""
import random
import unittest

from tests import util

from worldgen.extensions import expand
from worldgen.layout_map import layout_map
from worldgen.model import parse_plan


def _short(m):
    out = {}
    for name, (mw, mh) in m.measured.items():
        r = m.zone_pieces[name][0]
        if r.w < mw or r.h < mh:
            out[name] = ((r.w, r.h), (mw, mh))
    return out


class TestZonesFitMeasured(unittest.TestCase):
    def test_bramblewick_seed_3_keeps_every_measured_size(self):
        data = util.load_plan("live/bramblewick-barony.plan.json")
        m = layout_map(parse_plan(data), random.Random(3),
                       extensions=expand(set(data.get("extensions", []))))
        self.assertEqual(_short(m), {})
        self.assertEqual(m.zone_pieces["Hollyfields"][0].w, m.measured["Hollyfields"][0])

    def test_fixtures_with_region_groups_keep_every_measured_size(self):
        for fixture in ("village.json", "medieval-glm-plan.json",
                        "ashvale-compound.plan.json", "zombie-town.plan.json"):
            for seed in (1, 2, 3):
                with self.subTest(fixture=fixture, seed=seed):
                    m = layout_map(parse_plan(util.load_plan(fixture)), random.Random(seed),
                                   extensions=expand({"region-groups"}))
                    self.assertEqual(_short(m), {})


if __name__ == "__main__":
    unittest.main()
