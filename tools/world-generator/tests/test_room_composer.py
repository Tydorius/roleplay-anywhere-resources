"""The room composer: the bedroom and master recipes compose rooms that
pass the fixed-room checker at every clearance, keep the clearance gaps
between groups, never come out smaller at a higher clearance, and come
back the same for the same seed; the open style keeps a clear middle, a
symmetric recipe composes a symmetric chapel, Michael's sketch composes
at tight, and a recipe that cannot fit its size band says so."""
import json
import unittest

from worldgen import fixed_rooms as FR
from worldgen import library as WL
from worldgen import room_composer as RC
from worldgen import room_groups as RG

BEDROOMS = ("bedroom.small.a", "bedroom.medium.b")
MASTERS = ("bedroom.master.small.b", "bedroom.master.medium.b")
RECIPES = BEDROOMS + MASTERS


def area(room):
    return room["size"][0] * room["size"][1]


def instance_gaps(room):
    """The clearance between every pair of placed groups: how far apart the
    boxes are along the wider axis."""
    boxes = [inst["box"] for inst in FR.instances(room)]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            ax, ay, aw, ah = boxes[i]
            bx, by, bw, bh = boxes[j]
            sep_x = max(bx - (ax + aw), ax - (bx + bw))
            sep_y = max(by - (ay + ah), ay - (by + bh))
            yield max(sep_x, sep_y)


def touches_a_wall(room):
    w, h = room["size"]
    for p in room["pieces"]:
        x, y, pw, ph = p["at"] + p["size"]
        if y == 0 or y + ph == h or x == 0 or x + pw == w:
            return True
    return False


def sketch_recipe():
    """Michael's sketch: the couple bed, the dresser in front of it, the
    wardrobe and a lamp."""
    return {"layout": "bedroom.master.hand.sketch", "family": "bedroom.master",
            "sizeBands": ["small"],
            "groups": [
                {"group": "sleep.couple.bedside2", "kind": "anchor",
                 "count": "couples"},
                {"group": "storage.big.single.bedroom.master",
                 "kind": "required"},
                {"group": "storage.big.single.bedroom.master1",
                 "kind": "required"},
                {"group": "light.small.single.bedroom.master",
                 "kind": "optional"},
            ]}


def chapel_recipe():
    return {"layout": "chapel.hand.a", "family": "chapel",
            "sizeBands": ["medium"],
            "groups": [
                {"group": "altar.devotion2", "kind": "anchor"},
                {"group": "seat.long.single.chapel7", "kind": "repeatable",
                 "count": [1, 2]},
            ]}


class TestCompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def compose(self, recipe, clearance="tight", style="flush", seed=1, **kw):
        rooms, reason = RC.compose(recipe, self.data, clearance, style, seed,
                                   **kw)
        self.assertTrue(rooms, f"no rooms: {reason}")
        errors = FR.check(rooms, self.data, self.lib)
        self.assertEqual(errors, [], json.dumps(rooms[0], indent=1))
        return rooms

    def shipped(self, layout, **kw):
        return self.compose(self.data["recipes"][layout], **kw)

    def test_bedrooms_and_masters_compose_at_tight(self):
        for layout in RECIPES:
            rooms = self.shipped(layout)
            self.assertGreaterEqual(len(rooms), 1, layout)

    def test_the_anchor_stores_back_north(self):
        for layout in RECIPES:
            for room in self.shipped(layout):
                with self.subTest(layout=layout, room=room["id"]):
                    anchors = [p for p in room["pieces"]
                               if p.get("back") == "north"]
                    self.assertTrue(anchors)

    def test_no_empty_ring_along_the_walls(self):
        for layout in RECIPES:
            for room in self.shipped(layout):
                with self.subTest(layout=layout, room=room["id"]):
                    self.assertTrue(touches_a_wall(room),
                                    json.dumps(room["pieces"]))

    def test_deterministic_per_seed(self):
        for layout in RECIPES:
            for seed in (1, 2, 3):
                one = self.shipped(layout, seed=seed)
                two = self.shipped(layout, seed=seed)
                with self.subTest(layout=layout, seed=seed):
                    self.assertEqual(json.dumps(one, sort_keys=True),
                                     json.dumps(two, sort_keys=True))

    def test_higher_clearance_keeps_the_gaps(self):
        for layout in RECIPES:
            tight = self.shipped(layout, clearance="tight")[0]
            roomy = self.shipped(layout, clearance="roomy")
            grand = self.shipped(layout, clearance="grand")
            for rooms, gap in ((roomy, 2), (grand, 3)):
                with self.subTest(layout=layout, gap=gap):
                    for room in rooms:
                        self.assertTrue(instance_gaps(room))
                        for g in instance_gaps(room):
                            self.assertGreaterEqual(g, gap,
                                                    json.dumps(room["pieces"]))

    def test_higher_clearance_never_comes_out_smaller(self):
        for layout in RECIPES:
            tight = self.shipped(layout, clearance="tight")[0]
            roomy = self.shipped(layout, clearance="roomy")[0]
            grand = self.shipped(layout, clearance="grand")[0]
            with self.subTest(layout=layout):
                self.assertGreaterEqual(area(roomy), area(tight))
                self.assertGreaterEqual(area(grand), area(tight))

    def test_open_style_keeps_a_clear_middle(self):
        for layout in RECIPES:
            rooms = self.shipped(layout, clearance="roomy", style="open")
            for room in rooms:
                with self.subTest(layout=layout, room=room["id"]):
                    self.assertEqual(room["style"], "open")
                    fx, fy = room["filler"]["at"]
                    fw, fh = room["filler"]["size"]
                    self.assertGreaterEqual(fw, 2)
                    self.assertGreaterEqual(fh, 2)
                    w, h = room["size"]
                    occupied = {(x, y) for p in room["pieces"]
                                for x in range(p["at"][0], p["at"][0] + p["size"][0])
                                for y in range(p["at"][1], p["at"][1] + p["size"][1])}
                    cells = [(x, y) for x in range(fx, fx + fw)
                             for y in range(fy, fy + fh)]
                    self.assertTrue(all(0 <= x < w and 0 <= y < h
                                        and (x, y) not in occupied
                                        for x, y in cells))

    def test_symmetric_chapel(self):
        rooms = self.compose(chapel_recipe(), symmetric=True)
        for room in rooms:
            with self.subTest(room=room["id"]):
                self.assertTrue(room["symmetric"])

    def test_michaels_sketch_composes_at_tight(self):
        rooms = self.compose(sketch_recipe())
        best = rooms[0]
        self.assertLessEqual(best["size"][0], 6)
        self.assertLessEqual(best["size"][1], 6)
        beds = [i for i in FR.instances(best)
                if i["gid"] == "sleep.couple.bedside2"]
        dressers = [i for i in FR.instances(best)
                    if i["gid"] == "storage.big.single.bedroom.master"]
        self.assertTrue(beds and dressers)
        bx, by, bw, bh = beds[0]["box"]
        self.assertTrue(any(dy == by + bh + 1 and dx < bx + bw
                            and dx + dw > bx
                            for dx, dy, dw, dh in
                            (d["box"] for d in dressers)),
                        json.dumps(best["pieces"], indent=1))

    def test_a_recipe_that_cannot_fit_its_band_says_so(self):
        rooms, reason = RC.compose(sketch_recipe(), self.data, "tight",
                                   "flush", 1, size_band="tiny")
        self.assertEqual(rooms, [])
        self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
