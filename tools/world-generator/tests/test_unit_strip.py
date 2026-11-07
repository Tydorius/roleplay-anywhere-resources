"""A unit building's shared rooms that cannot sit side by side by its entrance.
Found by Ministral 3 14B's solo hamlet (November 2026): after 25 good calls it
listed the Old Salt Tavern's four guest rooms ("Unit_1".."Unit_4") as shared
rooms beside the one unit design, all seven went into an 11-cell strip, and the
build failed on furniture sitting on walls, on every seed. The strip now stacks
rooms when they don't fit, and P3's sanitizer drops numbered copies of the unit."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from tests import util
from worldgen import api, layout_building as lb, model, phases

LIVE = "live/frosthaven-ministral.plan.json"


def tavern(data):
    plan = model.parse_plan(data)
    tm = {t.name: t for t in plan.templates}
    design = next(b for z in plan.zones for b in z.buildings if b.name == "Old Salt Tavern")
    return design, tm


def strip_rooms(layout):
    return [r for r in layout.rooms if r.base_name != lb.UNIT_SPINE_NAME]


class TestStackedStrip(unittest.TestCase):
    def setUp(self):
        self.design, self.tm = tavern(util.load_plan(LIVE))
        w, h = lb.units_footprint(self.design, self.tm)
        self.rect = model.Rect(0, 0, w, h)
        import random
        self.layout = lb.layout_units(self.design, self.rect, random.Random(1), self.tm)

    def test_every_shared_room_is_wide_enough_to_furnish(self):
        rooms = strip_rooms(self.layout)
        self.assertEqual(len(rooms), 7)
        for r in rooms:
            self.assertGreaterEqual(min(r.rect.w, r.rect.h), lb.MIN_SIDE, r.base_name)

    def test_shared_rooms_stay_inside_the_block_and_apart(self):
        rooms = strip_rooms(self.layout)
        corridor = next(r for r in self.layout.rooms if r.base_name == lb.UNIT_SPINE_NAME)
        for r in rooms:
            self.assertTrue(self.rect.contains_cell((r.rect.x, r.rect.y)), r.base_name)
            self.assertTrue(self.rect.contains_cell((r.rect.x1, r.rect.y1)), r.base_name)
            self.assertFalse(r.rect.intersects(corridor.rect), r.base_name)
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                self.assertFalse(a.rect.intersects(b.rect), f"{a.base_name} / {b.base_name}")

    def test_every_shared_room_has_a_door(self):
        for r in strip_rooms(self.layout):
            self.assertTrue(r.doors, r.base_name)

    def test_rooms_that_fit_keep_the_one_row_strip(self):
        # the apartment fixture's lobby fits beside the corridor: unchanged
        data = util.load_plan("apartment-block.plan.json")
        plan = model.parse_plan(data)
        tm = {t.name: t for t in plan.templates}
        d = next(b for z in plan.zones for b in z.buildings if b.units)
        uw, uh = lb._unit_size(d, tm)
        along = uw if d.entrance_side in ("south", "north") else uh
        depth, sides = lb._strip_plan(d, tm, along)
        self.assertEqual(depth, lb._shared_strip_height(d, tm, along))
        self.assertTrue(all(len(rows) <= 1 for rows in sides))


class TestLiveTavernBuilds(unittest.TestCase):
    def test_the_failed_world_builds_on_several_seeds(self):
        tmp = tempfile.mkdtemp(prefix="worldgen-unit-strip-")
        try:
            for seed in (1, 3):
                with self.subTest(seed=seed):
                    s = api._layout_and_build(util.load_plan(LIVE), seed=seed,
                                              out_dir=os.path.join(tmp, str(seed)))
                    self.assertTrue(s["ok"], s)
                    self.assertEqual(s["validator_errors"], 0, s)
                    self.assertEqual(s["reachability"], 1.0, s)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDropUnitCopies(unittest.TestCase):
    TEMPLATES = ["wooden_table", "single_bed", "lantern"]

    def reply(self, shared):
        return {
            "wall": "wood", "ground": "wood",
            "rooms": [{"name": n, "share": "small"} for n in shared],
            "connections": [["Common Room", n] for n in shared[1:]],
            "entrance": {"room": shared[0], "side": "south"},
            "furniture": [{"template": "single_bed" if "Unit" in n or "Room " in n
                           else "wooden_table", "room": n, "count": 1} for n in shared],
            "unit": {"rooms": [{"name": "Guest Room", "share": "small"}],
                     "connections": [], "entrance": {"room": "Guest Room", "side": "south"},
                     "furniture": [{"template": "single_bed", "room": "Guest Room",
                                    "count": 1}]},
        }

    def test_numbered_copies_are_dropped_with_their_furniture(self):
        log = []
        shared = ["Common Room", "Kitchen", "Unit_1", "Unit_2", "Guest Room 3", "Room 4"]
        d = phases.sanitize_p3(self.reply(shared), "Old Salt Tavern", self.TEMPLATES, log,
                               units={"name": "Room", "count": 4, "residents": 2})
        self.assertEqual([r["name"] for r in d["rooms"]], ["Common Room", "Kitchen"])
        self.assertEqual({f["room"] for f in d["furniture"]}, {"Common Room", "Kitchen"})
        self.assertEqual(d["connections"], [["Common Room", "Kitchen"]])
        self.assertTrue(any("numbered copies of the unit" in r for (_w, r) in log))
        self.assertFalse(any("unknown template or room" in r for (_w, r) in log))

    def test_other_numbered_rooms_stay(self):
        log = []
        shared = ["Common Room", "Storeroom 2", "Office 1"]
        d = phases.sanitize_p3(self.reply(shared), "Old Salt Tavern", self.TEMPLATES, log,
                               units={"name": "Room", "count": 4})
        self.assertEqual([r["name"] for r in d["rooms"]], shared)

    def test_a_plain_building_keeps_numbered_rooms(self):
        log = []
        reply = self.reply(["Common Room", "Unit_1"])
        reply.pop("unit")
        d = phases.sanitize_p3(reply, "Old Salt Tavern", self.TEMPLATES, log)
        self.assertEqual([r["name"] for r in d["rooms"]], ["Common Room", "Unit_1"])

    def test_a_reply_of_only_copies_keeps_them(self):
        log = []
        d = phases.sanitize_p3(self.reply(["Unit_1", "Unit_2"]), "Old Salt Tavern",
                               self.TEMPLATES, log, units=True)
        self.assertEqual([r["name"] for r in d["rooms"]], ["Unit_1", "Unit_2"])


if __name__ == "__main__":
    unittest.main()
