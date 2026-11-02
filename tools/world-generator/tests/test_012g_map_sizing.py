"""Brief 012g: the map is sized from its content, inside out. Every zone
gets at least its content size — a band is as wide as its widest member and
long enough to stack them all, so a compound block never meets a zone too
thin for it. The live zombie-town plan (three zones, three compound blocks:
a 100x100 enclosure, an 88-wide row, a hospital spine) places all three
compounds at seed 1, where the old weight-guessed, GRID_MAX-capped grid
squeezed two of them to "no space in zone"."""
import unittest

from tests import util


class TestZombieTownCompoundsPlace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = util.build_world("zombie-town.plan.json")

    def test_all_three_compounds_place(self):
        names = {c.name for c in self.world.compounds}
        self.assertTrue({"Barlow Stronghold", "Pike Row", "Kettle Spine"} <= names,
                        sorted(names))

    def test_no_zone_too_thin_for_its_block(self):
        self.assertEqual(
            [f for f in self.world.failures if "no space in zone" in f[1]], [])

    def test_every_zone_keeps_its_content_minimums(self):
        """Each zone's rect is at least the compound footprint it holds plus
        its street and lot ring (the sizing rule zone_mins encodes)."""
        import worldgen.layout_map  # noqa: F401  (the footprints need the module)
        from worldgen.layout_compound import compound_footprint
        from worldgen.layout_zone import PATH_WIDTH, lot_spacing
        from worldgen.model import parse_plan

        plan = parse_plan(util.load_plan("zombie-town.plan.json"))
        tmap = {t.name: t for t in plan.templates}
        for z in plan.zones:
            piece = self.world.zone_pieces[z.name][0]
            sp = lot_spacing(z)
            for c in z.compounds:
                w, h = compound_footprint(z, c, tmap)
                self.assertGreaterEqual(
                    (piece.w, piece.h),
                    (w + sp + PATH_WIDTH + 2, h + sp + PATH_WIDTH + 2),
                    f"{z.name} is thinner than {c.name} plus its street ring")


if __name__ == "__main__":
    unittest.main()
