"""All four real fixture plans build cleanly, with and without the
region-groups extension: no partial region overlaps (the square must never
sit across a path), full reachability, at most three unplaced pieces."""
import json
import os
import unittest

import worldgen

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
PLANS = ("cyberpunk-glm-plan.json", "medieval-deepseek-plan.json",
         "medieval-glm-plan.json", "modern-glm-plan.json")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def builds():
    for name in PLANS:
        data = load(name)
        for ext in ((), ("region-groups",)):
            yield f"{name} ext={','.join(ext) or 'none'}", data, ext


class TestFixtureBuilds(unittest.TestCase):
    def test_clean_builds(self):
        for label, data, ext in builds():
            with self.subTest(label):
                world = worldgen.run(data, seed=1, extensions=ext)
                m = world.metrics
                self.assertEqual(m["region_overlaps"], [], label)
                self.assertEqual(m["object_overlaps"], [], label)
                self.assertEqual(m["objects_out_of_bounds"], [], label)
                self.assertEqual(m["reachability"], 1.0, label)
                self.assertLessEqual(len(m["objects"]["unplaced"]), 3, label)
                self.assertTrue(m["doors_clear"], label)
                self.assertTrue(m["walkways_clear"], label)


if __name__ == "__main__":
    unittest.main()
