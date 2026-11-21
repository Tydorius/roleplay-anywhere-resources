"""Rect.touches_any gives the same answer as building the rect's cell set."""
import random
import unittest

from worldgen.model import Rect


class TestTouchesAny(unittest.TestCase):

    def test_matches_the_cell_set_intersection(self):
        rng = random.Random(7)
        for _ in range(2000):
            r = Rect(rng.randint(-5, 20), rng.randint(-5, 20),
                     rng.randint(1, 12), rng.randint(1, 12))
            cells = {(rng.randint(-8, 35), rng.randint(-8, 35))
                     for _ in range(rng.choice((0, 1, 3, 40, 400)))}
            self.assertEqual(r.touches_any(cells), bool(r.cells() & cells),
                             (r, len(cells)))

    def test_edges_count_and_neighbours_do_not(self):
        r = Rect(2, 3, 4, 2)                  # x 2..5, y 3..4
        self.assertTrue(r.touches_any({(2, 3)}))
        self.assertTrue(r.touches_any({(5, 4)}))
        self.assertFalse(r.touches_any({(6, 4), (1, 3), (3, 5), (3, 2)}))
        self.assertFalse(r.touches_any(set()))


if __name__ == "__main__":
    unittest.main()
