"""loot-01: containers furnished by the room library draw loot again. P2's
prompts carry the library's purpose list so a pool is named after every
purpose, ``expand_design`` binds each container furniture line to its room's
purpose pool, and the spec's library container placements carry drawn
inventories. Non-container lines never gain one."""
import copy
import os
import tempfile
import unittest

import worldgen
from worldgen import api, library_plan
from tests.test_library_generate import RecordingClient, client as library_client
from tests.test_model import canned_replies

# the plan's pools: one named exactly after each purpose the fixture rooms
# use, plus decoys — "Bakery Store" holds "bakery" as a whole word but must
# lose to the exact name, "Bakehouse Store" and "Workshop shelf" match nothing
POOLS = {
    "Bakery": {"items": ["Bread", "Flour sack", "Knife"]},
    "Bakery Store": {"items": ["Bread"]},
    "Bakehouse Store": {"items": ["Bread"]},
    "Storage shelf": {"items": ["Nails", "Rope"]},
    "Storage sideboard": {"items": ["Candle"]},
    "Workshop shelf": {"items": ["Nails"]},
    "Cellar": {"items": ["Rope"]},
}
POOL_FOR_ROOM = {"Bakehouse": "Bakery", "Store room": "Storage shelf", "Nook": None}

LIB = library_plan.load()


def _item(name):
    return {"name": name, "type": "misc", "quality": "common", "value": 3,
            "description": f"{name}.", "physicalDescription": f"{name}, white background"}


def _design():
    """A library-shaped design (the shape ``phases.library_building`` makes:
    rooms with purposes, no furniture) plus its P1 building line."""
    return ({"name": "Bakehouse", "wall": "wood", "ground": "packed earth",
             "rooms": [{"name": "Bakehouse", "share": "large", "use": "bakery",
                        "purpose": "a floor white with flour"},
                       {"name": "Store room", "share": "small", "use": "storage",
                        "purpose": "sacks and bins"},
                       {"name": "Nook", "share": "small", "use": "chapel",
                        "purpose": "a quiet corner"}],
             "connections": [["Bakehouse", "Store room"], ["Bakehouse", "Nook"]],
             "entrance": {"room": "Bakehouse", "side": "south"}, "furniture": []},
            {"name": "Bakehouse", "kind": "bakery", "sizeClass": "small",
             "purpose": "the village bread", "residents": 0,
             "wealth": "modest", "condition": "kept"})


def _expand(design=None, b=None, pools=None):
    """A fresh registry furnishes a copy of the fixture design (binding on
    when ``pools`` is given) and returns (registry, the furnished copy)."""
    d, bb = _design()
    d = copy.deepcopy(design) if design is not None else d
    bb = b if b is not None else bb
    reg = library_plan.registry_for(LIB, "w", taken=set())
    library_plan.expand_design(LIB, reg, d, bb, "medieval", "fantasy", "w", [],
                               pools=set(POOLS) if pools is None else set(pools))
    return reg, d


class TestPoolForPurpose(unittest.TestCase):
    def test_exact_beats_whole_word_and_order_words_are_ignored(self):
        f = library_plan.pool_for_purpose
        self.assertEqual(f("bakery", POOLS), "Bakery")
        # both strip to "storage": the alphabetical first wins
        self.assertEqual(f("storage", POOLS), "Storage shelf")
        self.assertEqual(f("storage", ["Storage sideboard", "Storage shelf"]),
                         "Storage shelf")
        self.assertEqual(f("cellar", POOLS), "Cellar")

    def test_whole_word_containment_when_no_exact_name(self):
        f = library_plan.pool_for_purpose
        self.assertEqual(f("cellar", ["Cellar stores"]), "Cellar stores")
        self.assertEqual(f("master_bedroom", ["Master bedroom chest"]),
                         "Master bedroom chest")
        # a purpose that is only part of a word of the name never matches
        self.assertIsNone(f("shop", ["Workshop shelf"]))
        self.assertIsNone(f("bakery", ["Bakehouse Store", "Workshop shelf"]))
        self.assertIsNone(f("", POOLS))


class TestExpandDesignBindsContainers(unittest.TestCase):
    def test_container_lines_carry_the_purpose_pool_and_others_none(self):
        reg, design = _expand()
        by_room = {}
        for f in design["furniture"]:
            by_room.setdefault(f["room"], []).append(f)
        for room, pool in POOL_FOR_ROOM.items():
            lines = by_room[room]
            self.assertTrue(lines, room)
            for f in lines:
                if reg.is_container(f["template"]):
                    self.assertEqual(f.get("lootPool"), pool,
                                     f"{room}: {f['template']}")
                else:
                    self.assertNotIn("lootPool", f, f"{room}: {f['template']}")
        # the rooms really did place containers (the test is not vacuous)
        self.assertTrue(any(reg.is_container(f["template"]) for f in by_room["Bakehouse"]))
        self.assertTrue(any(reg.is_container(f["template"]) for f in by_room["Store room"]))

    def test_a_purpose_with_no_pool_leaves_it_unset(self):
        # only the bakery pool exists: the storage room places containers,
        # but with no storage pool their lines stay unset (never a bad name)
        reg, design = _expand(pools={"Bakery"})
        for f in design["furniture"]:
            if f["room"] != "Bakehouse":
                self.assertNotIn("lootPool", f, f"{f['room']}: {f['template']}")
        self.assertTrue(any(reg.is_container(f["template"])
                            for f in design["furniture"] if f["room"] == "Store room"))

    def test_without_pools_no_line_gains_one(self):
        reg, design = _expand(pools=set())
        self.assertFalse(any("lootPool" in f for f in design["furniture"]))

    def test_two_runs_bind_identical_pools(self):
        first = _expand()[1]["furniture"]
        second = _expand()[1]["furniture"]
        self.assertEqual([(f["template"], f["room"], f.get("lootPool")) for f in first],
                         [(f["template"], f["room"], f.get("lootPool")) for f in second])


class TestSpecInventories(unittest.TestCase):
    """The fixture as a whole plan, the shape ``phases.run_phases`` writes:
    library container placements draw inventories, others never do."""

    def setUp(self):
        design, b = _design()
        reg = library_plan.registry_for(LIB, "w", taken=set())
        library_plan.expand_design(LIB, reg, design, b, "medieval", "fantasy",
                                   "w", [], pools=set(POOLS))
        self.reg = reg
        self.plan = {
            "name": "W", "setting": {}, "mapSize": "small",
            "zones": [{"name": "Z", "kind": "village", "sizeClass": "medium",
                       "description": "d", "ground": "grass", "buildings": [b],
                       "dressing": {"paths": "dirt"}}],
            "roads": [], "templates": reg.templates(),
            "items": [_item(n) for n in ("Bread", "Flour sack", "Knife",
                                         "Nails", "Rope", "Candle")],
            "lootPools": copy.deepcopy(POOLS), "buildings": [design],
            "npcs": [], "player": {"name": "P", "gender": "female",
                                   "role": "villager", "home": ""}}
        # seed 4 draws non-empty inventories (probed over seeds 1-7 in setup:
        # 6-8 of the 9 container placements stocked under "normal")
        self.world = worldgen.run(copy.deepcopy(self.plan), seed=4)
        self.spec = worldgen.build_spec(self.world, self.plan)

    def _placements(self, container):
        names = {t["name"] for t in self.plan["templates"]
                 if bool(t.get("container")) == container}
        for t in self.spec["objectTemplates"]:
            if t["name"] in names:
                for p in t.get("placements", []):
                    yield t["name"], p

    def test_library_containers_draw_and_others_do_not(self):
        stocked = [p for _n, p in self._placements(True)
                   if isinstance(p, dict) and p.get("inventory")]
        self.assertGreaterEqual(len(stocked), 2)
        item_names = {i["name"] for i in self.plan["items"]}
        for p in stocked:
            for name, count in p["inventory"]:
                self.assertIsInstance(count, int)
                self.assertIn(name, item_names)
        for _n, p in self._placements(False):
            self.assertFalse(isinstance(p, dict) and p.get("inventory"))

    def test_the_summary_counts_them(self):
        counts = api._container_counts(self.spec, self.plan)
        total = sum(1 for _n, _p in self._placements(True))
        self.assertEqual(counts["total"], total)
        self.assertEqual(counts["stocked"],
                         sum(1 for _n, p in self._placements(True)
                             if isinstance(p, dict) and p.get("inventory")))
        self.assertGreaterEqual(counts["stocked"], 2)


class TestP2PromptCarriesThePurposes(unittest.TestCase):
    def test_on_the_library_names_a_pool_per_purpose_off_it_does_not(self):
        c = library_client()
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c, seed=3, cast=False,
                                   out_dir=tmp)
        self.assertTrue(summary["ok"], summary)
        for phase in ("p2", "p2-items"):
            self.assertIn("ROOM LIBRARY PURPOSES", c.prompts[phase], phase)
            self.assertIn("name one loot pool after each", c.prompts[phase].lower(),
                          phase)
            self.assertIn("vestry", c.prompts[phase], phase)
        c2 = RecordingClient(canned_replies())
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c2, seed=3, cast=False,
                                   out_dir=tmp, library=False)
        self.assertTrue(summary["ok"], summary)
        for phase in ("p2", "p2-items"):
            self.assertNotIn("vestry", c2.prompts[phase], phase)
            self.assertNotIn("ROOM LIBRARY PURPOSES", c2.prompts[phase], phase)


if __name__ == "__main__":
    unittest.main()
