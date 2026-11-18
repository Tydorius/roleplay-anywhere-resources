"""The fixed rooms: a hand-made room checks clean, every check catches its
own hand-broken copy, the hand-work fields (retired, edited, source) check
by their own rules and active() drops the retired, derive() reproduces the
worked-out fields of every shipped room, the access rules derive the cells
a piece is used from, turning four times returns the same room while every
turn and mirror still checks, and the shipped rooms folder loads clean."""
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
        """A 5x3 bedroom: a bed in the top left corner, its bedside beside
        the bed's side, and a tall chest against the east wall, one slack
        row along the south."""
        room = {
            "id": "bedroom.hand.a", "family": "bedroom", "sizeBand": "small",
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [5, 3],
            "sleeps": {"singles": 1, "couples": 0},
            "pieces": [
                piece("sleep", [1, 2], [0, 0], "sleep.bedside", "north"),
                piece("bedside", [1, 1], [2, 1], "sleep.bedside"),
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
        room["pieces"] += [piece("storage.small", [1, 1], [1, 1],
                                 "storage.big.single"),
                           piece("storage.small", [1, 1], [3, 1],
                                 "storage.big.single")]
        self.assertTrue(any("cannot be reached" in e for e in self.errors(room)))

    def test_a_piece_with_no_free_reached_access_cell(self):
        room = self.base()
        room["doors"]["north"] = [2]
        room["pieces"].append(piece("storage.small", [1, 2], [3, 0],
                                    "storage.small.single"))
        self.assertTrue(any("has no free reached cell among its access "
                            "cells" in e for e in self.errors(room)))

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
        room = self.base(size=[5, 4], style="open", pieces=[
            piece("sleep", [2, 1], [0, 0], "sleep.bedside", "north"),
            piece("bedside", [1, 1], [2, 0], "sleep.bedside"),
            piece("storage.big", [1, 2], [4, 2], "storage.big.single",
                  "east"),
        ], doors={"north": [3, 4], "south": [0, 1, 2, 3],
                  "west": [1, 2, 3], "east": [0, 1]})
        room["filler"] = {"at": [1, 1], "size": [3, 2]}
        self.assertEqual(self.errors(room), [])

    def test_wrong_size_band(self):
        room = self.base(sizeBand="large")
        self.assertTrue(any("outside size band" in e for e in self.errors(room)))

    def test_washroom_without_a_bath_is_rejected(self):
        room = self.base()
        room["family"] = "washroom"
        room["recipe"] = "washroom.small.b"
        errors = self.errors(room)
        self.assertTrue(any("holds no wash.bath piece: a washroom needs one"
                            in e for e in errors), errors)
        self.assertTrue(any("holds no wash.toilet piece: a washroom needs one"
                            in e for e in errors), errors)
        self.assertTrue(any("holds no wash.basin piece: a washroom needs one"
                            in e for e in errors), errors)

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
                piece("bedside", [1, 1], [0, 0], "sleep.couple.bedside2"),
                piece("sleep.couple", [2, 2], [1, 0],
                      "sleep.couple.bedside2", "north"),
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
        self.assertIn("33 dead floor cell(s) (first at 3,4): more than 2 "
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
                piece("bedside", [1, 1], [0, 0], "sleep.couple.bedside2"),
                piece("sleep.couple", [2, 2], [1, 0],
                      "sleep.couple.bedside2", "north"),
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
                         pieces=[
                             piece("sleep", [2, 1], [0, 0], "sleep.bedside",
                                   "north"),
                             piece("bedside", [1, 1], [2, 0], "sleep.bedside"),
                             piece("storage.big", [1, 2], [5, 3],
                                   "storage.big.single", "east"),
                         ],
                         doors={"north": [3, 4, 5],
                                "south": [0, 1, 2, 3, 4],
                                "west": [1, 2, 3, 4], "east": [0, 1, 2]})
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


class TestWashFamilyRules(unittest.TestCase):
    """The wash families' fixture pairings (WASH_FAMILY_RULES): a washroom
    needs a toilet, a bath and a basin, a privy holds the toilet and never a
    bath, and a bath room the bath and never a toilet. The rooms come from
    the shipped files, broken by hand one fixture at a time."""

    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()
        cls.shipped = [r for r in FR.load()
                       if r.get("family") in ("washroom", "privy", "bath")]

    def errors(self, room):
        return FR.check([room], self.data, self.lib)

    def _a_shipped(self, family, role=None, without=None):
        for room in self.shipped:
            if room["family"] != family:
                continue
            roles = {p["role"] for p in room["pieces"]}
            if role is not None and role not in roles:
                continue
            if without is not None and without in roles:
                continue
            return json.loads(json.dumps(room))
        self.fail(f"no shipped {family} room "
                  f"{'with' if role else 'without'} {role or without}")

    def _free_spot(self, room, pw, ph):
        w, h = room["size"]
        taken = {(x, y) for p in room["pieces"]
                 for x in range(p["at"][0], p["at"][0] + p["size"][0])
                 for y in range(p["at"][1], p["at"][1] + p["size"][1])}
        for y in range(h - ph + 1):
            for x in range(w - pw + 1):
                if not any((cx, cy) in taken
                           for cx in range(x, x + pw)
                           for cy in range(y, y + ph)):
                    return [x, y]
        self.fail(f"no free {pw}x{ph} spot in {room['id']}")

    def test_the_shipped_wash_rooms_check_clean(self):
        self.assertEqual(FR.check(self.shipped, self.data, self.lib), [])

    def test_a_washroom_without_its_bath_is_rejected(self):
        room = self._a_shipped("washroom", role="wash.bath")
        room["pieces"] = [p for p in room["pieces"]
                          if p["role"] != "wash.bath"]
        self.assertTrue(any("holds no wash.bath piece: a washroom needs one"
                            in e for e in self.errors(room)))

    def test_a_privy_with_a_bath_is_rejected(self):
        room = self._a_shipped("privy")
        room["pieces"].append(piece("wash.bath", [1, 2],
                                    self._free_spot(room, 1, 2),
                                    "wash.bath.wash.basin"))
        self.assertTrue(any("holds a wash.bath piece, which a privy never "
                            "does" in e for e in self.errors(room)))

    def test_a_bath_room_with_a_toilet_is_rejected(self):
        room = self._a_shipped("bath")
        room["pieces"].append(piece("wash.toilet", [1, 1],
                                    self._free_spot(room, 1, 1),
                                    "wash.toilet.single.privy"))
        self.assertTrue(any("holds a wash.toilet piece, which a bath never "
                            "does" in e for e in self.errors(room)))

    def test_privies_and_bath_rooms_pass_as_they_stand(self):
        for room in self.shipped:
            if room["family"] in ("privy", "bath"):
                with self.subTest(room=room["id"]):
                    self.assertEqual(self.errors(room), [])


class TestFamilyBands(unittest.TestCase):
    """Size bands per family (library.json's familySizeBands): a family with
    a table uses only its own bands — band_for reads cells and aspect, the
    first match winning — while every other family keeps the shared table;
    a band's aspect may stretch a room past the family cap, a band or family
    maxFloorPerPiece caps the free floor per piece, and a closet follows its
    own door rules (one side only, a walk-in needing that side, a reach-in
    needing no floor at all)."""

    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def errors(self, room):
        return FR.check([room], self.data, self.lib)

    def test_a_family_with_a_table_uses_only_its_own_bands(self):
        self.assertEqual([b["name"] for b in FR.family_bands("bedroom")],
                         ["narrow", "tiny", "small", "medium", "large",
                          "servant"])
        self.assertEqual([b["name"] for b in FR.family_bands("privy")],
                         ["stall", "small"])
        self.assertEqual([b["name"] for b in FR.family_bands("closet")],
                         ["reach", "walkin"])
        # a family without a table shares sizeBands and holds no band
        self.assertEqual(FR.family_bands("bath"), [])
        self.assertEqual(FR.band_for("bath", 5, 5), None)
        self.assertEqual(FR.band_for_area(25), "medium")

    def test_band_lookup_holds_cells_and_aspect(self):
        # first match wins: 10 cells at 5x2 read narrow, not tiny
        self.assertEqual(FR.band_for("bedroom", 5, 2), "narrow")
        self.assertEqual(FR.band_for("bedroom", 3, 3), "tiny")
        self.assertEqual(FR.band_for("bedroom", 6, 2), "narrow")
        self.assertEqual(FR.band_for("privy", 1, 2), "stall")
        self.assertEqual(FR.band_for("privy", 2, 3), "small")
        self.assertEqual(FR.band_for("closet", 1, 2), "reach")
        self.assertEqual(FR.band_for("closet", 2, 2), "walkin")
        self.assertEqual(FR.band_for("closet", 1, 3), "walkin")
        # 2x3 is six cells but no closet band holds it
        self.assertEqual(FR.band_for("closet", 2, 3), None)
        self.assertEqual(FR.max_floor_per_piece("privy", "stall"), 2)
        self.assertEqual(FR.max_floor_per_piece("bedroom", "narrow"), 2)
        self.assertIsNone(FR.max_floor_per_piece("bedroom", "tiny"))
        self.assertIsNone(FR.max_floor_per_piece("bath", "small"))

    def _servants(self, size_band="narrow"):
        """A 5x2 servants' bedroom: two single beds lying lengthwise against
        the north wall with a chest between them, the south row clear."""
        return {
            "id": "bedroom.hand.narrow", "family": "bedroom",
            "sizeBand": size_band, "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [5, 2],
            "sleeps": {"singles": 2, "couples": 0},
            "pieces": [
                piece("sleep", [2, 1], [0, 0], "sleep.pair.storage.small",
                      "north"),
                piece("storage.small", [1, 1], [2, 0],
                      "sleep.pair.storage.small", "north"),
                piece("sleep", [2, 1], [3, 0], "sleep.pair.storage.small",
                      "north"),
            ],
            "doors": {"north": [], "south": [0, 1, 2, 3, 4],
                      "west": [1], "east": [1]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.servants",
            "description": "A hand-made servants' room.",
        }

    def test_a_narrow_bedroom_passes_the_family_cap(self):
        # 5x2 reads 2.5:1, past the family cap of 2: the narrow band's own
        # aspect window is what lets it stand
        self.assertEqual(self.errors(self._servants()), [])

    def test_the_same_room_outside_narrow_fails_the_family_cap(self):
        # 10 cells sit inside tiny too, but tiny has no aspect of its own,
        # so the family cap of 2 applies again
        errors = self.errors(self._servants(size_band="tiny"))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("aspect 5x2 is over the family cap 2", errors[0])

    def _closet(self, size_band, size, pieces, doors):
        return {
            "id": "closet.hand.a", "family": "closet", "sizeBand": size_band,
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": size,
            "sleeps": {"singles": 0, "couples": 0},
            "pieces": pieces, "doors": doors,
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "closet.broom",
            "description": "A hand-made closet.",
        }

    def test_a_reach_in_closet_gets_its_door_cells_from_access(self):
        # 2x1 fully lined: both cells are pieces, so the door cells are the
        # access cells outside the room — derive() lands them on the south
        # side, and a reach-in with no door side at all is an error
        room = self._closet("reach", [2, 1], [
            piece("utility", [1, 1], [0, 0],
                  "utility.storage.small.opt.closet", "north"),
            piece("storage.small", [1, 1], [1, 0],
                  "utility.storage.small.opt.closet", "north"),
        ], {"north": [], "south": [], "west": [], "east": []})
        self.assertTrue(any("a closet needs a door on one side" in e
                            for e in self.errors(room)))
        derived = FR.derive(room, self.data, self.lib)
        self.assertEqual(derived["doors"]["south"], [0, 1])
        self.assertEqual(self.errors(derived), [])

    def test_a_walk_in_closet_needs_a_door_on_one_side(self):
        room = self._closet("walkin", [2, 2], [
            piece("utility", [1, 1], [0, 0],
                  "utility.storage.small.opt.closet", "north"),
            piece("storage.small", [1, 1], [1, 0],
                  "utility.storage.small.opt.closet", "north"),
        ], {"north": [], "south": [0, 1], "west": [], "east": []})
        self.assertEqual(self.errors(room), [])
        room["doors"]["south"] = []
        self.assertTrue(any("a closet needs a door on one side"
                            in e for e in self.errors(room)))

    def test_a_walk_in_piece_no_free_reached_access_cell_is_an_error(self):
        # the door reaches only the east column; the piece on the west side
        # is used from a cell nothing reaches
        room = self._closet("walkin", [2, 2], [
            piece("utility", [1, 1], [0, 0],
                  "utility.storage.small.opt.closet", "north"),
            piece("storage.small", [1, 1], [1, 1],
                  "utility.storage.small.opt.closet", "south"),
        ], {"north": [1], "south": [], "west": [], "east": []})
        errors = self.errors(room)
        self.assertTrue(any("no free reached cell among its access cells"
                            in e for e in errors), errors)

    def test_max_floor_per_piece_rejects_a_roomy_single_toilet_privy(self):
        # 4x4 with one toilet: 15 free cells over one piece is far past the
        # privy's 2 floor cells per piece
        room = {
            "id": "privy.hand.a", "family": "privy", "sizeBand": "small",
            "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [4, 4],
            "sleeps": {"singles": 0, "couples": 0},
            "pieces": [piece("wash.toilet", [1, 1], [0, 0],
                             "wash.toilet.single.privy", "north")],
            "doors": {"north": [1, 2, 3], "south": [0, 1, 2, 3],
                      "west": [1, 2], "east": [1, 2]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "privy.tiny.a",
            "description": "A hand-made privy, far too much floor.",
        }
        self.assertTrue(any("floor cells per piece cap" in e
                            for e in self.errors(room)))


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
                piece("bedside", [1, 1], [2, 1], "sleep.bedside"),
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
                piece("bedside", [1, 1], [2, 1], "sleep.bedside"),
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


class TestAccessCells(unittest.TestCase):
    """The access rules every piece is used through (library.json's
    roleAccess, read as cells): a bed standing free is used from its long
    sides at the foot end — both of them for a double bed, one for the
    rest — a bedside beside a one-long bed's head locks that side, a lone
    seat must back a wall, and a hand access list replaces the cells a
    group would derive."""

    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def p(self, role, size=(1, 1), at=(0, 0), group="group.hand", **kw):
        return piece(role, list(size), list(at), group,
                     kw.pop("back", None), **kw)

    def cons(self, pieces, room=None):
        """The constraints as plain tuples, so the assertions read as the
        cells themselves."""
        return [{"cells": [tuple(cc) for cc in c["cells"]],
                 "need": c["need"], "piece": c["piece"]}
                for c in FR.access_constraints(pieces, room, self.lib)]

    def errors(self, room):
        return FR.check([room], self.data, self.lib)

    def test_beds_use_their_long_sides_at_the_foot_end(self):
        # one long side is enough: one limited constraint over the foot
        # cells of both long sides (a bed at the origin reaches outside
        # the room on the west; the checker drops those cells)
        self.assertEqual(self.cons([self.p("sleep", (1, 2))]),
                         [{"cells": [(1, 1), (-1, 1)], "need": 1,
                           "piece": 0}])
        # both long sides: one mandatory cell each
        self.assertEqual(self.cons([self.p("sleep.couple", (2, 1))]),
                         [{"cells": [(0, -1)], "need": 1, "piece": 0},
                          {"cells": [(0, 1)], "need": 1, "piece": 0}])
        # a square bed with no back uses all four sides, one of them enough
        self.assertEqual(self.cons([self.p("sleep.child", (2, 2))]),
                         [{"cells": [(0, -1), (2, 1), (0, 2), (-1, 1)],
                           "need": 1, "piece": 0}])
        self.assertEqual(self.cons([self.p("med.bed")]),
                         [{"cells": [(0, -1), (1, 0), (0, 1), (-1, 0)],
                           "need": 1, "piece": 0}])

    def test_a_bed_lying_lengthwise_uses_the_opposite_side_alone(self):
        # back north and wider than tall: the south row is the only
        # constraint, whatever the rule says
        self.assertEqual(
            self.cons([self.p("sleep.couple", (2, 1), back="north")]),
            [{"cells": [(0, 1), (1, 1)], "need": 1, "piece": 0}])

    def test_a_bedside_locks_one_long_side_of_a_one_long_bed(self):
        bed = self.p("sleep", (1, 2), back="north")
        bedside = self.p("bedside", (1, 1), (1, 0))
        # the bedside covers the bed's east head cell: the east foot cell
        # becomes mandatory and the west side carries nothing
        self.assertEqual(self.cons([bed, bedside])[0],
                         {"cells": [(1, 1)], "need": 1, "piece": 0})

    def test_seats_are_not_used_from_their_tables_side(self):
        seat = self.p("seat")
        table = self.p("table.dining", (2, 1), (1, 0))
        self.assertEqual(self.cons([seat, table])[0],
                         {"cells": [(0, -1), (0, 1), (-1, 0)],
                          "need": 1, "piece": 0})

    def test_a_lone_seats_front_when_it_backs_a_wall_else_any_side(self):
        self.assertEqual(self.cons([self.p("seat", back="north")]),
                         [{"cells": [(0, 1)], "need": 1, "piece": 0}])
        self.assertEqual(self.cons([self.p("seat")]),
                         [{"cells": [(0, -1), (1, 0), (0, 1), (-1, 0)],
                           "need": 1, "piece": 0}])

    def test_a_backed_pieces_front(self):
        self.assertEqual(self.cons([self.p("storage.big", back="east")]),
                         [{"cells": [(-1, 0)], "need": 1, "piece": 0}])

    def test_tables_desks_and_defaults_any_side(self):
        for role in ("table.dining", "table.small", "desk", "chest",
                     "coat.rack", "basin"):
            self.assertEqual(self.cons([self.p(role, (2, 1))]),
                             [{"cells": [(0, -1), (2, 0), (0, 1), (-1, 0)],
                               "need": 1, "piece": 0}], role)

    def test_lights_decor_and_optionals_hold_no_constraints(self):
        self.assertEqual(self.cons([self.p("light.small"),
                                    self.p("decor.floor", (2, 2), (2, 0)),
                                    dict(self.p("chest"),
                                         optional=True)]), [])

    def _relax_room(self, wealth):
        """A 5x3 bedroom whose double bed's east foot cell is blocked by a
        chest of another group: both-long needs both feet, one-long makes
        do with the free west one."""
        return {
            "id": "bedroom.hand.relax", "family": "bedroom",
            "sizeBand": "small", "clearance": "tight", "style": "flush",
            "wealth": wealth, "size": [5, 3],
            "sleeps": {"singles": 0, "couples": 1},
            "pieces": [
                piece("sleep.couple", [2, 2], [1, 0],
                      "sleep.couple.bedside2", "north"),
                piece("storage.small", [1, 1], [3, 1],
                      "storage.small.single"),
            ],
            "doors": {"north": [3, 4], "south": [0, 1, 2, 3, 4],
                      "west": [1, 2], "east": [1, 2]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room the tests relax on purpose.",
        }

    def test_a_double_bed_one_side_blocked_relaxes_at_poor_tight(self):
        # sleep.couple relaxes to one-long for a poor tight room: the free
        # west foot cell is enough
        self.assertEqual(self.errors(self._relax_room(["poor"])), [])
        # at modest the relax is off: both feet are mandatory
        errors = self.errors(self._relax_room(["poor", "modest"]))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("has no free reached cell among its access cells "
                      "[[3, 1]] (needs 1)", errors[0])

    def test_a_single_bed_against_the_wall_checks_clean(self):
        room = {
            "id": "bedroom.hand.wall", "family": "bedroom",
            "sizeBand": "tiny", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [2, 3],
            "sleeps": {"singles": 1, "couples": 0},
            "pieces": [piece("sleep", [1, 2], [0, 0], "sleep.bedside",
                             "north")],
            "doors": {"north": [1], "south": [0, 1], "west": [2],
                      "east": [0, 1, 2]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room with a bed against the wall.",
        }
        self.assertEqual(self.errors(room), [])

    def _lock_room(self, blocked):
        """A 3x2 bedroom: the bedside beside the bed's head locks the east
        side, so the bed is used from (1, 1) alone — blocked or not."""
        pieces = [
            piece("sleep", [1, 2], [0, 0], "sleep.bedside", "north"),
            piece("bedside", [1, 1], [1, 0], "sleep.bedside"),
        ]
        if blocked:
            pieces.append(piece("storage.small", [1, 1], [1, 1],
                                "storage.small.single"))
        return {
            "id": "bedroom.hand.lock", "family": "bedroom",
            "sizeBand": "tiny", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [3, 2],
            "sleeps": {"singles": 1, "couples": 0},
            "pieces": pieces,
            "doors": {"north": [2], "south": [2], "west": [],
                      "east": [0, 1]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room with a locked bed side.",
        }

    def test_a_bedside_locked_beds_foot_cell_blocked_is_an_error(self):
        self.assertEqual(self.errors(self._lock_room(False)), [])
        errors = self.errors(self._lock_room(True))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("has no free reached cell among its access cells "
                      "[[1, 1]] (needs 1)", errors[0])

    def test_a_lone_seat_facing_nothing_is_an_error(self):
        room = {
            "id": "bedroom.hand.seat", "family": "bedroom",
            "sizeBand": "tiny", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [2, 2],
            "sleeps": {"singles": 0, "couples": 0},
            "pieces": [piece("seat", [1, 1], [0, 0],
                             "seat.single.bedroom.master")],
            "doors": {"north": [1], "south": [0, 1], "west": [1],
                      "east": [1]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room with a lone seat.",
        }
        errors = self.errors(room)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("faces nothing: a seat with no table, desk or counter "
                      "in its group must back a wall", errors[0])

    def test_access_cells_of_different_groups_may_overlap(self):
        room = {
            "id": "bedroom.hand.share", "family": "bedroom",
            "sizeBand": "tiny", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [3, 2],
            "sleeps": {"singles": 0, "couples": 0},
            "pieces": [
                piece("storage.big", [1, 1], [0, 0], "storage.big.single",
                      "west"),
                piece("storage.small", [1, 1], [2, 0],
                      "storage.small.single", "east"),
            ],
            "doors": {"north": [1], "south": [0, 1, 2], "west": [1],
                      "east": [1]},
            "stretch": {}, "outdoor": False, "symmetric": False,
            "recipe": "bedroom.small.a",
            "description": "A hand-made room with shared access cells.",
        }
        # both chests are used from (1, 0) alone — the same cell
        self.assertEqual(self.cons(room["pieces"]),
                         [{"cells": [(1, 0)], "need": 1, "piece": 0},
                          {"cells": [(1, 0)], "need": 1, "piece": 1}])
        self.assertEqual(self.errors(room), [])

    def test_a_hand_access_list_replaces_the_derived_cells(self):
        gdef = {
            "pieces": [{"role": "storage.big", "size": [1, 1], "at": [0, 0],
                        "back": "east"}],
            "access": [{"cells": [[2, 1]], "need": 1, "replaces": [0]}],
        }
        # derived alone the chest is used from its front (-1, 0); the hand
        # list stands in its place
        self.assertEqual(FR.group_constraints(gdef, self.lib),
                         [{"cells": [[2, 1]], "need": 1, "piece": 0}])
        placed = [dict(gdef["pieces"][0], at=[4, 4], group="hand.share")]
        self.assertEqual(
            FR.access_constraints(placed, None, self.lib,
                                  {"groups": {"hand.share": gdef}}),
            [{"cells": [[6, 5]], "need": 1, "piece": 0}])


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
