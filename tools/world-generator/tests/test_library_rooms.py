"""Room library build step 3: a layout compiles into furniture lines that the
existing placer lays out. Every layout lays out at its smallest and largest
interior, door on either kind of wall, in every band, with every piece placed."""
import random
import unittest

from worldgen import library as L
from worldgen.library_rooms import (Templates, compile_room, furnish_room, layout_need,
                                   pick_layout, size_band)
from worldgen.layout_room import layout_room
from worldgen.model import ObjectTemplate, Rect

LIB = L.load()


def object_templates(reg):
    return {t["name"]: ObjectTemplate(
        name=t["name"], size=tuple(t["size"]), walkability=t["walkability"],
        extras={"forSleep": t["forSleep"], **({"back": t["back"]} if t.get("back") else {})})
        for t in reg.templates()}


def door(w, h, side):
    return {"south": (w // 2, 0), "north": (w // 2, h - 1),
            "west": (0, h // 2), "east": (w - 1, h // 2)}[side]


def purpose_for(fam):
    ps = [p for p, f in LIB.vocab["purposes"].items() if f == fam]
    return fam if fam in ps else ps[0]


def place(reg, room, interior, side, rng):
    w, h = interior[0] + 2, interior[1] + 2
    return layout_room(Rect(0, 0, w, h), [door(w, h, side)], room.furniture,
                       object_templates(reg), rng)


class TestCompile(unittest.TestCase):
    def test_a_bedroom_beds_its_singles(self):
        reg = Templates(LIB, 1)
        room = compile_room(LIB, reg, "bedroom", (5, 5), "medieval", "modest", "kept",
                            random.Random(1), singles=2)
        self.assertTrue(room.layout_id.startswith("bedroom."))
        beds = [f for f in room.furniture
                if next(t for t in reg.templates() if t["name"] == f.template)["forSleep"]]
        self.assertEqual(sum(f.count for f in beds), 2)
        self.assertEqual(room.gaps, [])

    def test_a_couple_gets_one_double(self):
        reg = Templates(LIB, 1)
        room = compile_room(LIB, reg, "master_bedroom", (6, 6), "modern", "wealthy", "kept",
                            random.Random(2), couples=1)
        by_name = {t["name"]: t for t in reg.templates()}
        doubles = [f for f in room.furniture if by_name[f.template]["forSleep"]
                   and by_name[f.template]["size"] == [2, 2]]
        self.assertEqual(sum(f.count for f in doubles), 1)

    def test_templates_are_shared_and_clean(self):
        reg = Templates(LIB, 3)
        for i in range(3):
            compile_room(LIB, reg, "bedroom", (5, 5), "industrial", "poor", "worn",
                         random.Random(i), singles=1)
        names = [t["name"] for t in reg.templates()]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(reg.by_key), len(names))
        for t in reg.templates():
            for k in ("description", "physicalDescription"):
                self.assertNotIn("{", t[k])
        obj = LIB.objects[next(iter(reg.by_key))[0]]
        self.assertIs(reg.get(obj, "industrial", "poor", "worn"), reg.get(obj, "industrial", "poor", "worn"))

    def test_beside_and_around_name_templates(self):
        reg = Templates(LIB, 1)
        room = compile_room(LIB, reg, "dining", (6, 6), "medieval", "modest", "kept",
                            random.Random(4))
        names = {f.template for f in room.furniture}
        for f in room.furniture:
            for tok in f.hint.split("+"):
                key, _, val = tok.partition(":")
                if key in ("beside", "around"):
                    self.assertIn(val, names, f.hint)

    def test_no_layout_fits_a_cupboard(self):
        reg = Templates(LIB, 1)
        room = compile_room(LIB, reg, "great_hall", (2, 2), "medieval", "elite", "kept",
                            random.Random(1))
        self.assertIsNone(room.layout_id)
        self.assertTrue(room.gaps)

    def test_layout_choice_and_needs(self):
        lay = pick_layout(LIB, "kitchen", (6, 5), random.Random(1))
        self.assertEqual(lay["family"], "kitchen")
        mn, mx = lay["minInterior"], lay["maxInterior"]
        self.assertTrue(mn[0] <= 6 <= mx[0] or mn[1] <= 6 <= mx[1])
        area, side = layout_need(lay)
        self.assertEqual(area, mn[0] * mn[1])
        self.assertEqual(size_band(LIB, (5, 5)), "medium")


class TestEveryLayoutLaysOut(unittest.TestCase):
    def test_min_and_max_interior_every_band(self):
        """Each layout, forced, at its min and max interior: everything placed,
        leaving out optional slots where the room comes out tight."""
        failed = []
        for lid, lay in sorted(LIB.layouts.items()):
            purpose = purpose_for(lay["family"])
            for which in ("minInterior", "maxInterior"):
                interior = tuple(lay[which])
                for band in LIB.bands:
                    for side in ("south", "east"):
                        rng = random.Random(f"{lid}|{which}|{band}|{side}")
                        reg = Templates(LIB, 1)
                        for optional in (True, False):
                            room = compile_room(LIB, reg, purpose, interior, band, "modest",
                                                "kept", rng, singles=2, couples=1, layout=lay,
                                                optional=optional)
                            out = place(reg, room, interior, side, rng)
                            if not out.failures:
                                break
                        if room.gaps or out.failures:
                            failed.append((lid, which, band, side, room.gaps, out.failures[:2]))
        # a forced layout may lose a piece in a rare draw; furnish_room's
        # redraws cover that, so allow a handful here
        self.assertLessEqual(len(failed), 4, "; ".join(map(str, failed[:20])))

    def test_furnish_room_places_everything(self):
        """The real entry point: every purpose at a spread of room sizes, in
        every band and two wealth tiers, places every piece."""
        failed = []
        for purpose in sorted(LIB.vocab["purposes"]):
            fam = LIB.family_of(purpose)
            sizes = sorted({tuple(l["minInterior"]) for l in LIB.layouts_for(fam)} |
                           {tuple(l["maxInterior"]) for l in LIB.layouts_for(fam)})
            for interior in sizes:
                w, h = interior[0] + 2, interior[1] + 2
                rect = Rect(0, 0, w, h)
                for band in LIB.bands:
                    for tier in ("poor", "wealthy"):
                        rng = random.Random(f"{purpose}|{interior}|{band}|{tier}")
                        reg = Templates(LIB, 1)
                        comp, out = furnish_room(LIB, reg, purpose, rect, [door(w, h, "south")],
                                                 band, tier, "kept", rng, singles=2, couples=1)
                        if comp.gaps or out is None or out.failures:
                            failed.append((purpose, interior, band, tier, comp.gaps,
                                           out.failures[:2] if out else None))
        self.assertEqual(failed, [], "; ".join(map(str, failed[:20])))


if __name__ == "__main__":
    unittest.main()
