"""Two plans from the small-model runs of November 2026 that cost a full run and
then failed the build: Deckard's east-west inn, whose wing could not be reached,
and Nano's hamlet, sealed as if it were a starship."""
import copy
import types
import unittest

import worldgen
from tests import util
from worldgen import phases
from worldgen.layout_compound import _spine_geometry, _spine_side


def part(name, kind, side="", index=0):
    return types.SimpleNamespace(building=name, slot_kind=kind, side=side, index=index,
                                 gate=False, host=None)


def geometry(parts, sizes, axis, hub_pos="start", width=3):
    every = ("north", "south", "east", "west")
    plans = {p.building: (None, "", {s: sizes[p.building] for s in every}) for p in parts}
    c = types.SimpleNamespace(parts=parts, spine_width=width, axis=axis, hub_pos=hub_pos,
                              shape="spine", name="The Spine")
    return _spine_geometry(c, plans)[1]


class TestEastWestSpine(unittest.TestCase):
    PARTS = [part("Hub", "hub"), part("A", "spine", "right", 0), part("B", "spine", "right", 1)]
    SIZES = {"Hub": (25, 18), "A": (25, 15), "B": (24, 17)}   # Deckard's inn

    def test_parts_keep_the_size_they_are_built_at(self):
        placed = geometry(self.PARTS, self.SIZES, "ew")["placements"]
        for name, size in self.SIZES.items():
            self.assertEqual((placed[name].w, placed[name].h), size, name)

    def test_nothing_overlaps(self):
        for hub_pos in ("start", "center", "end"):
            with self.subTest(hub_pos):
                geo = geometry(self.PARTS, self.SIZES, "ew", hub_pos)
                rects = list(geo["placements"].items()) + \
                    [(f"corridor {i}", r) for i, r in enumerate(geo["corridors"])]
                for i, (a, ra) in enumerate(rects):
                    for b, rb in rects[i + 1:]:
                        self.assertFalse(ra.intersects(rb), f"{a} overlaps {b}")

    def test_a_start_cap_faces_along_the_spine(self):
        self.assertEqual(_spine_side(part("Cap", "spine_end", "start"), "ew"), "east")
        self.assertEqual(_spine_side(part("Cap", "spine_end", "end"), "ew"), "west")
        self.assertEqual(_spine_side(part("Cap", "spine_end", "start"), "ns"), "north")
        self.assertEqual(_spine_side(part("Cap", "spine_end", "end"), "ns"), "south")

    def test_a_whole_east_west_hospital_can_be_walked(self):
        plan = copy.deepcopy(util.load_plan("hospital-spine.plan.json"))
        for c in plan["compounds"]:
            c["axis"] = "ew"
        world = worldgen.run(plan, seed=1)
        self.assertEqual(world.metrics["errors"]["dropped"], [])
        rooms = world.metrics["rooms"]
        self.assertEqual(rooms["reachable"], rooms["total"], rooms["unreachable"])
        self.assertEqual(world.metrics["region_overlaps"], [])


class TestVoidNeedsACompound(unittest.TestCase):
    def plan(self, compounds=()):
        return {"name": "Frostshore", "mapSize": "small", "compounds": list(compounds),
                "zones": [{"name": "Dock", "sizeClass": "small", "exterior": "void",
                           "buildings": [{"name": "Boat Shed", "kind": "shed",
                                          "sizeClass": "small", "purpose": "boats"}]}]}

    def test_a_lone_building_opens_the_zone(self):
        log = []
        d = phases.sanitize_p1(self.plan(), log)
        self.assertNotIn("exterior", d["zones"][0])
        self.assertTrue(any("Boat Shed" in reason for _what, reason in log), log)

    def test_every_building_in_a_compound_stays_sealed(self):
        hull = {"name": "Hull", "zone": "Dock", "shape": "cluster",
                "parts": [{"building": "Boat Shed", "at": "spine:hub"}]}
        log = []
        d = phases.sanitize_p1(self.plan([hull]), log)
        self.assertEqual(d["zones"][0].get("exterior"), "void")

    def test_the_void_fixtures_stay_sealed(self):
        for name in ("ship-void.plan.json", "starship-decks.plan.json"):
            with self.subTest(name):
                d = copy.deepcopy(util.load_plan(name))
                phases.open_void_zones(d, [])
                self.assertTrue(all(z.get("exterior") == "void" for z in d["zones"]))


if __name__ == "__main__":
    unittest.main()
