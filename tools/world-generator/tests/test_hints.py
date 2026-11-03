import unittest

from worldgen.hints import parse


class TestHints(unittest.TestCase):
    def test_wall_side(self):
        h = parse("wall:north")
        self.assertEqual(h.walls, ("north",))
        self.assertTrue(h.constrained)

    def test_combined(self):
        h = parse("wall:north+center")
        self.assertEqual(h.walls, ("north",))
        self.assertTrue(h.center)

    def test_around_and_beside(self):
        h = parse("around:Trestle table")
        self.assertEqual(h.around, "Trestle table")
        h = parse("beside:Clay hearth")
        self.assertEqual(h.beside, "Clay hearth")

    def test_zone_hints(self):
        h = parse("behind:Oak Cottage")
        self.assertEqual(h.rel, "behind")
        self.assertEqual(h.building_ref, "Oak Cottage")
        self.assertTrue(parse("along_path").along_path)
        self.assertTrue(parse("edge").edge)
        self.assertTrue(parse("cluster").cluster)
        self.assertTrue(parse("scatter").scatter)

    def test_door_hints(self):
        self.assertTrue(parse("near_door").near_door)
        self.assertTrue(parse("away_from_door").away_from_door)

    def test_row_hint(self):
        self.assertEqual(parse("row:east").row, "east")

    def test_unknown_falls_back_to_anywhere(self):
        h = parse("on the ceiling")
        self.assertFalse(h.constrained)
        self.assertEqual(h.unknown, ("on the ceiling",))
        h = parse("wall:diagonal")
        self.assertFalse(h.constrained)

    def test_empty(self):
        self.assertFalse(parse("").constrained)
        self.assertFalse(parse(None).constrained)
