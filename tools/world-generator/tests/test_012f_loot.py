"""Brief 012f change 3: the P2 item catalogue and loot pools — validation,
sanitizing, the plan parser's strict pool references, and the per-placement
starting inventories the spec writer draws (seeded, quality-weighted, scaled
by the plan's "loot" setting)."""
import json
import os
import unittest

import worldgen
from worldgen import loot as loot_mod
from worldgen import phases
from worldgen.model import LootPool, ItemTemplate, parse_plan

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def item(name, **kw):
    d = {"name": name, "type": "misc", "quality": "common", "value": 2,
         "description": f"{name}.", "physicalDescription": f"{name}, white background"}
    d.update(kw)
    return d


def p2_reply(items=(), pools=None):
    d = {"templates": [{"name": "Box", "size": [1, 1], "walkability": 0,
                        "description": "d", "physicalDescription": "p", "rule": "r"}],
         "items": list(items)}
    if pools is not None:
        d["lootPools"] = pools
    return d


class TestCheckP2Items(unittest.TestCase):
    def test_items_and_pools_validate(self):
        d = p2_reply(items=[item("Bread"), item("Knife", quality="rare", value=9)],
                     pools={"Kitchen cupboard": {"items": ["Bread", "Knife"],
                                                 "weights": {"Knife": 0.4}}})
        self.assertEqual(phases.check_p2(d), [])

    def test_bad_type_quality_value(self):
        d = p2_reply(items=[item("Bread", type="weapon", quality="shiny", value=0)])
        errs = phases.check_p2(d)
        self.assertTrue(any("type" in e for e in errs))
        self.assertTrue(any("quality" in e for e in errs))
        self.assertTrue(any("value" in e for e in errs))

    def test_pools_as_a_list_or_object_both_parse(self):
        for pools in ({"Kitchen": {"items": ["Bread"]}},
                      [{"name": "Kitchen", "items": ["Bread"]}]):
            d = p2_reply(items=[item("Bread")], pools=pools)
            self.assertEqual([e for e in phases.check_p2(d) if "pool" in e], [])


class TestSanitizeP2Items(unittest.TestCase):
    def logged(self, d):
        out = []
        return phases.sanitize_p2(d, out), out

    def test_white_background_is_appended(self):
        d = p2_reply(items=[item("Bread", physicalDescription="a loaf")])
        d, log = self.logged(d)
        self.assertTrue(d["items"][0]["physicalDescription"].endswith("white background"))
        self.assertTrue(any("white background" in r for (_w, r) in log))

    def test_fixes_and_unknown_pool_items_dropped(self):
        d = p2_reply(items=[item("Bread"), item("Knife", quality="junk", type="sword")],
                     pools={"Kitchen": {"items": ["Bread", "Nope", 7],
                                        "weights": {"Knife": 2, "Nope": 1}}})
        d, log = self.logged(d)
        self.assertEqual([i["name"] for i in d["items"]], ["Bread", "Knife"])
        knife = d["items"][1]
        self.assertEqual((knife["type"], knife["quality"]), ("misc", "common"))
        self.assertEqual(d["lootPools"]["Kitchen"]["items"], ["Bread"])
        self.assertEqual(d["lootPools"]["Kitchen"]["weights"], {})
        self.assertTrue(any("Nope" in r for (_w, r) in log))

    def test_pool_without_real_items_is_dropped(self):
        d = p2_reply(items=[item("Bread")], pools={"Empty": {"items": ["Nope"]}})
        d, log = self.logged(d)
        self.assertEqual(d["lootPools"], {})
        self.assertTrue(any("no real items" in r for (_w, r) in log))

    def test_template_default_pool_must_survive(self):
        d = p2_reply(items=[item("Bread")], pools={"Kitchen": {"items": ["Bread"]}})
        d["templates"][0]["lootPool"] = "Pantry"
        d, log = self.logged(d)
        self.assertNotIn("lootPool", d["templates"][0])
        d = p2_reply(items=[item("Bread")], pools={"Kitchen": {"items": ["Bread"]}})
        d["templates"][0]["lootPool"] = "Kitchen"
        d, _ = self.logged(d)
        self.assertEqual(d["templates"][0]["lootPool"], "Kitchen")


class TestParsePlanItems(unittest.TestCase):
    def plan(self, **over):
        d = {"name": "W", "zones": [{"name": "Z", "kind": "village", "sizeClass": "medium",
                                     "description": "d", "ground": "grass",
                                     "buildings": [{"name": "Home", "kind": "house",
                                                    "sizeClass": "small", "purpose": "p"}],
                                     "dressing": {"paths": "dirt"}}],
             "templates": [{"name": "Box", "size": [1, 1], "walkability": 0}],
             "items": [item("Bread"), item("Knife", quality="rare", value=9)],
             "lootPools": {"Kitchen": {"items": ["Bread", "Knife"]}}}
        d.update(over)
        return d

    def test_items_and_pools_parse(self):
        plan = parse_plan(self.plan(loot="sparse"))
        self.assertEqual([i.name for i in plan.items], ["Bread", "Knife"])
        self.assertEqual(plan.loot_pools["Kitchen"].items, ["Bread", "Knife"])
        self.assertEqual(plan.extras["loot"], "sparse")

    def test_unknown_pool_reference_raises(self):
        d = self.plan()
        d["buildings"] = [{"name": "Home", "wall": "wood", "ground": "wood",
                           "rooms": [{"name": "Hall", "share": "small",
                                      "lootPool": "Pantry"}],
                           "connections": [], "entrance": {"room": "Hall", "side": "south"},
                           "furniture": [{"template": "Box", "room": "Hall",
                                          "lootPool": "Also Not"}]}]
        with self.assertRaises(ValueError) as cm:
            parse_plan(d)
        self.assertIn("Pantry", str(cm.exception))

    def test_pool_naming_unknown_items_raises(self):
        with self.assertRaises(ValueError):
            parse_plan(self.plan(lootPools={"Kitchen": {"items": ["Soup"]}}))

    def test_bad_loot_setting_raises(self):
        with self.assertRaises(ValueError):
            parse_plan(self.plan(loot="generous"))


class TestDrawInventory(unittest.TestCase):
    POOL = LootPool(name="P", items=["Bread", "Ring"],
                    weights={"Ring": 0.05})
    ITEMS = {"Bread": ItemTemplate(name="Bread", quality="common"),
             "Ring": ItemTemplate(name="Ring", quality="legendary")}

    def test_same_seed_same_draw_and_copies_differ(self):
        a = loot_mod.draw_inventory(self.POOL, self.ITEMS, "seed|Box|1")
        b = loot_mod.draw_inventory(self.POOL, self.ITEMS, "seed|Box|1")
        self.assertEqual(a, b)
        c = loot_mod.draw_inventory(self.POOL, self.ITEMS, "seed|Box|2")
        # not guaranteed different every seed, but across 24 copies some differ
        draws = {tuple(loot_mod.draw_inventory(self.POOL, self.ITEMS, f"s|Box|{i}"))
                 for i in range(1, 25)}
        self.assertGreater(len(draws), 1)

    def test_counts_scale_with_the_setting(self):
        for setting, expect_empty in (("none", True), ("sparse", False)):
            draws = [loot_mod.draw_inventory(self.POOL, self.ITEMS, f"s|B|{i}", setting)
                     for i in range(30)]
            if expect_empty:
                self.assertTrue(all(d == [] for d in draws))
            else:
                self.assertTrue(any(d for d in draws))

    def test_quality_weighting_favours_the_common_item(self):
        def has_bread(i):
            inv = loot_mod.draw_inventory(self.POOL, self.ITEMS, f"s|B|{i}", "rich")
            return any(n == "Bread" for (n, _c) in inv)
        common = sum(1 for i in range(60) if has_bread(i))
        self.assertGreater(common, 30)

    def test_no_pool_or_no_items_is_empty(self):
        self.assertEqual(loot_mod.draw_inventory(None, self.ITEMS, "x"), [])
        empty = LootPool(name="E", items=[])
        self.assertEqual(loot_mod.draw_inventory(empty, self.ITEMS, "x"), [])


class TestSpecInventories(unittest.TestCase):
    """A small hand plan with one pool on a furniture line and one on a room:
    the spec's placements carry per-placement inventories drawn from the
    resolved pool, and the builder's itemTemplates section is emitted."""

    def setUp(self):
        with open(os.path.join(FIXTURES, "village.json"), encoding="utf-8") as f:
            self.data = json.load(f)
        self.data["templates"].append(
            {"name": "Chest", "size": [1, 1], "walkability": 0, "tags": ["storage"],
             "description": "A chest.", "physicalDescription": "a chest",
             "rule": "in a corner"})
        home = next(b for b in self.data["buildings"]
                    if b["name"] == self.data["zones"][0]["buildings"][0]["name"])
        home["rooms"][0]["lootPool"] = "Home chest"
        home["furniture"].append({"template": "Chest", "room": home["rooms"][0]["name"],
                                  "count": 2, "hint": "corner"})
        self.data["items"] = [item("Candle"), item("Ledger")]
        self.data["lootPools"] = {"Home chest": {"items": ["Candle", "Ledger"]}}

    def test_chests_carry_drawn_inventories(self):
        world = worldgen.run(self.data, seed=3)
        spec = worldgen.build_spec(world, self.data)
        chest = next(t for t in spec["objectTemplates"] if t["name"] == "Chest")
        self.assertIn("placements", chest)
        invs = [p.get("inventory") for p in chest["placements"]
                if isinstance(p, dict)]
        self.assertTrue(invs, "the chest placements carry inventories")
        names = {n for inv in invs for (n, _c) in inv}
        self.assertTrue(names <= {"Candle", "Ledger"}, names)
        self.assertEqual({i["name"] for i in spec["itemTemplates"]},
                         {"Candle", "Ledger"})
        # the same seed re-rolls the same inventories
        world2 = worldgen.run(self.data, seed=3)
        spec2 = worldgen.build_spec(world2, self.data)
        chest2 = next(t for t in spec2["objectTemplates"] if t["name"] == "Chest")
        self.assertEqual([p for p in chest["placements"] if isinstance(p, dict)],
                         [p for p in chest2["placements"] if isinstance(p, dict)])

    def test_loot_none_leaves_them_empty(self):
        self.data["loot"] = "none"
        world = worldgen.run(self.data, seed=3)
        spec = worldgen.build_spec(world, self.data)
        chest = next(t for t in spec["objectTemplates"] if t["name"] == "Chest")
        self.assertTrue(all(not isinstance(p, dict) or not p["inventory"]
                            for p in chest["placements"]))


if __name__ == "__main__":
    unittest.main()
