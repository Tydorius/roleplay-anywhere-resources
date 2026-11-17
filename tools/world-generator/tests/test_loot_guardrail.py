"""loot-02: the guardrails — a container that would ship empty is a warning,
and the summary says so. A container placement (a template with a loot pool
of its own, or one the room library tags storage) that resolves no pool draws
no starting inventory: run_checks warns once per building and once for a
whole world whose containers all ship empty, without failing the build."""
import copy
import os
import tempfile
import unittest

import worldgen
from worldgen import api, library_plan
from tests.test_loot_library import LIB, POOLS, _design, _item

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "..", "fixtures")

# a pool per purpose the fixture rooms use, so every library container binds
STOCKED_POOLS = dict(POOLS, Chapel={"items": ["Candle"]})


def _plan(pools):
    """The loot-01 fixture as a whole plan; ``pools`` decides whether the
    library containers bind a pool (one named after each purpose) or would
    ship empty."""
    design, b = _design()
    reg = library_plan.registry_for(LIB, "w", taken=set())
    library_plan.expand_design(LIB, reg, design, b, "medieval", "fantasy", "w", [],
                               pools=set(pools))
    return {
        "name": "W", "setting": {}, "mapSize": "small",
        "zones": [{"name": "Z", "kind": "village", "sizeClass": "medium",
                   "description": "d", "ground": "grass", "buildings": [b],
                   "dressing": {"paths": "dirt"}}],
        "roads": [], "templates": reg.templates(),
        "items": [_item(n) for n in ("Bread", "Flour sack", "Knife",
                                     "Nails", "Rope", "Candle")],
        "lootPools": copy.deepcopy(pools), "buildings": [design],
        "npcs": [], "player": {"name": "P", "gender": "female",
                               "role": "villager", "home": ""}}


def _containers(world):
    """The world's container placements, as the checks see them: templates
    with a loot pool of their own or the storage tag."""
    return [o for o in world.objects
            if (world.templates[o.template].extras.get("lootPool")
                or "storage" in (world.templates[o.template].tags or []))]


class LibraryContainersAreTagged(unittest.TestCase):
    def test_container_templates_carry_the_storage_tag(self):
        design, b = _design()
        reg = library_plan.registry_for(LIB, "w", taken=set())
        library_plan.expand_design(LIB, reg, design, b, "medieval", "fantasy",
                                   "w", [], pools=set(POOLS))
        boxes = [t for t in reg.templates() if t.get("container")]
        self.assertTrue(boxes)
        for t in boxes:
            self.assertIn("storage", t["tags"], t["name"])


class EmptyContainersWarn(unittest.TestCase):
    """A built fixture world whose library containers bind no pool: one
    warning line per building, and one note for the whole world."""

    def setUp(self):
        self.plan = _plan({})
        self.world = worldgen.run(copy.deepcopy(self.plan), seed=4)

    def test_one_warning_line_per_building_counting_the_placements(self):
        n = sum(1 for o in _containers(self.world)
                if o.region.startswith("Bakehouse"))
        self.assertGreaterEqual(n, 3)      # the one-line cap is doing real work
        lines = [w for w in self.world.metrics["map_warnings"]
                 if w.startswith("Bakehouse: ")]
        self.assertEqual(lines,
                         [f"Bakehouse: {n} containers would ship empty"])

    def test_the_whole_world_gets_one_note(self):
        notes = [w for w in self.world.metrics["map_warnings"]
                 if w.startswith("no container in the whole world")]
        self.assertEqual(notes,
                         [f"no container in the whole world ships loot: "
                          f"{len(_containers(self.world))} placed, "
                          f"none resolves a pool"])


class StockedContainersStaySilent(unittest.TestCase):
    def test_a_stocked_world_reports_neither(self):
        plan = _plan(STOCKED_POOLS)
        world = worldgen.run(copy.deepcopy(plan), seed=4)
        self.assertTrue(_containers(world))
        warned = [w for w in world.metrics["map_warnings"]
                  if "ship empty" in w or "ships loot" in w]
        self.assertEqual(warned, [])


class WarningsDoNotFailTheBuild(unittest.TestCase):
    def test_a_world_that_ships_empty_containers_still_builds_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.relayout(os.path.join(FIXTURES, "village.json"),
                                   seed=3, out_dir=tmp)
        self.assertTrue(summary["ok"], summary)
        warned = summary["map_warnings"]
        self.assertIn("Rose Cottage: 1 container would ship empty", warned)
        self.assertTrue(any("containers would ship empty" in w for w in warned))
        self.assertTrue(any(w.startswith("no container in the whole world")
                            for w in warned))


if __name__ == "__main__":
    unittest.main()
