"""A field's dirt track stops where it meets an earlier field's track,
joining the path network instead of crossing it: the builder refuses two
path regions that overlap. Found by the village at seed 7 once zones were
sized to their measured layout (brief 012h2)."""
import unittest

import worldgen
from tests import util


def _overlap(a, b):
    return not (a.x1 < b.x or b.x1 < a.x or a.y1 < b.y or b.y1 < a.y)


class TestFieldTracksNeverCross(unittest.TestCase):
    def test_no_two_paths_overlap(self):
        for seed in (1, 7):
            world = worldgen.run(util.load_plan("village.json"), seed=seed)
            paths = [r for r in world.regions if r.kind == "path"]
            for i, a in enumerate(paths):
                for b in paths[i + 1:]:
                    with self.subTest(seed=seed, a=a.name, b=b.name):
                        self.assertFalse(_overlap(a.rect, b.rect),
                                         f"{a.name} {a.rect} overlaps {b.name} {b.rect}")


if __name__ == "__main__":
    unittest.main()
