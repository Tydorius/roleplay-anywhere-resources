"""Brief rl-11: outdoor rooms — the courtyard as a library room. A room of
the outdoor families (courtyard, garden, yard) stands in the open: no piece
backs a side (there are no walls), the flag must follow the family's own
bands spec, the flush style alone, every free edge cell is a door on every
side, and with the free area in one piece that keeps a clear walkway
crossing the room between every pair of opposite edges — a wall of pieces
across the middle is rejected, and so is a side every cell of which is
covered. The hand recipes compose rooms that carry the flag and check
clean. The compound fixture's castle courtyard is furnished behind
--room-assembler — its region under the compound, its pieces as objects,
every free court cell still one walk — and with the switch off the fixture
builds spec bytes identical to the reference."""
import json
import os
import tempfile
import unittest

import worldgen
from worldgen import api
from worldgen import fixed_rooms as FR
from worldgen import library as WL
from worldgen import room_composer as RC
from worldgen import room_groups as RG

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
DATA = os.path.join(os.path.dirname(__file__), "data")
SIDES = ("north", "south", "east", "west")

OUTDOOR_RECIPES = ("courtyard.small.hand", "courtyard.medium.hand",
                   "courtyard.large.hand", "garden.small.hand",
                   "garden.medium.hand", "garden.large.hand",
                   "yard.small.hand", "yard.medium.hand", "yard.large.hand")


def piece(role, size, at, group):
    return {"role": role, "size": size, "at": at, "group": group}


def occupied_cells(room):
    return {(p["at"][0] + i, p["at"][1] + j) for p in room["pieces"]
            for i in range(p["size"][0]) for j in range(p["size"][1])}


class TestOutdoorChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def court(self, **over):
        """A 5x4 courtyard: the statue court group on the middle-left, two
        benches facing the statue between them; the whole free edge is its
        entrance, one clear walk either way across."""
        room = {
            "id": "courtyard.hand.a", "family": "courtyard",
            "sizeBand": "small", "clearance": "tight", "style": "flush",
            "wealth": ["poor", "modest"], "size": [5, 4],
            "sleeps": {"singles": 0, "couples": 0},
            "pieces": [
                piece("seat.long", [2, 1], [1, 0], "statue.seat.court"),
                piece("decor.feature", [1, 1], [2, 1], "statue.seat.court"),
                piece("seat.long", [2, 1], [1, 2], "statue.seat.court"),
            ],
            "doors": {"north": [0, 3, 4], "south": [0, 1, 2, 3, 4],
                      "west": [0, 1, 2, 3], "east": [0, 1, 2, 3]},
            "stretch": {}, "outdoor": True, "symmetric": False,
            "recipe": "courtyard.small.hand",
            "description": "A hand-made court the tests break on purpose.",
        }
        room.update(over)
        return room

    def errors(self, room):
        return FR.check([room], self.data, self.lib)

    def test_the_court_checks_clean(self):
        self.assertEqual(self.errors(self.court()), [])

    def test_a_piece_pinned_to_a_side_is_rejected(self):
        room = self.court()
        room["pieces"][0]["back"] = "north"
        self.assertTrue(any("no walls to pin it to" in e
                            for e in self.errors(room)))

    def test_the_flag_must_follow_the_family(self):
        room = self.court(outdoor=False)
        errors = self.errors(room)
        self.assertTrue(any("stands in the open" in e for e in errors), errors)

    def test_the_open_style_is_rejected(self):
        room = self.court(style="open")
        self.assertTrue(any("keeps the flush style" in e
                            for e in self.errors(room)))

    def test_doors_must_list_every_free_edge_cell(self):
        room = self.court()
        room["doors"]["north"] = [3, 4]
        self.assertTrue(any("whole edge is its entrance" in e
                            for e in self.errors(room)))

    def test_a_wall_of_pieces_across_the_room_is_rejected(self):
        """A full column of trees splits the court east from west: no clear
        walk crosses the room any more, and the east doors are cut off."""
        room = self.court(pieces=[
            piece("decor.floor", [1, 1], [2, 0], "plant.tree.single.court"),
            piece("decor.floor", [1, 1], [2, 1], "plant.tree.single.court"),
            piece("decor.floor", [1, 1], [2, 2], "plant.tree.single.court"),
            piece("decor.floor", [1, 1], [2, 3], "plant.tree.single.court"),
        ], doors={"north": [0, 1, 3, 4], "south": [0, 1, 3, 4],
                  "west": [0, 1, 2, 3], "east": [0, 1, 2, 3]})
        errors = self.errors(room)
        self.assertTrue(any("cannot be reached from the doors" in e
                            or "cut off from the other doors" in e
                            for e in errors), errors)

    def test_a_side_without_one_free_edge_cell_is_rejected(self):
        room = self.court(pieces=[
            piece("decor.feature", [1, 4], [4, 0], "statue.seat.court"),
        ], doors={"north": [0, 1, 2, 3], "south": [0, 1, 2, 3],
                  "west": [0, 1, 2, 3], "east": []})
        self.assertTrue(any("no free edge cell on the east edge" in e
                            for e in self.errors(room)))


class TestOutdoorCompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def test_every_recipe_composes_an_outdoor_room_that_checks_clean(self):
        for layout in OUTDOOR_RECIPES:
            made, reason = None, ""
            for clearance in ("tight", "roomy", "grand"):
                rooms, reason = RC.compose(
                    self.data["recipes"][layout], self.data, clearance,
                    "flush", 1)
                if rooms:
                    made = rooms
                    break
            self.assertIsNotNone(made, f"{layout} composed nowhere: {reason}")
            for room in made:
                with self.subTest(layout=layout, room=room["id"]):
                    errors = FR.check([room], self.data, self.lib)
                    self.assertEqual(errors, [], errors)
                    self.assertIs(room["outdoor"], True)
                    self.assertEqual(room["style"], "flush")
                    self.assertFalse([p for p in room["pieces"]
                                      if p.get("back")], room["pieces"])
                    # every free edge cell a door on every side: the whole
                    # edge is the entrance, so a walk crosses either way
                    w, h = room["size"]
                    want = FR._edge_doors(w, h, occupied_cells(room))
                    have = {s: sorted((room.get("doors") or {}).get(s) or [])
                            for s in SIDES}
                    self.assertEqual(have, want, room["id"])
                    self.assertTrue(all(want.values()),
                                    f"{room['id']} loses a side: {want}")


class TestCompoundCourtyard(unittest.TestCase):
    ASHVALE = os.path.join(FIXTURES, "ashvale-compound.plan.json")

    @classmethod
    def setUpClass(cls):
        with open(cls.ASHVALE, encoding="utf-8") as f:
            cls.plan = json.load(f)

    def test_with_the_switch_off_the_build_is_byte_identical(self):
        with open(os.path.join(DATA, "compound-off-ashvale.json"),
                  encoding="utf-8") as f:
            want = json.load(f)["spec"]
        with tempfile.TemporaryDirectory() as tmp:
            api.relayout(self.ASHVALE, seed=1,
                         out_dir=os.path.join(tmp, "off"),
                         room_assembler=False)
            with open(os.path.join(tmp, "off", "spec.py"),
                      encoding="utf-8", newline="") as f:
                self.assertEqual(f.read(), want)

    def test_the_courtyard_is_furnished_behind_the_switch(self):
        world = worldgen.run(self.plan, seed=1, room_assembler=True)
        m = world.metrics
        self.assertEqual(m["region_overlaps"], [])
        self.assertEqual(m["object_overlaps"], [])
        self.assertEqual(m["reachability"], 1.0)
        self.assertTrue(m["doors_clear"])
        self.assertTrue(m["walkways_clear"])
        furnished = [c for c in world.compounds if c.court is not None]
        self.assertTrue(furnished, "no compound got a furnished courtyard")
        comp = furnished[0]
        room, (cx, cy) = comp.court["room"], comp.court["at"]
        self.assertIs(room["outdoor"], True)
        rw, rh = room["size"]
        # the court ships as an unwalled region under the compound, sized
        # and placed as the library room it holds
        fname = f"{comp.name} Courtyard"
        court = next((r for r in world.regions if r.name == fname), None)
        self.assertIsNotNone(court, fname)
        self.assertEqual(court.kind, "yard")
        self.assertEqual(court.parent, comp.name)
        self.assertEqual((court.rect.x, court.rect.y,
                          court.rect.w, court.rect.h), (cx, cy, rw, rh))
        # its pieces ship as objects of the court region, inside its rect
        objs = [o for o in world.objects if o.region == fname]
        self.assertTrue(objs, "the court placed no objects")
        for o in objs:
            self.assertTrue(court.rect.contains_cell(o.pos), (o.template,
                                                              o.pos))
        # every free court cell is still one walk: flood from the open edge
        rect_cells = {(x, y) for x in range(cx, cx + rw) for y in range(cy, cy + rh)}
        blocked = set(world.solid_walls)
        free = rect_cells - blocked
        edge = {c for c in free
                if c[0] in (cx, cx + rw - 1) or c[1] in (cy, cy + rh - 1)}
        self.assertTrue(edge, "the court keeps no open edge cell")
        seen, stack = {next(iter(edge))}, [next(iter(edge))]
        while stack:
            x, y = stack.pop()
            for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if c in free and c not in seen:
                    seen.add(c)
                    stack.append(c)
        self.assertEqual(seen, free,
                         f"{len(free - seen)} court cell(s) cut off")


if __name__ == "__main__":
    unittest.main()
