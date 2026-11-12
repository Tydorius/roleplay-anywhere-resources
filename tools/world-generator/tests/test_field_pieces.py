"""The field code picks its crop and fence pieces by whole words and honors
each piece's footprint. A live world (brief 016) failed to build with 87
overlapping objects, all in its crop fields: a counter tagged 'shop' matched
the crop word 'hop' by substring, and a 2x2 garden bed tagged 'fence' became
a fence ring that claimed only one row of its cells."""
import random
import unittest

from worldgen.layout_zone import (_pick_crop, _pick_fence, _place_fields,
                                  ZoneOut)
from worldgen.model import ObjectTemplate, Rect


def tpl(name, size=(1, 1), walkability=0.5, tags=()):
    return ObjectTemplate(name=name, size=tuple(size), walkability=walkability,
                          tags=list(tags))


def catalogue(*pieces):
    return {t.name: t for t in pieces}


class TestCropPickingWholeWords(unittest.TestCase):
    def test_shop_tagged_counter_is_no_crop(self):
        counter = tpl("Elm tap counter", size=(3, 1), walkability=0.0,
                      tags=("counter", "furniture", "bar", "shop"))
        self.assertIsNone(_pick_crop(catalogue(counter)))

    def test_real_crops_are_picked(self):
        wheat = tpl("Wheat row", size=(3, 1), tags=("crop",))
        self.assertIs(_pick_crop(catalogue(wheat)), wheat)
        herbs = tpl("Herbs")
        self.assertIs(_pick_crop(catalogue(herbs)), herbs)

    def test_store_pieces_are_not_crops(self):
        self.assertIsNone(_pick_crop(catalogue(tpl("Oat sacks"))))

    def test_substring_names_are_not_crops(self):
        for name in ("Boat", "Corner shelf", "Divine statue"):
            self.assertIsNone(_pick_crop(catalogue(tpl(name))), name)


class TestFencePickingThinPieces(unittest.TestCase):
    def test_a_fenced_bed_is_no_fence(self):
        bed = tpl("Wattled garden bed", size=(2, 2), tags=("plant", "fence"))
        self.assertIsNone(_pick_fence(catalogue(bed)))

    def test_thin_pieces_are_fences_and_the_smallest_wins(self):
        post = tpl("Post fence", tags=("fence",))
        rail = tpl("Split-rail fence", size=(2, 1), tags=("fence",))
        self.assertIs(_pick_fence(catalogue(post, rail)), post)


class _MapCtx:
    """Just the field-name pool _place_fields reads from the map context."""

    def __init__(self):
        self.field_names = set()


def place_fields(pieces, seed):
    cat = catalogue(*pieces)
    rect = Rect(0, 0, 52, 40)
    out = ZoneOut(None, rect)
    _place_fields(None, rect, out, random.Random(seed), cat, _MapCtx())
    return out, cat


class TestPlacedPiecesFitTheirPlot(unittest.TestCase):
    def check(self, out, cat):
        """Every placement sits whole inside its plot, and no two pieces
        (expanded by their template's size) share a cell."""
        self.assertGreaterEqual(len(out.fields), 2, "no field plots were laid")
        plots = dict(out.fields)
        owner = {}
        for pl in out.props:
            w, h = cat[pl.template].size
            x, y = pl.pos
            self.assertTrue(plots[pl.region].contains_rect(Rect(x, y, w, h)),
                            f"{pl.template} at {(x, y)} escapes its plot")
            for c in ((xx, yy) for xx in range(x, x + w) for yy in range(y, y + h)):
                self.assertNotIn(c, owner, f"{pl.template} at {(x, y)} shares "
                                            f"{c} with {owner.get(c)}")
                owner[c] = pl.template

    def test_tall_fence_wide_crop(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                out, cat = place_fields(
                    (tpl("Wattle hurdle", size=(1, 2), tags=("fence",)),
                     tpl("Barley row", size=(2, 1), tags=("crop",))), seed)
                self.check(out, cat)
                placed = {pl.template for pl in out.props}
                self.assertIn("Wattle hurdle", placed)
                self.assertIn("Barley row", placed)

    def test_wide_fence_tall_crop(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                out, cat = place_fields(
                    (tpl("Split-rail fence", size=(2, 1), tags=("fence",)),
                     tpl("Bean row", size=(1, 2), tags=("crop",))), seed)
                self.check(out, cat)

    def test_bad_catalogue(self):
        """The catalogue that broke the live world: a 2x2 bed tagged 'fence'
        and a counter tagged 'shop' must not be laid by the field code."""
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                out, cat = place_fields(
                    (tpl("Wattled garden bed", size=(2, 2), tags=("plant", "fence")),
                     tpl("Elm tap counter", size=(3, 1), walkability=0.0,
                         tags=("counter", "furniture", "bar", "shop")),
                     tpl("Wheat seedling", tags=("crop",))), seed)
                self.check(out, cat)
                placed = {pl.template for pl in out.props}
                self.assertNotIn("Elm tap counter", placed)
                self.assertNotIn("Wattled garden bed", placed)
                self.assertIn("Wheat seedling", placed)


if __name__ == "__main__":
    unittest.main()
