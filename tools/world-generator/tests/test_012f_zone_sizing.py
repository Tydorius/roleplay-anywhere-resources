"""Brief 012f change 6: zones sized round the real block footprint of every
compound shape, front strip included. The minimums are per axis now — a row's
length floors one axis and its depth (the front strip with it) the other, a
spine's wing spread the axis the wings run along — and a blocks-only zone's
fit is a measurement, not an estimate, so the band and centre caps never
stretch it past its own dims. The lone settlement centre keeps the shape its
content fit asks for on every axis, not just the banded ones. Every built-up
zone in the 012e and 012f fixtures fills at least 0.45 of its ground."""
import unittest

from tests import util

# (fixture, extensions) — one build per shape family, plain where the plan
# has no extensions of its own
BUILDS = (
    ("apartment-block.plan.json", ("floors",)),
    ("shop-strip.plan.json", ()),
    ("hospital-spine.plan.json", ()),
    ("ship-void.plan.json", ()),
    ("modern-quarter.plan.json", ("floors",)),
    ("starship-decks.plan.json", ("floors",)),
)


class TestCompoundZoneSizing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {}
        for name, ext in BUILDS:
            data = util.load_plan(name)
            if not ext:
                data.pop("extensions", None)
            cls.worlds[(name, ext)] = util.build_world(name, extensions=ext)

    def test_every_built_zone_fills_at_least_45_percent(self):
        for key, world in self.worlds.items():
            for name, area in world.zone_building_area.items():
                if not area:
                    continue   # an empty wild zone has no content to fill it
                ratio = world.metrics["zone_fill"][name]["ratio"]
                self.assertGreaterEqual(
                    ratio, 0.45,
                    f"{key[0]}: {name} is mostly empty ground (fill {ratio})")

    def test_a_row_zone_runs_long_and_thin(self):
        """The shop row's block is 59 wide and 13 deep with its parking
        front; its zone must run long along the row, not square off to the
        row's length (the 012e build measured fill 0.21 at 66x66)."""
        w = self.worlds[("shop-strip.plan.json", ())]
        piece = w.zone_pieces["Farrow Street"][0]
        self.assertGreaterEqual(piece.w, 1.5 * piece.h, (piece.w, piece.h))
        ratio = w.metrics["zone_fill"]["Farrow Street"]["ratio"]
        self.assertGreaterEqual(ratio, 0.6)

    def test_a_spine_zone_carries_its_wing_spread_across(self):
        """The hospital spine's wings sit either side of the corridor: the
        block is wide across the wings and shallow along the corridor, and
        so is its zone."""
        w = self.worlds[("hospital-spine.plan.json", ())]
        piece = w.zone_pieces["Ruan's Hill"][0]
        self.assertGreaterEqual(piece.w, 1.5 * piece.h, (piece.w, piece.h))
        self.assertGreaterEqual(
            w.metrics["zone_fill"]["Ruan's Hill"]["ratio"], 0.6)

    def test_blocks_only_zones_are_never_stretched_past_their_fit(self):
        """The all-void ship's two zones hold one compound block each: their
        area stays within about a third of the block's own footprint-plus-
        margins (the 012e build ran The Merian to 0.42 and the dock to
        0.39)."""
        w = self.worlds[("ship-void.plan.json", ())]
        for name, block in (("Relay Dock", "Relay Cluster"),
                            ("The Merian", "Merian Spine")):
            piece = w.zone_pieces[name][0]
            comp = next(c for c in w.compounds if c.name == block)
            area = piece.w * piece.h
            self.assertLessEqual(
                area, 1.5 * (comp.rect.w + 7) * (comp.rect.h + 7),
                f"{name} stretches past its block's footprint")


if __name__ == "__main__":
    unittest.main()
