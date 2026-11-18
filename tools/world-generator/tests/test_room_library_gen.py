"""The generated room library: the shipped bedroom, master bedroom,
washroom, privy and bath rooms load and check clean, stay inside the
family's aspect cap with no dead floor, hold the wash families' fixtures
(a washroom all three, a privy no bath, a bath room no toilet), every
recipe of those families keeps at least one tight flush room except the
two washroom recipes the generator skips for lacking a bath, every grand
room carries a luxury group from its family's pool within the per-kind
limits, never doubles a desk, bed or fire, has more pieces than its roomy
sibling and stays at or under 8 cells of floor per piece and within the
grand area ratio of its roomy sibling, every open room's filler stays off
every edge and holds its clearance cap, the two-to-one aspect and the
centre, no room wastes more than one line along a wall, the generator
comes back the same for the same seed, and ids are unique and follow the
family.band.letter.clearance.style pattern. Hand work in a temp copy of
the files survives regeneration: a hand room is kept as it stands with
its letter taken, its generated duplicate dropped, a surviving room's
edited description kept, and a second run changes nothing."""
import importlib.util
import json
import math
import os
import re
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)

from worldgen import fixed_rooms as FR      # noqa: E402
from worldgen import library as WL          # noqa: E402
from worldgen import room_composer as RC    # noqa: E402
from worldgen import room_groups as RG      # noqa: E402

FAMILIES = ("bedroom", "bedroom.master", "washroom", "privy", "bath")
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
        with open(os.path.join(GEN, "library", "rooms", "privy.json"),
                  encoding="utf-8") as fh:
            cls.privies = json.load(fh)["rooms"]
        with open(os.path.join(GEN, "library", "rooms", "bath.json"),
                  encoding="utf-8") as fh:
            cls.baths = json.load(fh)["rooms"]

    def test_the_shipped_rooms_load_and_check_clean(self):
        rooms = FR.load()
        self.assertGreater(len(rooms), 0)
        self.assertEqual(FR.check(rooms, RG.load(), WL.load()), [])

    def test_every_shipped_room_stays_inside_the_aspect_cap(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            for room in rooms:
                w, h = room["size"]
                with self.subTest(room=room["id"]):
                    self.assertLessEqual(
                        max(w, h), RC.aspect_cap(room["family"]) * min(w, h),
                        f"{w}x{h}: the long side may be at most "
                        f"{RC.aspect_cap(room['family']):g}x the short side")

    def test_no_shipped_room_has_dead_floor(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            for room in rooms:
                with self.subTest(room=room["id"]):
                    self.assertEqual(FR.dead_cells(room), [])

    def test_every_washroom_holds_all_three_fixtures(self):
        for room in self.washrooms:
            roles = {p["role"] for p in room["pieces"]}
            with self.subTest(room=room["id"]):
                self.assertTrue({"wash.toilet", "wash.bath", "wash.basin"}
                                <= roles, sorted(roles))

    def test_every_privy_holds_a_toilet_and_no_bath(self):
        for room in self.privies:
            roles = {p["role"] for p in room["pieces"]}
            with self.subTest(room=room["id"]):
                self.assertIn("wash.toilet", roles)
                self.assertNotIn("wash.bath", roles)

    def test_every_bath_room_holds_a_bath_and_no_toilet(self):
        for room in self.baths:
            roles = {p["role"] for p in room["pieces"]}
            with self.subTest(room=room["id"]):
                self.assertIn("wash.bath", roles)
                self.assertNotIn("wash.toilet", roles)

    def test_every_recipe_keeps_a_tight_flush_room(self):
        data = RG.load()
        recipes = {r["layout"] for r in data["recipes"].values()
                   if r.get("family") in FAMILIES}
        kept = {r["recipe"] for rooms in (self.bedrooms, self.masters,
                                          self.washrooms, self.privies,
                                          self.baths)
                for r in rooms
                if r["clearance"] == "tight" and r["style"] == "flush"}
        # the two washroom recipes whose groups cannot give a room all
        # three fixtures are skipped whole (their rooms are the privy's)
        skipped = {"washroom.tiny.a", "washroom.tiny.c"}
        self.assertEqual(recipes - kept, skipped,
                         f"recipes without a tight flush room: "
                         f"{sorted(recipes - kept)}")

    def test_every_grand_room_keeps_a_luxury_group(self):
        data = RG.load()
        pools = {fam: {e["group"] for e in entries}
                 for fam, entries in (data.get("pools") or {}).items()}
        for rooms, fam in ((self.bedrooms, "bedroom"),
                           (self.masters, "bedroom.master"),
                           (self.washrooms, "washroom"),
                           (self.privies, "privy"),
                           (self.baths, "bath")):
            for room in rooms:
                if room["clearance"] != "grand":
                    continue
                with self.subTest(room=room["id"]):
                    self.assertTrue(
                        any(p.get("group") in pools.get(fam, ())
                            for p in room["pieces"]),
                        "no piece comes from the family's luxury pool")

    def test_grand_rooms_stay_within_the_luxury_limits(self):
        data = RG.load()
        kinds_of = {gid: RG.luxury_kinds(g) for gid, g in data["groups"].items()}
        pools = {fam: {e["group"] for e in entries}
                 for fam, entries in (data.get("pools") or {}).items()}
        for rooms, fam in ((self.bedrooms, "bedroom"),
                           (self.masters, "bedroom.master"),
                           (self.washrooms, "washroom"),
                           (self.privies, "privy"),
                           (self.baths, "bath")):
            for room in rooms:
                if room["clearance"] != "grand":
                    continue
                counts, decor_pieces = {}, 0
                for gid in {p.get("group") for p in room["pieces"]} & pools[fam]:
                    for kind in kinds_of[gid]:
                        counts[kind] = counts.get(kind, 0) + 1
                    if "decor" in kinds_of[gid]:
                        decor_pieces += sum(1 for p in room["pieces"]
                                            if p.get("group") == gid)
                for kind, n in counts.items():
                    with self.subTest(room=room["id"], kind=kind):
                        self.assertLessEqual(n, RC.LUXURY_LIMITS[kind],
                                             f"{n} groups of {kind}")
                with self.subTest(room=room["id"], kind="decor pieces"):
                    self.assertLessEqual(decor_pieces, RC.LUXURY_DECOR_PIECES)

    def test_no_room_doubles_a_desk_bed_or_fire(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            for room in rooms:
                desks = sum(1 for p in room["pieces"] if p["role"] == "desk")
                beds = sum(1 for p in room["pieces"]
                           if p["role"] in ("sleep", "sleep.couple"))
                fires = sum(1 for p in room["pieces"]
                            if p["role"] in ("heat", "hearth"))
                with self.subTest(room=room["id"]):
                    self.assertLessEqual(desks, 1, f"{desks} desks")
                    self.assertLessEqual(beds, 1, f"{beds} beds")
                    self.assertLessEqual(fires, 1, f"{fires} fires")

    def test_grand_rooms_stay_within_the_area_ratio(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            roomy = {(r["recipe"], r["style"]): r["size"][0] * r["size"][1]
                     for r in rooms if r["clearance"] == "roomy"}
            for room in rooms:
                if room["clearance"] != "grand":
                    continue
                with self.subTest(room=room["id"]):
                    self.assertIn((room["recipe"], room["style"]), roomy,
                                  "no roomy sibling to size against")
                    w, h = room["size"]
                    cap = math.ceil(RC.GRAND_AREA_RATIO
                                    * roomy[(room["recipe"], room["style"])])
                    self.assertLessEqual(w * h, cap,
                                         f"{w}x{h} = {w * h} cells over the "
                                         f"cap of {cap}")

    def test_every_grand_room_outranks_its_roomy_sibling(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            roomy = {(r["recipe"], r["style"]): len(r["pieces"])
                     for r in rooms if r["clearance"] == "roomy"}
            for room in rooms:
                if room["clearance"] != "grand":
                    continue
                with self.subTest(room=room["id"]):
                    self.assertIn((room["recipe"], room["style"]), roomy,
                                  "no roomy sibling to outdo")
                    self.assertGreater(
                        len(room["pieces"]),
                        roomy[(room["recipe"], room["style"])])

    def test_every_grand_room_stays_under_eight_cells_per_piece(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            for room in rooms:
                if room["clearance"] != "grand":
                    continue
                w, h = room["size"]
                with self.subTest(room=room["id"]):
                    self.assertLessEqual(
                        w * h, 8 * len(room["pieces"]),
                        f"{w * h} cells over {len(room['pieces'])} pieces = "
                        f"{w * h / len(room['pieces']):.1f} cells per piece")

    def test_open_fillers_stay_off_every_edge(self):
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
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
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
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
        for rooms in (self.bedrooms, self.masters, self.washrooms,
                           self.privies, self.baths):
            for room in rooms:
                counts = empty_edge_lines(room)
                for side, k in counts.items():
                    with self.subTest(room=room["id"], side=side):
                        self.assertLessEqual(k, 1)

    def test_ids_are_unique_and_follow_the_pattern(self):
        seen = {}
        for fam, rooms in (("bedroom", self.bedrooms),
                           ("bedroom.master", self.masters),
                           ("washroom", self.washrooms),
                           ("privy", self.privies),
                           ("bath", self.baths)):
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
                                       self.washrooms, self.privies,
                                       self.baths))))


class TestGenerator(unittest.TestCase):
    def test_generating_twice_comes_back_the_same(self):
        rooms, drops = generate_rooms.generate()
        again, drops_again = generate_rooms.generate()
        self.assertEqual(json.dumps(rooms, sort_keys=True),
                         json.dumps(again, sort_keys=True))
        self.assertEqual(drops, drops_again)


class TestHandRooms(unittest.TestCase):
    """Hand work in a temp copy of the shipped rooms: a "source": "hand"
    room survives a regeneration unchanged with its id's letter taken, a
    generated room equal to it after any turn or mirror is dropped in its
    favour, a generated room whose id survives keeps the fields in its
    "edited" list, and regenerating the generated files changes nothing."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.rooms_dir = os.path.join(tmp.name, "rooms")
        os.makedirs(self.rooms_dir)
        for fam in FAMILIES:
            shutil.copyfile(
                os.path.join(GEN, "library", "rooms", f"{fam}.json"),
                os.path.join(self.rooms_dir, f"{fam}.json"))

    def shipped(self, fam):
        with open(os.path.join(self.rooms_dir, f"{fam}.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)["rooms"]

    def write(self, fam, rooms):
        with open(os.path.join(self.rooms_dir, f"{fam}.json"), "w",
                  encoding="utf-8", newline="\n") as fh:
            json.dump({"rooms": rooms}, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    def hand_copy(self, rooms):
        """The family's first shipped room as a hand room under a free letter
        of its own band, clearance and style."""
        hand = json.loads(json.dumps(rooms[0]))
        bits = hand["id"].split(".")
        bits[2] = "z"
        hand["id"] = ".".join(bits)
        hand["source"] = "hand"
        hand["description"] = "A hand-made room."
        return hand

    def test_a_hand_room_survives_unchanged_and_keeps_its_letter(self):
        rooms = self.shipped("bedroom")
        hand = self.hand_copy(rooms)
        self.write("bedroom", rooms + [hand])
        out, _drops = generate_rooms.generate(["bedroom"],
                                              rooms_dir=self.rooms_dir)
        by_id = {r["id"]: r for r in out["bedroom"]}
        self.assertIn(hand["id"], by_id)
        self.assertEqual(by_id[hand["id"]], hand)
        group = (hand["sizeBand"], hand["clearance"], hand["style"])
        zs = [r for r in out["bedroom"]
              if (r["sizeBand"], r["clearance"], r["style"]) == group
              and r["id"].split(".")[2] == "z"]
        self.assertEqual(len(zs), 1, "another room took the hand room's letter")

    def test_a_generated_duplicate_of_a_hand_room_is_dropped(self):
        rooms = self.shipped("bedroom")
        hand = self.hand_copy(rooms)
        self.write("bedroom", rooms + [hand])
        out, _drops = generate_rooms.generate(["bedroom"],
                                              rooms_dir=self.rooms_dir)
        shape = generate_rooms.canonical(hand)
        alike = [r["id"] for r in out["bedroom"]
                 if generate_rooms.canonical(r) == shape]
        self.assertEqual(alike, [hand["id"]])

    def test_a_surviving_room_keeps_its_edited_description(self):
        rooms = self.shipped("bedroom")
        target = json.loads(json.dumps(rooms[0]))
        target["edited"] = ["description"]
        target["description"] = "Described by hand."
        rooms[0] = target
        self.write("bedroom", rooms)
        out, _drops = generate_rooms.generate(["bedroom"],
                                              rooms_dir=self.rooms_dir)
        by_id = {r["id"]: r for r in out["bedroom"]}
        self.assertIn(target["id"], by_id)
        self.assertEqual(by_id[target["id"]]["description"],
                         "Described by hand.")
        self.assertEqual(by_id[target["id"]]["edited"], ["description"])

    def test_generating_the_generated_files_changes_nothing(self):
        rooms = self.shipped("bedroom")
        hand = self.hand_copy(rooms)
        self.write("bedroom", rooms + [hand])
        first, _drops = generate_rooms.generate(["bedroom"],
                                                rooms_dir=self.rooms_dir)
        self.write("bedroom", first["bedroom"])
        second, _drops_again = generate_rooms.generate(["bedroom"],
                                                       rooms_dir=self.rooms_dir)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
