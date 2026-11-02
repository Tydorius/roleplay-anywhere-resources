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


class TestAshvaleCompoundFixture(unittest.TestCase):
    """The compound fixture: a castle of four towers, a gatehouse and a keep
    joined by walkable walls, the village around its green, the farm in
    fields — clean in all four extension combinations."""

    EXTS = ((), ("region-groups",), ("floors",), ("floors", "region-groups"))

    @classmethod
    def setUpClass(cls):
        cls.data = load("ashvale-compound.plan.json")
        cls.worlds = {ext: worldgen.run(cls.data, seed=1, extensions=ext)
                      for ext in cls.EXTS}

    def assertClean(self, world, label):
        m = world.metrics
        self.assertEqual(m["region_overlaps"], [], label)
        self.assertEqual(m["object_overlaps"], [], label)
        self.assertEqual(m["objects_out_of_bounds"], [], label)
        self.assertEqual(m["reachability"], 1.0, label)
        self.assertEqual(m["objects"]["unplaced"], [], label)
        self.assertTrue(m["doors_clear"], label)
        self.assertTrue(m["walkways_clear"], label)
        self.assertEqual(world.failures, [], label)
        if "floors" in label:
            self.assertEqual(m["floors"]["issues"], [], label)

    def test_all_four_combinations_clean(self):
        for ext in self.EXTS:
            label = f"ext={','.join(ext) or 'none'}"
            with self.subTest(label):
                self.assertClean(self.worlds[ext], label)

    def test_castle_is_walls_towers_gate_and_keep(self):
        for ext in self.EXTS:
            label = f"ext={','.join(ext) or 'none'}"
            names = {r.name for r in self.worlds[ext].regions}
            with self.subTest(label):
                self.assertIn("Ashvale Castle", names)
                towers = {"Northwest Tower", "Northeast Tower",
                          "Southeast Tower", "Southwest Tower"}
                self.assertTrue(towers <= names, sorted(towers - names))
                for part in ("Gatehouse", "Ashvale Keep", "Garrison Barracks"):
                    self.assertIn(part, names)
                walls = {n for n in names if n.startswith("Ashvale Castle Wall")}
                self.assertGreaterEqual(len(walls), 4, sorted(walls))

    def test_village_green_and_farm_fields_exist(self):
        for ext in self.EXTS:
            label = f"ext={','.join(ext) or 'none'}"
            world = self.worlds[ext]
            with self.subTest(label):
                square = [r for r in world.regions
                          if r.name == "Emberwick Village Square"]
                self.assertEqual(len(square), 1)
                fields = [r for r in world.regions
                          if r.kind == "field" and r.parent == "Millfield Farms"]
                self.assertGreaterEqual(len(fields), 2)

    def test_wall_walk_joins_the_upper_storeys(self):
        world = self.worlds[("floors",)]
        walks = [r for r in world.regions
                 if r.name.startswith("Ashvale Castle Wall")
                 and "upper floor" in r.name]
        self.assertGreaterEqual(len(walks), 2, [r.name for r in walks])
        # every tower rose to its lookout, the keep and gatehouse to storey 2
        ups = {r.name for r in world.regions if "upper floor" in r.name}
        for part in ("Northwest Tower", "Northeast Tower", "Southeast Tower",
                     "Southwest Tower", "Gatehouse", "Ashvale Keep"):
            self.assertTrue(any(n.startswith(part) for n in ups), part)


if __name__ == "__main__":
    unittest.main()
