"""The generated room library: the shipped bedroom, master bedroom and
washroom rooms load and check clean, stay inside the family's aspect cap
with no dead floor, every recipe of those families keeps at least one tight
flush room, every open room's filler stays off every edge and holds its
clearance cap, the two-to-one aspect and the centre, no room wastes more
than one line along a wall, the generator comes back the same for the same
seed, and ids are unique and follow the family.band.letter.clearance
.style pattern."""
import importlib.util
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)

from worldgen import fixed_rooms as FR      # noqa: E402
from worldgen import library as WL          # noqa: E402
from worldgen import room_composer as RC    # noqa: E402
from worldgen import room_groups as RG      # noqa: E402

FAMILIES = ("bedroom", "bedroom.master", "washroom")
ID_PATTERN = re.compile(
    r"\.(tiny|small|medium|large)\.([a-z])\.(tight|roomy|grand)\."
    r"(flush|open)$")

_SPEC = importlib.util.spec_from_file_location(
    "generate_rooms", os.path.join(GEN, "library-seed", "generate_rooms.py"))
generate_rooms = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generate_rooms)


def empty_edge_lines(room):
    """How many full lines sit empty along each wall (the consecutive rows
    from the north, and so on, with no piece and no filler cell on them)."""
    w, h = room["size"]
    taken = {(x, y) for p in room["pieces"]
             for x in range(p["at"][0], p["at"][0] + p["size"][0])
             for y in range(p["at"][1], p["at"][1] + p["size"][1])}
    f = room.get("filler")
    if f:
        fx, fy = f["at"]
        fw, fh = f["size"]
        taken |= {(x, y) for x in range(fx, fx + fw) for y in range(fy, fy + fh)}
    rows = [not any((x, y) in taken for x in range(w)) for y in range(h)]
    cols = [not any((x, y) in taken for y in range(h)) for x in range(w)]

    def leading(line):
        n = 0
        for v in line:
            if not v:
                break
            n += 1
        return n

    return {"north": leading(rows), "south": leading(reversed(rows)),
            "west": leading(cols), "east": leading(reversed(cols))}


class TestShippedRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(GEN, "library", "rooms", "bedroom.json"),
                  encoding="utf-8") as fh:
            cls.bedrooms = json.load(fh)["rooms"]
        with open(os.path.join(GEN, "library", "rooms", "bedroom.master.json"),
                  encoding="utf-8") as fh:
            cls.masters = json.load(fh)["rooms"]
        with open(os.path.join(GEN, "library", "rooms", "washroom.json"),
                  encoding="utf-8") as fh:
            cls.washrooms = json.load(fh)["rooms"]

    def test_the_shipped_rooms_load_and_check_clean(self):
        rooms = FR.load()
        self.assertGreater(len(rooms), 0)
        self.assertEqual(FR.check(rooms, RG.load(), WL.load()), [])

    def test_every_shipped_room_stays_inside_the_aspect_cap(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms):
            for room in rooms:
                w, h = room["size"]
                with self.subTest(room=room["id"]):
                    self.assertLessEqual(
                        max(w, h), RC.aspect_cap(room["family"]) * min(w, h),
                        f"{w}x{h}: the long side may be at most "
                        f"{RC.aspect_cap(room['family']):g}x the short side")

    def test_no_shipped_room_has_dead_floor(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms):
            for room in rooms:
                with self.subTest(room=room["id"]):
                    self.assertEqual(FR.dead_cells(room), [])

    def test_every_recipe_keeps_a_tight_flush_room(self):
        data = RG.load()
        recipes = {r["layout"] for r in data["recipes"].values()
                   if r.get("family") in FAMILIES}
        kept = {r["recipe"] for rooms in (self.bedrooms, self.masters,
                                          self.washrooms)
                for r in rooms
                if r["clearance"] == "tight" and r["style"] == "flush"}
        self.assertEqual(recipes - kept, set(),
                         f"recipes without a tight flush room: "
                         f"{sorted(recipes - kept)}")

    def test_open_fillers_stay_off_every_edge(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms):
            for room in rooms:
                if room["style"] != "open":
                    continue
                with self.subTest(room=room["id"]):
                    fx, fy = room["filler"]["at"]
                    fw, fh = room["filler"]["size"]
                    w, h = room["size"]
                    self.assertGreaterEqual(fw, 2)
                    self.assertGreaterEqual(fh, 2)
                    self.assertGreater(fx, 0)
                    self.assertGreater(fy, 0)
                    self.assertLess(fx + fw, w)
                    self.assertLess(fy + fh, h)

    def test_open_fillers_hold_the_cap_aspect_and_centre(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms):
            for room in rooms:
                if room["style"] != "open":
                    continue
                with self.subTest(room=room["id"]):
                    fx, fy = room["filler"]["at"]
                    fw, fh = room["filler"]["size"]
                    w, h = room["size"]
                    hi, lo = RC.FILLER_MAX[room["clearance"]]
                    self.assertLessEqual(max(fw, fh), hi,
                                         f"{fw}x{fh}: over the "
                                         f"{room['clearance']} cap {hi}x{lo}")
                    self.assertLessEqual(min(fw, fh), lo)
                    self.assertLessEqual(max(fw, fh),
                                         RC.FILLER_ASPECT * min(fw, fh),
                                         f"{fw}x{fh}: long side over "
                                         f"{RC.FILLER_ASPECT:g}x the short")
                    self.assertLessEqual(abs(fx - (w - fx - fw)), 1,
                                         "west and east wall distances "
                                         "differ by more than 1")
                    self.assertLessEqual(abs(fy - (h - fy - fh)), 1,
                                         "north and south wall distances "
                                         "differ by more than 1")

    def test_no_room_wastes_more_than_one_line_along_a_wall(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms):
            for room in rooms:
                counts = empty_edge_lines(room)
                for side, k in counts.items():
                    with self.subTest(room=room["id"], side=side):
                        self.assertLessEqual(k, 1)

    def test_ids_are_unique_and_follow_the_pattern(self):
        seen = {}
        for fam, rooms in (("bedroom", self.bedrooms),
                           ("bedroom.master", self.masters),
                           ("washroom", self.washrooms)):
            for room in rooms:
                with self.subTest(room=room["id"]):
                    self.assertTrue(room["id"].startswith(fam + "."),
                                    room["id"])
                    m = ID_PATTERN.search(room["id"])
                    self.assertTrue(m, room["id"])
                    self.assertEqual(m.group(1), room["sizeBand"])
                    self.assertEqual(m.group(3), room["clearance"])
                    self.assertEqual(m.group(4), room["style"])
                    self.assertNotIn(room["id"], seen)
                    seen[room["id"]] = fam
        self.assertEqual(len(seen),
                         sum(map(len, (self.bedrooms, self.masters,
                                       self.washrooms))))


class TestGenerator(unittest.TestCase):
    def test_generating_twice_comes_back_the_same(self):
        rooms, drops = generate_rooms.generate()
        again, drops_again = generate_rooms.generate()
        self.assertEqual(json.dumps(rooms, sort_keys=True),
                         json.dumps(again, sort_keys=True))
        self.assertEqual(drops, drops_again)


if __name__ == "__main__":
    unittest.main()
