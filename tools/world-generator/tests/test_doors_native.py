"""Anywhere RPG 1.0 door objects on every doorway of a generated world: the
Python port of the editor's doorway rules (world10.js) agrees with
hand-worked cases, hung doors sit zero-wide on the wall line in the doorway's
room's own kind (a holding cell barred), and a built fixture world ships with
no doorway left open and the vendored 1.0 checker silent."""
import json
import os
import shutil
import tempfile
import unittest

from worldgen import native
from worldgen.vendor import scenario_checks

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def door_world():
    """A 24x24 map with a 6x6 house at [4,4] and one door out on its south
    wall."""
    return {
        "gridSize": [24, 24],
        "regions": [
            {"id": "house", "name": "House", "wall": "wood",
             "position": [4, 4], "size": [6, 6], "openings": [[6, 4]]},
        ],
        "entities": [], "objectTemplates": [],
    }


def split_world():
    """The same house split into a 2x6 west room and a 4x4 east room, with
    the outer door at [6,4] and a matching pair of openings on the wall the
    rooms share at y = 7."""
    return {
        "gridSize": [24, 24],
        "regions": [
            {"id": "house", "name": "House", "wall": "wood",
             "position": [4, 4], "size": [6, 6], "openings": [[6, 4]]},
            {"id": "west", "name": "West room", "wall": "wood",
             "position": [4, 4], "size": [2, 6], "openings": [[5, 7]]},
            {"id": "east", "name": "East room", "wall": "wood",
             "position": [6, 6], "size": [4, 4], "openings": [[6, 7]]},
        ],
        "entities": [], "objectTemplates": [],
    }


class TestDoorways(unittest.TestCase):
    """doorways() against the same hand-worked maps as the editor's tests."""

    def test_a_south_wall_opening_gives_one_doorway_and_its_placement(self):
        dws = native.doorways(door_world())
        self.assertEqual(len(dws), 1)
        dw = dws[0]
        self.assertEqual((dw["cell"], dw["out"], dw["key"]),
                         ((6, 4), (6, 3), "6,3,y"))
        self.assertEqual(dw["room"]["id"], "house")
        self.assertEqual(native.door_placement(dw),
                         {"pos": [6, 4], "rot": 0, "size": [1, 0]})

    def test_a_shared_wall_with_matching_openings_is_one_doorway(self):
        dws = native.doorways(split_world())
        self.assertEqual(len(dws), 2, "the outer door and the shared wall")
        shared = [d for d in dws if d["key"] == "5,7,x"]
        self.assertEqual(len(shared), 1, "the facing pair counts once")
        self.assertEqual((shared[0]["cell"], shared[0]["out"]),
                         ((5, 7), (6, 7)))
        self.assertEqual(shared[0]["room"]["id"], "west", "2x6 beats 4x4")
        outer = [d for d in dws if d["key"] == "6,3,y"][0]
        self.assertEqual(outer["room"]["id"], "house")

    def test_an_opening_in_one_wall_but_not_the_other_is_no_doorway(self):
        scn = split_world()
        scn["regions"][2]["openings"] = []      # the east side stays shut
        self.assertEqual([d["key"] for d in native.doorways(scn)], ["6,3,y"])

    def test_a_corner_opening_is_a_doorway_on_both_sides(self):
        scn = door_world()
        scn["regions"][0]["openings"] = [[4, 4]]
        self.assertEqual([(d["cell"], d["out"], d["key"], d["room"]["id"])
                          for d in native.doorways(scn)],
                         [((4, 4), (4, 3), "4,3,y", "house"),
                          ((4, 4), (3, 4), "3,4,x", "house")])

    def test_opening_sides_pick_a_third_value_only_when_the_cell_is_there(self):
        house = {"position": [4, 4], "size": [6, 6]}     # rect [4,4] to [9,9]
        self.assertEqual(native.opening_sides(house, [4, 4]), ["s", "w"])
        self.assertEqual(native.opening_sides(house, [4, 4, "w"]), ["w"])
        self.assertEqual(native.opening_sides(house, [4, 4, "n"]), ["s", "w"],
                         "a side it is not on opens nothing")
        self.assertEqual(native.opening_sides(house, [10, 4]), [],
                         "off the rectangle")


class TestDoorObjects(unittest.TestCase):
    def test_placement_and_rotation_along_x_and_along_y(self):
        scn = door_world()
        along_y = native.doorways(scn)[0]        # the way out is one cell south
        self.assertEqual(native.door_placement(along_y),
                         {"pos": [6, 4], "rot": 0, "size": [1, 0]})
        scn["regions"][0]["openings"] = [[4, 6]]  # the way out is one cell west
        along_x = native.doorways(scn)[0]
        self.assertEqual(native.door_placement(along_x),
                         {"pos": [4, 6], "rot": 1, "size": [0, 1]})
        e = native.hang_door(scn, along_x, "door", native.Ids(scn))
        self.assertEqual((e["pos"], e["size"], e["rot"]), ([4, 6], [0, 1], 1))
        self.assertEqual(native.door_key_of(e), "3,6,x")
        self.assertTrue(e["id"].startswith("obj_"))
        self.assertTrue(scn["objectTemplates"][0]["id"].startswith("otpl_"))

    def test_hang_doors_hangs_one_per_doorway_and_names_after_the_template(self):
        scn = split_world()
        self.assertEqual(native.hang_doors(scn), 2)
        self.assertEqual([(e["name"], e["pos"], e["size"], e.get("rot", 0))
                          for e in scn["entities"]],
                         [("Door 1", [6, 4], [1, 0], 0),
                          ("Door 2", [6, 7], [0, 1], 1)])
        self.assertEqual(len(scn["objectTemplates"]), 1)
        self.assertEqual({k: v for k, v in scn["objectTemplates"][0].items()
                          if k != "id"},
                         {"name": "Door", "size": [1, 0], "walkability": 1,
                          "door": "door", "heightM": 2.1, "maxHp": 60})
        self.assertEqual(native.hang_doors(scn), 0, "nothing left to hang")
        self.assertEqual(native.door_counts(scn), {"door": 2})

    def test_hang_doors_uses_the_rooms_kind_and_skips_none(self):
        scn = split_world()
        scn["regions"][0]["door"] = "none"       # its own doorway stays open
        scn["regions"][1]["door"] = "bars"       # the shared doorway's room
        self.assertEqual(native.hang_doors(scn), 1)
        self.assertEqual([e["name"] for e in scn["entities"]],
                         ["Barred door 1"])
        self.assertEqual({k: v for k, v in scn["objectTemplates"][0].items()
                          if k != "id"},
                         {"name": "Barred door", "size": [1, 0],
                          "walkability": 1, "door": "bars", "heightM": 2.1,
                          "maxHp": 60})


class TestFixtureWorldDoors(unittest.TestCase):
    """medieval-glm-plan.json built end to end, with the mill's Meal Store
    rewritten in the plan as a holding cell: the build stays clean, every
    doorway ships hung, the cell's doors are bars, and the vendored 1.0
    checker reports nothing against the shipped world."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-doors-native-")
        cls.data = load("medieval-glm-plan.json")
        for g in cls.data["buildings"]:
            if g["name"] == "Millbrook Mill":
                for r in g["rooms"]:
                    if r["name"] == "Meal Store":
                        r["purpose"] = ("a stone holding cell where the miller "
                                        "shuts grain thieves overnight")
        from worldgen import api
        cls.summary = api._layout_and_build(cls.data, seed=1, out_dir=cls.tmp)
        path = os.path.join(cls.summary["out"],
                            cls.summary["zip"][:-len(".zip")], "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)
        cls.path = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_no_doorway_is_left_open(self):
        doors = native.doors_by_key(self.scn)
        missing = [dw["key"] for dw in native.doorways(self.scn)
                   if dw["room"].get("door", "door") != "none"
                   and not doors.get(dw["key"])]
        self.assertEqual(missing, [], missing)
        self.assertTrue(doors, "the world carries door objects at all")

    def test_every_door_object_sits_on_a_doorway(self):
        keys = {dw["key"] for dw in native.doorways(self.scn)}
        stray = [k for k in native.doors_by_key(self.scn) if k not in keys]
        self.assertEqual(stray, [], stray)

    def test_the_holding_cell_room_gets_bars(self):
        by_name = {r["name"]: r for r in self.scn["regions"]}
        cell = by_name["Millbrook Mill Meal Store"]
        self.assertEqual(cell["door"], "bars")
        tpl = {t["id"]: t for t in self.scn["objectTemplates"]}
        doors = native.doors_by_key(self.scn)
        barred = [e for dw in native.doorways(self.scn)
                  if dw["room"] is cell for e in doors.get(dw["key"], [])]
        self.assertTrue(barred, "the cell's doorway has a door")
        for e in barred:
            self.assertEqual(tpl[e["templateId"]]["door"], "bars")
            self.assertEqual(tpl[e["templateId"]]["name"], "Barred door")

    def test_the_summary_counts_the_doors_by_kind(self):
        self.assertEqual(self.summary["doors"],
                         native.door_counts(self.scn))
        self.assertIn("door", self.summary["doors"])

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)


if __name__ == "__main__":
    unittest.main()
