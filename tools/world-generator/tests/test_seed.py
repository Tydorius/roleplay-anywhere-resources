"""The same seed must give the same output, byte for byte."""
import copy
import json
import os
import unittest

import worldgen

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "village.json")


def spec_for(seed):
    with open(FIXTURE, "r", encoding="utf-8") as f:
        data = json.load(f)
    world = worldgen.run(copy.deepcopy(data), seed=seed)
    return worldgen.build_spec(world, copy.deepcopy(data))


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_spec(self):
        a = spec_for(1)
        b = spec_for(1)
        self.assertEqual(a, b)

    def test_different_seed_moves_something(self):
        a = spec_for(1)
        b = spec_for(2)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
