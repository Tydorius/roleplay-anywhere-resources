"""Room library build step 1: pieces with a back turn to their wall, round a
table they face it, they turn to fit, and wall:/row: take far, side and near
from the room's main door. The turn reaches the scenario as rot plus the
turned size. Pieces without a back never turn, so the plain route is unchanged."""
import copy
import json
import os
import random
import shutil
import tempfile
import unittest

from tests import util
from worldgen import api
from worldgen.hints import parse
from worldgen.layout_room import TURN_SIDES, layout_room, turned
from worldgen.model import FurniturePlan, ObjectTemplate, Rect


def templates():
    return {
        "Bed": ObjectTemplate(name="Bed", size=(1, 2), extras={"forSleep": True, "back": "north"}),
        "Desk": ObjectTemplate(name="Desk", size=(2, 1), extras={"back": "north"}),
        "Table": ObjectTemplate(name="Table", size=(2, 2)),
        "Chair": ObjectTemplate(name="Chair", size=(1, 1), extras={"back": "north"}),
        "Bench": ObjectTemplate(name="Bench", size=(3, 1), extras={"back": "north"}),
        "Plain bed": ObjectTemplate(name="Plain bed", size=(1, 2), extras={"forSleep": True}),
    }


def room(w, h, door_side):
    """A room at (0, 0) with one door in the middle of the named wall."""
    rect = Rect(0, 0, w, h)
    door = {"south": (w // 2, 0), "north": (w // 2, h - 1),
            "west": (0, h // 2), "east": (w - 1, h // 2)}[door_side]
    return rect, door


def against(rect, pos, size):
    """The walls a footprint touches from inside."""
    inter = rect.interior()
    out = set()
    if pos[1] == inter.y:
        out.add("south")
    if pos[1] + size[1] - 1 == inter.y1:
        out.add("north")
    if pos[0] == inter.x:
        out.add("west")
    if pos[0] + size[0] - 1 == inter.x1:
        out.add("east")
    return out


class TestRelativeWalls(unittest.TestCase):
    def test_hints_accept_far_side_near(self):
        h = parse("wall:far+corner")
        self.assertEqual(h.walls, ("far",))
        self.assertEqual(parse("row:side").row, "side")
        self.assertEqual(parse("wall:near").unknown, ())

    def test_far_wall_and_back_to_it(self):
        t = templates()
        for door_side, far in (("south", "north"), ("north", "south"),
                               ("east", "west"), ("west", "east")):
            with self.subTest(door=door_side):
                rect, door = room(8, 8, door_side)
                out = layout_room(rect, [door], [FurniturePlan("Bed", "R", 1, "wall:far")],
                                  t, random.Random(1))
                (name, pos), = out.placements
                rot = out.rot(name, pos)
                size = turned(t["Bed"].size, rot)
                self.assertIn(far, against(rect, pos, size))
                self.assertEqual(TURN_SIDES[rot], far, "the headboard is against the far wall")

    def test_near_and_side_walls(self):
        t = templates()
        rect, door = room(9, 9, "south")
        out = layout_room(rect, [door], [FurniturePlan("Desk", "R", 1, "wall:near")],
                          t, random.Random(2))
        (name, pos), = out.placements
        self.assertEqual(TURN_SIDES[out.rot(name, pos)], "south")
        out = layout_room(rect, [door], [FurniturePlan("Desk", "R", 1, "wall:side")],
                          t, random.Random(2))
        (name, pos), = out.placements
        side = TURN_SIDES[out.rot(name, pos)]
        self.assertIn(side, ("east", "west"))
        self.assertIn(side, against(rect, pos, turned(t["Desk"].size, out.rot(name, pos))))

    def test_a_piece_that_never_turns_still_finds_the_far_wall(self):
        t = templates()
        rect, door = room(8, 8, "west")
        out = layout_room(rect, [door], [FurniturePlan("Plain bed", "R", 1, "wall:far")],
                          t, random.Random(1))
        (name, pos), = out.placements
        self.assertEqual(out.turns, {})
        self.assertIn("east", against(rect, pos, t["Plain bed"].size))


class TestTurning(unittest.TestCase):
    def test_chairs_face_the_table(self):
        t = templates()
        rect, door = room(10, 10, "south")
        out = layout_room(rect, [door], [FurniturePlan("Table", "R", 1, "center"),
                                         FurniturePlan("Chair", "R", 4, "around:Table")],
                          t, random.Random(3))
        tpos = next(p for (n, p) in out.placements if n == "Table")
        tc = (tpos[0] + 0.5, tpos[1] + 0.5)
        chairs = [(p, out.rot("Chair", p)) for (n, p) in out.placements if n == "Chair"]
        self.assertEqual(len(chairs), 4)
        for (p, rot) in chairs:
            back = TURN_SIDES[rot]
            # the back points away from the table
            away = {"north": p[1] > tc[1], "south": p[1] < tc[1],
                    "east": p[0] > tc[0], "west": p[0] < tc[0]}[back]
            self.assertTrue(away, (p, back))

    def test_a_long_piece_turns_to_fit(self):
        t = templates()
        # interior 2 wide and 5 tall: a 3x1 bench only fits turned
        rect, door = room(4, 7, "south")
        out = layout_room(rect, [door], [FurniturePlan("Bench", "R", 1, "")],
                          t, random.Random(5))
        (name, pos), = out.placements
        self.assertEqual(out.rot(name, pos) % 2, 1)
        self.assertEqual(out.size_of(name, pos, t), (1, 3))

    def test_pieces_without_a_back_place_as_before(self):
        t = templates()
        rect, door = room(8, 8, "south")
        plan = [FurniturePlan("Plain bed", "R", 2, "wall:north"),
                FurniturePlan("Table", "R", 1, "center")]
        a = layout_room(rect, [door], plan, t, random.Random(9))
        no_back = {k: ObjectTemplate(name=v.name, size=v.size) for k, v in t.items()}
        b = layout_room(rect, [door], plan, no_back, random.Random(9))
        self.assertEqual(a.placements, b.placements)
        self.assertEqual(a.turns, {})


class TestRotInTheScenario(unittest.TestCase):
    def test_turned_pieces_reach_the_scenario(self):
        data = copy.deepcopy(util.load_plan("village.json"))
        for tm in data["templates"]:
            if tm["name"] in ("Straw bed", "Trestle table", "Long bench", "Clay hearth"):
                tm["back"] = "north"
        tmp = tempfile.mkdtemp(prefix="worldgen-rot-")
        try:
            s = api._layout_and_build(data, seed=1, out_dir=os.path.join(tmp, "v"))
            self.assertTrue(s["ok"], s)
            self.assertEqual(s["validator_errors"], 0, s)
            with open(os.path.join(s["out"], s["zip"][:-4], "scenario.json"), encoding="utf-8") as f:
                scen = json.load(f)
            sizes = {t["id"]: t["size"] for t in scen["objectTemplates"]}
            turned_objs = [e for e in scen["entities"] if e.get("type") == "object" and e.get("rot")]
            self.assertTrue(turned_objs, "some backed piece was turned")
            for e in turned_objs:
                w, h = sizes[e["templateId"]]
                want = [h, w] if e["rot"] % 2 else [w, h]
                self.assertEqual(e["size"], want, e["name"])
                self.assertIn(e["rot"], (1, 2, 3))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
