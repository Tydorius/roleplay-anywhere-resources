"""The fixed rooms: a hand-made room checks clean, every check catches its
own hand-broken copy, the use-side table matches the design, turning four
times returns the same room while every turn and mirror still checks, and
the shipped rooms folder loads clean."""
import json
import os
import tempfile
import unittest

from worldgen import fixed_rooms as FR
from worldgen import library as WL
from worldgen import room_groups as RG


def piece(role, size, at, group, back=None):
    p = {"role": role, "size": size, "at": at, "group": group}
    if back:
        p["back"] = back
    return p


class TestChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def base(self, **over):
        """A 5x3 bedroom: a bed with its bedside in the top left corner and a
        tall chest against the east wall, one slack row along the south."""
        room = {
            "id": "bedroom.hand.a", "family": "bedroom", "sizeBand": "small",
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [5, 3],
            "sleeps": {"singles": 1, "couples": 0},
            "pieces": [
                piece("sleep", [1, 2], [0, 0], "sleep.bedside", "north"),
                piece("bedside", [1, 1], [1, 0], "sleep.bedside"),
                piece("storage.big", [1, 2], [4, 0], "storage.big.single",
                      "east"),
            ],
            "doors": {"north": [2, 3], "south": [0, 1, 2, 3, 4],
                      "west": [2], "east": [2]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room the tests break on purpose.",
        }
        room.update(over)
        return room

    def errors(self, room):
        return FR.check([room], self.data, self.lib)

    def test_base_checks_clean(self):
        self.assertEqual(self.errors(self.base()), [])

    def test_overlapping_pieces(self):
        room = self.base()
        room["pieces"][1]["at"] = [0, 0]
        self.assertTrue(any("overlap" in e for e in self.errors(room)))

    def test_blocked_door_cell(self):
        room = self.base()
        room["doors"]["north"] = [0, 2, 3]
        self.assertTrue(any("blocked by a piece" in e for e in self.errors(room)))

    def test_pocket_of_free_cells(self):
        room = self.base()
        del room["doors"]["north"]
        room["pieces"] += [piece("storage.small", [1, 1], [2, 1],
                                 "storage.big.single"),
                           piece("storage.small", [1, 1], [3, 1],
                                 "storage.big.single")]
        self.assertTrue(any("cannot be reached" in e for e in self.errors(room)))

    def test_piece_with_no_free_use_side(self):
        room = self.base()
        room["doors"]["north"] = [2]
        room["pieces"].append(piece("storage.small", [1, 2], [3, 0],
                                    "storage.big.single"))
        self.assertTrue(any("no reached cell on its use sides" in e
                            for e in self.errors(room)))

    def test_bad_stretch_line(self):
        room = self.base()
        room["stretch"] = {"y": [1]}
        self.assertTrue(any("runs through a piece" in e for e in self.errors(room)))

    def test_a_clear_stretch_line_is_fine(self):
        room = self.base()
        room["stretch"] = {"x": [2]}
        self.assertEqual(self.errors(room), [])

    def test_flush_room_with_two_empty_lines_along_a_wall(self):
        room = self.base(size=[5, 4])
        room["doors"]["west"] = [2, 3]
        room["doors"]["east"] = [2, 3]
        self.assertTrue(any("empty lines along the south wall" in e
                            for e in self.errors(room)))

    def test_open_filler_touching_an_edge(self):
        room = self.base(size=[5, 4], style="open")
        room["doors"]["west"] = [2, 3]
        room["doors"]["east"] = [2, 3]
        room["filler"] = {"at": [1, 2], "size": [3, 2]}
        self.assertTrue(any("touches the room edge" in e
                            for e in self.errors(room)))

    def test_open_room_with_an_empty_line_its_middle_does_not_need(self):
        room = self.base(size=[5, 5], sizeBand="medium", style="open")
        room["doors"]["west"] = [2, 3, 4]
        room["doors"]["east"] = [2, 3, 4]
        room["filler"] = {"at": [1, 1], "size": [2, 2]}
        self.assertTrue(any("along the south wall" in e
                            for e in self.errors(room)))

    def test_an_open_room_with_only_the_fillers_buffer_line_checks_clean(self):
        room = self.base(size=[5, 4], style="open")
        room["doors"]["west"] = [2, 3]
        room["doors"]["east"] = [2, 3]
        room["filler"] = {"at": [1, 1], "size": [3, 2]}
        self.assertEqual(self.errors(room), [])

    def test_wrong_size_band(self):
        room = self.base(sizeBand="large")
        self.assertTrue(any("outside size band" in e for e in self.errors(room)))

    def test_room_three_times_as_long_as_wide(self):
        """A 6x2 bedroom whose only fault is the aspect: the long side is
        three times the short, over the family cap of two."""
        room = {
            "id": "bedroom.hand.aspect", "family": "bedroom",
            "sizeBand": "small", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [6, 2],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 1], [0, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [2, 0], "sleep.couple.bedside2"),
                piece("storage.big", [2, 1], [3, 0],
                      "storage.big.single.bedroom.master", "north"),
                piece("light.small", [1, 1], [5, 0],
                      "light.small.single.bedroom.master1"),
            ],
            "doors": {"north": [], "south": [0, 1, 2, 3, 4, 5],
                      "west": [1], "east": [1]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room three times as long as wide.",
        }
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("aspect 6x2 is over the family cap 2: the long side "
                      "may be at most 2x the short side", errors[0])

    def test_grand_room_with_a_dead_corner(self):
        """An 11x7 grand room whose furniture hugs the north and the two west
        corners: the bottom right corner sits more than the grand gap plus
        one from every piece, so its floor is dead."""
        room = {
            "id": "bedroom.master.hand.dead", "family": "bedroom.master",
            "sizeBand": "large", "clearance": "grand", "style": "flush",
            "wealth": ["wealthy", "elite"], "size": [11, 7],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 2], [0, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [2, 0], "sleep.couple.bedside2"),
                piece("storage.big", [2, 1], [3, 0],
                      "storage.big.single.bedroom.master", "north"),
                piece("seat", [1, 1], [10, 0], "seat.single.bedroom.master",
                      "north"),
                piece("seat.lounge", [1, 1], [0, 6],
                      "seat.lounge.single.bedroom.master", "south"),
            ],
            "doors": {"north": [5, 6, 7, 8, 9],
                      "south": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                      "west": [2, 3, 4, 5], "east": [1, 2, 3, 4, 5, 6]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.master.large.b",
            "description": "A hand-made room with a dead corner.",
        }
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("11 dead floor cell(s) (first at 5,6): more than 4 "
                      "cells from every piece at grand clearance", errors[0])

    def test_open_filler_and_its_ring_are_not_dead_floor(self):
        """A 13x11 grand open room whose filler centre is more than the grand
        gap plus one from every piece: the filler and the ring of cells
        around it are walkable floor, so the room checks clean — the same
        room without its filler is the dead-floor room above."""
        room = {
            "id": "bedroom.master.hand.ring", "family": "bedroom.master",
            "sizeBand": "large", "clearance": "grand", "style": "open",
            "wealth": ["wealthy", "elite"], "size": [13, 11],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 2], [0, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [2, 0], "sleep.couple.bedside2"),
                piece("storage.big", [2, 1], [3, 0],
                      "storage.big.single.bedroom.master", "north"),
                piece("seat", [1, 1], [12, 0], "seat.single.bedroom.master",
                      "north"),
                piece("light.small", [1, 1], [12, 5],
                      "light.small.single.bedroom.master1"),
                piece("wash.basin", [1, 1], [0, 10], "wash.basin.single",
                      "south"),
                piece("seat.lounge", [1, 1], [5, 10],
                      "seat.lounge.single.bedroom.master", "south"),
                piece("heat", [2, 1], [11, 10],
                      "heat.single.bedroom.master", "south"),
            ],
            "doors": {"north": [5, 6, 7, 8, 9, 10, 11],
                      "south": [1, 2, 3, 4, 6, 7, 8, 9, 10],
                      "west": [2, 3, 4, 5, 6, 7, 8, 9],
                      "east": [1, 2, 3, 4, 6, 7, 8, 9]},
            "filler": {"at": [5, 4], "size": [3, 3]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.master.large.b",
            "description": "A hand-made room around an open middle.",
        }
        self.assertEqual(self.errors(room), [])
        self.assertEqual(FR.dead_cells(room), [])
        flushed = {k: v for k, v in room.items() if k != "filler"}
        flushed["style"] = "flush"
        self.assertTrue(any("dead floor" in e for e in self.errors(flushed)))

    def test_sleeps_must_match_the_pieces(self):
        room = self.base(sleeps={"singles": 2, "couples": 0})
        self.assertTrue(any("does not match the pieces" in e
                            for e in self.errors(room)))

    def test_unknown_group(self):
        room = self.base()
        room["pieces"][1]["group"] = "ghost.group"
        self.assertTrue(any("names no group" in e for e in self.errors(room)))

    def test_broken_symmetry(self):
        room = self.base(symmetric=True)
        self.assertTrue(any("flagged symmetric" in e for e in self.errors(room)))

    def test_symmetric_room_checks_clean(self):
        room = {
            "id": "bedroom.hand.sym", "family": "bedroom",
            "sizeBand": "small", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [4, 3],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 2], [1, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [0, 0], "sleep.couple.bedside2"),
                piece("bedside", [1, 1], [3, 0], "sleep.couple.bedside2"),
            ],
            "doors": {"south": [0, 1, 2, 3], "west": [1, 2],
                      "east": [1, 2]},
            "stretch": {}, "outdoor": False, "symmetric": True,
            "recipe": "bedroom.small.a",
            "description": "A symmetric hand-made room.",
        }
        self.assertEqual(self.errors(room), [])
        room["pieces"].pop()
        self.assertTrue(any("flagged symmetric" in e for e in self.errors(room)))


class TestTurning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def rooms(self):
        plain = {
            "id": "bedroom.hand.a", "family": "bedroom", "sizeBand": "small",
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [5, 3],
            "sleeps": {"singles": 1, "couples": 0},
            "pieces": [
                piece("sleep", [1, 2], [0, 0], "sleep.bedside", "north"),
                piece("bedside", [1, 1], [1, 0], "sleep.bedside"),
                piece("storage.big", [1, 2], [4, 0], "storage.big.single",
                      "east"),
            ],
            "doors": {"north": [2, 3], "south": [0, 1, 2, 3, 4],
                      "west": [2], "east": [2]},
            "stretch": {"x": [2]}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room the tests turn around.",
        }
        symmetric = {
            "id": "bedroom.hand.sym", "family": "bedroom",
            "sizeBand": "small", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [4, 3],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 2], [1, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [0, 0], "sleep.couple.bedside2"),
                piece("bedside", [1, 1], [3, 0], "sleep.couple.bedside2"),
            ],
            "doors": {"south": [0, 1, 2, 3], "west": [1, 2],
                      "east": [1, 2]},
            "stretch": {}, "outdoor": False, "symmetric": True,
            "recipe": "bedroom.small.a",
            "description": "A symmetric hand-made room.",
        }
        return [plain, symmetric]

    def test_four_turns_return_the_room(self):
        for room in self.rooms():
            with self.subTest(room=room["id"]):
                self.assertEqual(FR.rotate(room, 4), room)
                stepped = room
                for _ in range(4):
                    stepped = FR.rotate(stepped, 1)
                self.assertEqual(stepped, room)

    def test_a_quarter_turn_swaps_the_size(self):
        room = self.rooms()[0]
        self.assertEqual(FR.rotate(room, 1)["size"], [3, 5])
        self.assertEqual(FR.rotate(room, 2)["size"], room["size"])

    def test_every_turn_and_mirror_checks(self):
        for room in self.rooms():
            for mirror in (False, True):
                for turns in range(4):
                    turned = FR.rotate(room, turns, mirror)
                    with self.subTest(room=room["id"], mirror=mirror,
                                      turns=turns):
                        self.assertEqual(
                            FR.check([turned], self.data, self.lib), [],
                            json.dumps(turned, indent=1))


class TestUseSides(unittest.TestCase):
    def p(self, role, size=(1, 1), at=(0, 0), **kw):
        return dict({"role": role, "size": list(size), "at": list(at)}, **kw)

    def test_beds_use_a_long_side(self):
        self.assertEqual(FR.use_sides(self.p("sleep", (1, 2))),
                         ("east", "west"))
        self.assertEqual(FR.use_sides(self.p("sleep.couple", (2, 1))),
                         ("north", "south"))
        self.assertEqual(FR.use_sides(self.p("sleep.child", (2, 2))),
                         ("north", "east", "south", "west"))
        self.assertEqual(FR.use_sides(self.p("med.bed", (1, 1))),
                         ("north", "east", "south", "west"))

    def test_seats_face_away_from_their_table(self):
        table = self.p("table.dining", (2, 1), (2, 0))
        self.assertEqual(FR.use_sides(self.p("seat"), (table,)), ("west",))
        desk = self.p("desk", (1, 2), (0, 2))
        self.assertEqual(FR.use_sides(self.p("seat", at=(0, 0)), (desk,)),
                         ("north",))

    def test_a_lone_seats_front_when_it_backs_a_wall_else_any_side(self):
        seat = self.p("seat", back="north")
        self.assertEqual(FR.use_sides(seat), ("south",))
        self.assertEqual(FR.use_sides(self.p("seat")),
                         ("north", "east", "south", "west"))

    def test_a_backed_pieces_front(self):
        chest = self.p("storage.big", back="east")
        self.assertEqual(FR.use_sides(chest), ("west",))

    def test_tables_desks_and_defaults_any_side(self):
        for role in ("table.dining", "table.small", "desk", "chest",
                     "coat.rack", "basin"):
            self.assertEqual(FR.use_sides(self.p(role)),
                             ("north", "east", "south", "west"), role)

    def test_lights_decor_and_optionals_none(self):
        self.assertEqual(FR.use_sides(self.p("light.small")), ())
        self.assertEqual(FR.use_sides(self.p("decor.floor", (2, 2))), ())
        self.assertEqual(FR.use_sides(self.p("chest", optional=True)), ())


class TestShipped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def test_the_shipped_rooms_folder_loads_clean(self):
        rooms = FR.load()
        self.assertGreater(len(rooms), 0)
        self.assertEqual(FR.check(rooms, self.data, self.lib), [])

    def test_unreadable_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bedroom.json"), "w",
                      encoding="utf-8") as f:
                f.write('{"rooms": [ {"id": "bedroom.hand.a",')
            rooms = FR.load(d)
            self.assertTrue(any("cannot be read" in e
                                for e in FR.check(rooms, self.data, self.lib)))


if __name__ == "__main__":
    unittest.main()
