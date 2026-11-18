"""The fixed rooms: a hand-made room checks clean, every check catches its
own hand-broken copy, the hand-work fields (retired, edited, source) check
by their own rules and active() drops the retired, derive() reproduces the
worked-out fields of every shipped room, the use-side table matches the
design, turning four times returns the same room while every turn and
mirror still checks, and the shipped rooms folder loads clean."""
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
                piece("bedside", [1, 1], [1, 1], "sleep.bedside"),
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
        room["stretch"] = {"x": [1]}
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
        room["pieces"][1]["at"] = [1, 0]
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
        """An 11x7 grand master room whose furniture hugs the north and the
        two west corners: the bottom right corner sits more than the roomy
        gap of 2 a private room keeps at grand from every piece, so its
        floor is dead."""
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
        self.assertEqual(len(errors), 1)
        self.assertIn("34 dead floor cell(s) (first at 3,4): more than 2 "
                      "cells from every piece at grand clearance", errors[0])

    def test_a_free_cell_exactly_one_past_the_gap_is_dead(self):
        """A 5x3 tight room whose middle column sits exactly gap+1 cells from
        the bed and the chest: under the tighter floor rule that column is
        dead — a cell may lean no more than the gap itself against the
        furniture."""
        room = self.base(pieces=[
            piece("sleep", [1, 2], [0, 0], "sleep.bedside", "north"),
            piece("storage.big", [1, 2], [4, 0], "storage.big.single",
                  "east"),
        ], doors={"north": [1, 2, 3], "south": [0, 1, 2, 3, 4],
                  "west": [2], "east": [2]})
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("3 dead floor cell(s) (first at 2,0): more than 1 "
                      "cells from every piece at tight clearance", errors[0])

    def test_open_filler_and_its_ring_are_not_dead_floor(self):
        """An 11x11 grand open room whose middle sits more than the grand gap
        from every piece: the filler and the ring of cells around it are
        walkable floor, so the room checks clean — the same room without its
        filler is dead floor in the middle."""
        room = {
            "id": "bedroom.master.hand.ring", "family": "bedroom.master",
            "sizeBand": "large", "clearance": "grand", "style": "open",
            "wealth": ["wealthy", "elite"], "size": [11, 11],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 2], [0, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [2, 0], "sleep.couple.bedside2"),
                piece("storage.big", [2, 1], [6, 0],
                      "storage.big.single.bedroom.master", "north"),
                piece("seat", [1, 1], [10, 0], "seat.single.bedroom.master",
                      "north"),
                piece("light.small", [1, 1], [10, 4],
                      "light.small.single.bedroom.master1"),
                piece("coat", [1, 1], [0, 5], "coat.single.bedroom.master"),
                piece("wash.basin", [1, 1], [0, 10], "wash.basin.single",
                      "south"),
                piece("seat.lounge", [1, 1], [5, 10],
                      "seat.lounge.single.bedroom.master", "south"),
                piece("seat.lounge", [1, 1], [10, 10],
                      "seat.lounge.single.bedroom.master", "south"),
                piece("decor.floor", [1, 1], [10, 7],
                      "decor.floor.single.bedroom.master2"),
            ],
            "doors": {"north": [3, 4, 5, 8, 9],
                      "south": [1, 2, 3, 4, 6, 7, 8, 9],
                      "west": [2, 3, 4, 6, 7, 8, 9],
                      "east": [1, 2, 3, 5, 6, 8, 9]},
            "filler": {"at": [3, 3], "size": [5, 4]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.master.large.b",
            "description": "A hand-made room around an open middle.",
        }
        self.assertEqual(self.errors(room), [])
        self.assertEqual(FR.dead_cells(room), [])
        flushed = {k: v for k, v in room.items() if k != "filler"}
        flushed["style"] = "flush"
        self.assertTrue(any("dead floor" in e for e in self.errors(flushed)))

    def test_open_filler_over_the_clearance_cap(self):
        """A 6x5 tight open room whose filler runs 4x3, one cell over the
        tight cap: nobody lays a rug that big."""
        room = self.base(size=[6, 5], sizeBand="medium", style="open",
                         wealth=["poor", "modest"],
                         pieces=[
                             piece("sleep", [1, 2], [0, 0], "sleep.bedside",
                                   "north"),
                             piece("bedside", [1, 1], [1, 0], "sleep.bedside"),
                             piece("storage.big", [1, 2], [5, 0],
                                   "storage.big.single", "east"),
                         ],
                         doors={"north": [2, 3, 4],
                                "south": [0, 1, 2, 3, 4, 5],
                                "west": [2, 3, 4], "east": [2, 3, 4]})
        room["filler"] = {"at": [1, 1], "size": [4, 3]}
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("filler 4x3 is over the tight cap 3x3: nobody lays a "
                      "rug that big", errors[0])

    def test_open_filler_twice_as_long_as_wide_at_most(self):
        """A 4x7 grand open room whose filler runs 2x5, half a cell over the
        two-to-one aspect: a rug twice as long as wide at the very most."""
        room = {
            "id": "bedroom.master.hand.narrow", "family": "bedroom.master",
            "sizeBand": "medium", "clearance": "grand", "style": "open",
            "wealth": ["wealthy", "elite"], "size": [4, 7],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 1], [0, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [2, 0], "sleep.couple.bedside2"),
                piece("storage.big", [2, 1], [0, 6],
                      "storage.big.single.bedroom.master", "south"),
            ],
            "doors": {"north": [3], "south": [2, 3],
                      "west": [2, 3, 4, 5], "east": [0, 1, 2, 3, 4, 5, 6]},
            "filler": {"at": [1, 1], "size": [2, 5]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.master.large.b",
            "description": "A runner of a rug.",
        }
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("filler 2x5 is too narrow: its long side may be at "
                      "most 2x its short side", errors[0])

    def test_open_filler_must_be_centred(self):
        """A 7x5 roomy open room whose 3x2 filler hugs the bed side: its
        distances to the west and east walls differ by two cells, and a rug
        that size sits in the middle of the floor or not at all."""
        room = self.base(size=[7, 5], sizeBand="medium", clearance="roomy",
                         style="open", wealth=["wealthy"],
                         pieces=[
                             piece("sleep", [1, 2], [0, 0], "sleep.bedside",
                                   "north"),
                             piece("bedside", [1, 1], [1, 0], "sleep.bedside"),
                             piece("storage.big", [1, 2], [6, 0],
                                   "storage.big.single", "east"),
                             piece("light.small", [1, 1], [5, 4],
                                   "light.small.single.bedroom.master1"),
                         ],
                         doors={"north": [2, 3, 4, 5],
                                "south": [0, 1, 2, 3, 4, 6],
                                "west": [2, 3, 4], "east": [2, 3, 4]})
        room["filler"] = {"at": [1, 2], "size": [3, 2]}
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("filler at [1, 2] is off centre: its distances to "
                      "opposite walls differ by more than 1 cell", errors[0])

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


class TestHandFields(unittest.TestCase):
    """The hand-work fields: retired, edited and source are checked by their
    own rules (the editable fields are wealth, description, symmetric and
    retired), and active() is the rooms a world may place."""

    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def base(self, **over):
        """The TestChecker bedroom again: the same 5x3 room, so the hand-work
        rules are tested on a room that checks clean without them."""
        room = {
            "id": "bedroom.hand.a", "family": "bedroom", "sizeBand": "small",
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [5, 3],
            "sleeps": {"singles": 1, "couples": 0},
            "pieces": [
                piece("sleep", [1, 2], [0, 0], "sleep.bedside", "north"),
                piece("bedside", [1, 1], [1, 1], "sleep.bedside"),
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

    def test_retired_edited_and_source_are_accepted(self):
        room = self.base(retired=True, source="hand",
                         edited=["wealth", "description", "symmetric",
                                 "retired"])
        room["wealth"] = ["modest"]
        room["description"] = "A hand-made room taken out of use."
        self.assertEqual(self.errors(room), [])

    def test_edited_must_list_editable_fields(self):
        self.assertTrue(any("edited must list fields among" in e
                            for e in self.errors(self.base(edited=["size"]))))

    def test_retired_must_be_true_or_false(self):
        self.assertTrue(any("retired must be true or false" in e
                            for e in self.errors(self.base(retired="yes"))))

    def test_active_drops_the_retired_rooms(self):
        up = self.base()
        down = self.base(id="bedroom.hand.b", retired=True)
        back = self.base(id="bedroom.hand.c", retired=False)
        self.assertEqual([r["id"] for r in FR.active([up, down, back])],
                         ["bedroom.hand.a", "bedroom.hand.c"])
        self.assertEqual(FR.active([]), [])
        self.assertEqual(FR.active(None), [])


class TestDerive(unittest.TestCase):
    """derive(): the one derivation of the worked-out fields — size, sizeBand,
    sleeps, doors and stretch recomputed from the pieces, matching every
    shipped room (whose own size stands: a room's floor may run past its
    pieces' span)."""

    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def test_derive_reproduces_every_shipped_room(self):
        rooms = FR.load()
        self.assertGreater(len(rooms), 0)
        for room in rooms:
            with self.subTest(room=room["id"]):
                bare = {k: v for k, v in room.items()
                        if k not in ("sizeBand", "sleeps", "doors", "stretch")}
                derived = FR.derive(bare, self.data, self.lib)
                for field in ("size", "sizeBand", "sleeps", "doors",
                              "stretch"):
                    self.assertEqual(derived[field], room[field], field)

    def test_a_room_without_a_size_is_sized_to_its_pieces(self):
        room = FR.derive({
            "id": "bedroom.hand.bare", "family": "bedroom", "sizeBand": "tiny",
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "pieces": [
                piece("sleep.couple", [2, 1], [0, 0],
                      "sleep.couple.bedside2", "north"),
                piece("bedside", [1, 1], [2, 1], "sleep.couple.bedside2"),
            ],
        }, self.data, self.lib)
        self.assertEqual(room["size"], [3, 2])
        self.assertEqual(room["sizeBand"], "tiny")
        self.assertEqual(room["sleeps"], {"singles": 0, "couples": 1})
        self.assertEqual(room["doors"], {"north": [2], "south": [0, 1],
                                         "west": [1], "east": [0]})


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
                piece("bedside", [1, 1], [1, 1], "sleep.bedside"),
                piece("storage.big", [1, 2], [4, 0], "storage.big.single",
                      "east"),
            ],
            "doors": {"north": [2, 3], "south": [0, 1, 2, 3, 4],
                      "west": [2], "east": [2]},
            "stretch": {"x": [1]}, "outdoor": False, "symmetric": False,
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
