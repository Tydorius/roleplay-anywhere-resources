"""The item library wired into P2 (the "Use item library" switch): the items
call carries a menu of shipped items instead of a blank page, the reply's
picks, variants and plot items expand into templates with library links, the
containers draw them, and the switch falls back to the old prompt when off or
when the menu is empty. The replies are canned; no network."""
import argparse
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.test_model import ScriptedClient, canned_replies
from worldgen import api, llm, phases
from worldgen import __main__ as wgmain
from worldgen import item_library as IL
from worldgen import library_items as LIT
from worldgen import settings as settings_mod

BAND = "medieval"          # what the canned P1's era words derive
GENRE = "medieval"         # no genre in the plan, so the band stands in


class QueuedItemsClient(ScriptedClient):
    """Every phase through the real Client machinery, validation and retries
    included, so the p2-items reply comes from the script's queue."""

    def call(self, *args, **kw):
        return llm.Client.call(self, *args, **kw)


def menu_entries():
    items = IL.load()
    if not items:
        raise unittest.SkipTest("library/items/ is empty or missing")
    entries = LIT.menu(items, BAND, GENRE)
    if len(entries) < 30 or not any(e["tintable"] for e in entries):
        raise unittest.SkipTest("the medieval menu is too small to test with")
    return entries


def library_reply(entries):
    """A reply in the library shape: pools of menu names, one variant, one
    plot item, everything resolvable."""
    names = [e["name"] for e in entries[:30]]
    return {
        "lootPools": {
            "Kitchen cupboard": {"items": names[:10] + ["Red ledger"],
                                 "weights": {names[0]: 0.4}},
            "Apothecary shelf": {"items": names[10:20]},
            "Barred chest": {"items": names[20:30] + ["Seal of the Drowned Choir"]},
        },
        "variants": [{"from": next(e["name"] for e in entries if e["tintable"]),
                      "name": "Red ledger", "tint": "red",
                      "description": "The steward's household accounts."}],
        "items": [{"name": "Seal of the Drowned Choir", "type": "misc",
                   "quality": "rare", "value": 400, "plot": True,
                   "description": "A wax seal the choir swore on.",
                   "physicalDescription": "A wax seal on a cord, white background"}],
    }


def tiny_reply(entries):
    return {"lootPools": {"Kitchen cupboard": {"items": [e["name"] for e in entries[:3]]}},
            "variants": [], "items": []}


OLD_ITEMS = {"items": [{"name": "Bread", "type": "consumable", "quality": "common",
                        "value": 3, "description": "A loaf.",
                        "physicalDescription": "A loaf, white background"}],
             "lootPools": {"Larder": {"items": ["Bread"]}}}


def run_replies(items_reply, player_items, barrel_pool=None):
    """The canned transcript with the bad p2 reply replaced by ``items_reply``
    (one reply, or a list of them when a test wants a retry first). The player
    reply gets a starting inventory of ``player_items`` (the check wants 2-5
    real items once the catalogue carries any), and, wanted, the barrel
    container template points at a loot pool."""
    replies = canned_replies()
    catalogue = json.loads(replies[2])
    if barrel_pool:
        barrel = next(t for t in catalogue["templates"] if t["name"] == "Oak barrel")
        barrel["lootPool"] = barrel_pool
        replies[2] = json.dumps(catalogue, ensure_ascii=False)
        # the canned P3 never asks for a barrel: put one in the mill so the
        # pool has a container to stock
        mill = json.loads(replies[3])
        mill["furniture"].append({"template": "Oak barrel",
                                  "room": mill["furniture"][0]["room"],
                                  "count": 1, "hint": "corner"})
        replies[3] = json.dumps(mill, ensure_ascii=False)
    player = json.loads(replies[8])
    player["player"]["inventory"] = [[n, 1] for n in player_items]
    replies[8] = json.dumps(player, ensure_ascii=False)
    if not isinstance(items_reply, list):
        items_reply = [items_reply]
    items = [json.dumps(r, ensure_ascii=False) for r in items_reply]
    return replies[:1] + items + replies[2:]


class TestTheItemsCallCarriesTheMenu(unittest.TestCase):
    def setUp(self):
        self.entries = menu_entries()

    def test_the_prompt_offers_the_menu_not_a_blank_page(self):
        c = QueuedItemsClient(run_replies(library_reply(self.entries),
                                          [self.entries[0]["name"], "Red ledger"]))
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c, seed=3, cast=False,
                                   out_dir=tmp, library=False)
        self.assertTrue(summary["ok"], summary)
        prompt = c.sent[1][1]["content"]           # the p2-items user prompt
        self.assertIn(f"THE ITEM MENU ({BAND})", prompt)
        self.assertIn(LIT.menu_lines(self.entries)[0], prompt)
        self.assertNotIn("30 to 60 items", prompt)

    def test_no_item_library_sends_the_old_prompt_unchanged(self):
        c = QueuedItemsClient(run_replies(OLD_ITEMS, ["Bread", "Bread"]))
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c, seed=3, cast=False,
                                   out_dir=tmp, library=False, item_library=False)
        self.assertTrue(summary["ok"], summary)
        prompt = c.sent[1][1]["content"]
        self.assertIn("30 to 60 items", prompt)
        self.assertNotIn("THE ITEM MENU", prompt)

    def test_an_empty_menu_falls_back_to_the_old_prompt(self):
        emitted = []
        c = QueuedItemsClient(run_replies(OLD_ITEMS, ["Bread", "Bread"]))
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(LIT, "menu", return_value=[]):
                summary = api.generate("a mill village", client=c, seed=3, cast=False,
                                       out_dir=tmp, library=False, emit=emitted.append)
        self.assertTrue(summary["ok"], summary)
        prompt = c.sent[1][1]["content"]
        self.assertIn("30 to 60 items", prompt)
        self.assertNotIn("THE ITEM MENU", prompt)
        self.assertTrue(any("the item library has no items for" in line
                            for line in emitted), emitted)


class TestTheReplyExpands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = menu_entries()
        cls.client = QueuedItemsClient(
            run_replies(library_reply(cls.entries),
                        [cls.entries[0]["name"], "Red ledger"],
                        barrel_pool="Kitchen cupboard"))
        cls.tmp = tempfile.mkdtemp(prefix="wg-item-lib-")
        cls.summary = api.generate("a mill village", client=cls.client, seed=3, cast=False,
                                   out_dir=cls.tmp, library=False)
        with open(os.path.join(cls.tmp, "plan.json"), encoding="utf-8") as f:
            cls.plan = json.load(f)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def by_name(self, name):
        return next(t for t in self.plan["items"] if t["name"] == name)

    def test_the_run_built(self):
        self.assertTrue(self.summary["ok"], self.summary)

    def test_menu_picks_become_templates_with_library_links(self):
        name = self.entries[0]["name"]
        t = self.by_name(name)
        e = self.entries[0]
        self.assertEqual(t["library"], {"item": e["item"]["id"], "look": e["look"]["key"],
                                        "tint": None})
        self.assertEqual(t["type"], e["item"]["type"])
        self.assertIn(t["name"], self.plan["lootPools"]["Kitchen cupboard"]["items"])

    def test_the_variant_and_the_plot_item_expand(self):
        red = self.by_name("Red ledger")
        self.assertEqual(red["library"]["tint"], "red")
        self.assertEqual(red["description"], "The steward's household accounts.")
        seal = self.by_name("Seal of the Drowned Choir")
        self.assertTrue(seal["plot"])
        self.assertNotIn("library", seal)
        self.assertEqual(seal["value"], 400)

    def test_the_containers_draw_library_items(self):
        with open(os.path.join(self.tmp, "spec.json"), encoding="utf-8") as f:
            spec = json.load(f)
        barrel = next(t for t in spec["objectTemplates"] if t["name"] == "Oak barrel")
        pool = set(self.plan["lootPools"]["Kitchen cupboard"]["items"])
        inventories = [p["inventory"] for p in barrel.get("placements", [])
                       if isinstance(p, dict)]
        self.assertTrue(any(inv for inv in inventories), inventories)
        names = {n for inv in inventories for (n, _c) in inv}
        self.assertTrue(names <= pool, names)
        shipped = {t["name"] for t in spec["itemTemplates"]}
        self.assertTrue(names <= shipped, (names, shipped))

    def test_p5_item_lines_include_them(self):
        player = next(m["content"] for ms in self.client.sent for m in ms
                      if "ITEMS THIS SETTING OFFERS" in m.get("content", ""))
        self.assertIn(f"- {self.entries[0]['name']}", player)
        self.assertIn("- Red ledger", player)
        self.assertIn("- Seal of the Drowned Choir", player)


class TestTooFewPooledItems(unittest.TestCase):
    def test_a_thin_reply_is_retried_with_the_check_message(self):
        entries = menu_entries()
        c = QueuedItemsClient(run_replies([tiny_reply(entries), library_reply(entries)],
                                          [entries[0]["name"], entries[1]["name"]]))
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=c, seed=3, cast=False,
                                   out_dir=tmp, library=False)
            self.assertTrue(summary["ok"], summary)
            self.assertGreaterEqual(c.retries, 1)
            msgs = [m["content"] for ms in c.sent for m in ms if isinstance(m, dict)]
            self.assertTrue(any("at least 25 different items" in m for m in msgs))
            # the second reply was accepted: the plan holds the full pools
            with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
            self.assertEqual(len(plan["lootPools"]), 3)


class TestTheCheck(unittest.TestCase):
    def setUp(self):
        self.entries = menu_entries()
        self.menu_names = [e["name"] for e in self.entries]

    def test_a_good_reply_passes(self):
        self.assertEqual(phases.check_p2_items_library(
            library_reply(self.entries), self.menu_names), [])

    def test_the_reply_needs_pools(self):
        for bad in (None, {}, {"items": []}, {"lootPools": {}}):
            with self.subTest(bad):
                self.assertTrue(phases.check_p2_items_library(bad, self.menu_names))

    def test_a_new_item_needs_its_fields_and_plot_true(self):
        d = library_reply(self.entries)
        d["items"][0].pop("plot")
        errs = phases.check_p2_items_library(d, self.menu_names)
        self.assertTrue(any(".plot" in e for e in errs), errs)
        d["items"][0]["plot"] = True
        d["items"][0]["value"] = 0
        errs = phases.check_p2_items_library(d, self.menu_names)
        self.assertTrue(any(".value" in e for e in errs), errs)

    def test_off_menu_pool_names_are_not_errors(self):
        d = library_reply(self.entries)
        d["lootPools"]["Barred chest"]["items"] += ["Mystery box", 7]
        self.assertEqual(phases.check_p2_items_library(d, self.menu_names), [])

    def test_fewer_than_25_distinct_items_is_an_error(self):
        errs = phases.check_p2_items_library(tiny_reply(self.entries), self.menu_names)
        self.assertTrue(any("only 3 different items" in e and
                            "at least 25" in e for e in errs), errs)

    def test_errors_are_capped(self):
        d = {"lootPools": {"P": {"items": [self.entries[0]["name"]]}},
             "items": [{"name": f"x{i}", "type": "gadget", "quality": "common",
                        "value": 1, "description": "d",
                        "physicalDescription": "p, white background"}
                       for i in range(phases.MAX_ERRORS + 4)]}
        errs = phases.check_p2_items_library(d, self.menu_names)
        self.assertGreater(len(errs), 1)
        self.assertLessEqual(len(errs), phases.MAX_ERRORS)


class TestTheSwitchReachesGenerate(unittest.TestCase):
    def args(self, **kw):
        base = dict(command="generate", settings=None, idea="a mill village", seed=None,
                    ext=[], library=None, item_library=None)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_the_cli_flag_defaults_on_and_turns_off(self):
        self.assertTrue(wgmain._generate_args(self.args())["item_library"])
        self.assertFalse(wgmain._generate_args(self.args(item_library=False))
                         ["item_library"])

    def test_a_settings_file_carries_it_until_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = settings_mod.write(os.path.join(tmp, "settings.json"),
                                      settings_mod.make(idea="a mill village",
                                                        item_library=False))
            from_file = wgmain._generate_args(self.args(settings=path))
            self.assertFalse(from_file["item_library"])
            self.assertTrue(from_file["library"])   # the two switches are separate
            overridden = wgmain._generate_args(self.args(settings=path, item_library=True))
            self.assertTrue(overridden["item_library"])


if __name__ == "__main__":
    unittest.main()
