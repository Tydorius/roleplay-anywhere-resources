"""A symmetric pair never overlaps itself: in an odd-width room the mirror
of a 2-wide piece next to the middle shares a cell with it. Found by the
live zombie-town run (two plywood barricades in a 9x5 entry hall)."""
import random
import unittest

from worldgen.layout_room import layout_room
from worldgen.model import FurniturePlan, ObjectTemplate, Rect


class TestSymmetricOverlap(unittest.TestCase):
    def test_pairs_never_share_a_cell(self):
        templates = {"Board": ObjectTemplate(name="Board", size=(2, 1), walkability=0.2)}
        for w in (7, 8, 9, 10, 11):
            for seed in range(20):
                with self.subTest(w=w, seed=seed):
                    rect = Rect(0, 0, w, 5)
                    lay = layout_room(rect, [(0, 2)],
                                      [FurniturePlan("Board", "R", 2, "symmetric")],
                                      templates, random.Random(seed))
                    cells = []
                    for (_n, (x, y)) in lay.placements:
                        cells += [(x, y), (x + 1, y)]
                    self.assertEqual(len(cells), len(set(cells)), lay.placements)


if __name__ == "__main__":
    unittest.main()
