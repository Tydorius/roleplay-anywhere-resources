"""A turned object covers its turned footprint everywhere the generator asks
which cells it takes: one shared helper turns a placed object's template size
by its rot, so the schedules, the checks, the native view and the stair
planning all see the 1x3 column a turned 3x1 counter really covers — the same
cells the builder and the game use. Found by the Cold Harbor model-test plan:
Signe Stonehand started on the third cell of a turned tap counter."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import ObjectOut, RegionOut, World, api, checks, schedule
from worldgen.extensions import expand
from worldgen.layout_room import object_cells, object_rect
from worldgen.model import ObjectTemplate, Rect

PLAN = os.path.join(os.path.dirname(__file__), "data", "cold-harbor-dots.plan.json")


def _world():
    """A bare zone world whose one template is a 3x1 counter."""
    w = World()
    w.grid = (9, 9)
    w.templates = {"Counter": ObjectTemplate("Counter", (3, 1), walkability=0.0)}
    w.regions = [RegionOut("Village", Rect(0, 0, 9, 9), "zone")]
    w.regions_by_name = {r.name: r for r in w.regions}
    return w


class TestTheHelper(unittest.TestCase):
    def test_rot_1_and_3_cover_the_turned_cells(self):
        w = _world()
        obj = ObjectOut("Counter", (4, 3), "Village", rot=1)
        self.assertEqual(object_cells(w, obj), {(4, 3), (4, 4), (4, 5)})
        self.assertEqual(object_rect(w, obj), Rect(4, 3, 1, 3))
        obj.rot = 3
        self.assertEqual(object_cells(w, obj), {(4, 3), (4, 4), (4, 5)})

    def test_rot_0_and_2_cover_the_unturned_cells(self):
        w = _world()
        obj = ObjectOut("Counter", (4, 3), "Village")
        self.assertEqual(object_cells(w, obj), {(4, 3), (5, 3), (6, 3)})
        obj.rot = 2
        self.assertEqual(object_cells(w, obj), {(4, 3), (5, 3), (6, 3)})


class TestFreeCell(unittest.TestCase):
    def test_free_cell_never_returns_a_cell_under_the_turned_object(self):
        w = _world()
        # a 3x1 counter turned to a 1x3 column at (4, 3): the cell under the
        # room's centre anchor (4, 4) looks free only when unturned
        w.objects = [ObjectOut("Counter", (4, 3), "Village", rot=1)]
        cell = schedule.free_cell(w, "Village", connected={(4, 4), (2, 2)})
        self.assertEqual(cell, (2, 2))


class TestWalkabilityGrid(unittest.TestCase):
    def test_the_grid_blocks_the_turned_cells_not_the_unturned_ones(self):
        w = _world()
        w.objects = [ObjectOut("Counter", (4, 3), "Village", rot=1)]
        blocked, _doors = checks.walkability_grid(w, checks.compute_openings(w))
        self.assertEqual(blocked, {(4, 3), (4, 4), (4, 5)})


class TestColdHarbor(unittest.TestCase):
    def test_the_plan_builds_and_no_start_sits_on_a_turned_object(self):
        with open(PLAN, "r", encoding="utf-8") as f:
            data = json.load(f)
        tmp = tempfile.mkdtemp(prefix="worldgen-turned-")
        try:
            s = api._layout_and_build(data, seed=1, out_dir=os.path.join(tmp, "v"))
            self.assertTrue(s["ok"], s)
            self.assertEqual(s["validator_errors"], 0, s)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        world = worldgen.run(data, seed=1, extensions=expand(set(data.get("extensions", ()))))
        under = {}
        for o in world.objects:
            for cell in object_cells(world, o):
                under.setdefault(cell, o.template)
        for c in world.characters:
            hit = under.get(tuple(c.pos))
            self.assertIsNone(hit, f"{c.name} starts at {tuple(c.pos)} on {hit}")


if __name__ == "__main__":
    unittest.main()
