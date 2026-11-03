"""Settlement zones size to their content: the cyberpunk districts pack to
at least 40% building coverage each, medieval villages stay loose under 30%,
the zones read as compact blocks (no long full-width bands), and the grid
never drops under its 48x48 floor."""
import json
import os
import unittest

import worldgen

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


class TestBuildingCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.punk = worldgen.run(load("cyberpunk-glm-plan.json"), seed=1)
        cls.med = worldgen.run(load("medieval-glm-plan.json"), seed=1)

    def test_metric_present_for_every_built_zone(self):
        cov = self.punk.metrics["density"]["building_coverage"]
        self.assertEqual(set(cov), {"Neon Row", "Stack Alley", "Clinic Block"})

    def test_cyberpunk_districts_are_packed(self):
        cov = self.punk.metrics["density"]["building_coverage"]
        for zn, c in cov.items():
            self.assertGreaterEqual(c, 40.0, f"{zn} coverage {c}% is sparse")

    def test_medieval_villages_stay_loose(self):
        cov = self.med.metrics["density"]["building_coverage"]
        self.assertIn("Village Green", cov)
        self.assertLess(cov["Village Green"], 30.0,
                        f"Village Green coverage {cov['Village Green']}% is too tight")

    def test_urban_core_is_blocks_not_bands(self):
        """Every settlement zone of the all-settlement fixture is a compact
        block, not a strip spanning the core."""
        for zn, zr in self.punk.zones_by_name.items():
            aspect = max(zr.w / float(zr.h), zr.h / float(zr.w))
            self.assertLess(aspect, 3.0,
                            f"{zn} is {zr.w}x{zr.h}, a band not a block")

    def test_grid_respects_its_floor(self):
        for name in ("cyberpunk-glm-plan.json", "medieval-glm-plan.json"):
            with self.subTest(name):
                w = worldgen.run(load(name), seed=1)
                self.assertGreaterEqual(min(w.grid), 48)
                self.assertLessEqual(max(w.grid), 160)


if __name__ == "__main__":
    unittest.main()
