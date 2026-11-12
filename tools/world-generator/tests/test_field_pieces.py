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


if __name__ == "__main__":
    unittest.main()
