"""The item library as P2's item menu: entries filtered by band and genre,
the reply expanded into item templates and loot pools, sprite recolouring,
and the shipped item art attached to a built scenario. The library and two
of its real sprites are used; the model's reply is canned, so no model
calls happen."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from worldgen import item_library as IL
from worldgen import library_art
from worldgen import library_items as LIT

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEM_SPRITES = os.path.join(GEN, "library", "item-sprites")


def real_items():
    items = IL.load()
    if not items:
        raise unittest.SkipTest("library/items/ is empty or missing")
    return items


def capitalised(name):
    return name[:1].upper() + name[1:]


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class TestMenu(unittest.TestCase):
    BAND = "medieval"
    GENRE = "dark fantasy"

    def entries(self, band=BAND, genre=GENRE):
        return LIT.menu(real_items(), band, genre)

    def test_filters_by_band(self):
        es = self.entries()
        self.assertTrue(es)
        taken = {e["name"].casefold() for e in es}
        modern_only = [it for it in real_items().values()
                       if IL.expand_bands(it.get("bands")) == ["modern"]
                       and not it.get("onlyGenres")
                       and IL.name_for(it, "modern").casefold() not in taken]
        if not modern_only:
            self.skipTest("no modern-only item apart from the medieval menu")
        gone = IL.name_for(modern_only[0], "modern")
        self.assertNotIn(gone.casefold(), taken)
        modern = LIT.menu(real_items(), "modern", "cyberpunk")
        self.assertIn(capitalised(gone), [e["name"] for e in modern])

    def test_filters_by_only_genres(self):
        fantasy_only = [it for it in real_items().values() if it.get("onlyGenres")]
        if not fantasy_only:
            self.skipTest("no genre-limited item in the library")
        it = fantasy_only[0]
        band = IL.expand_bands(it.get("bands"))[0]
        name = capitalised(IL.name_for(it, band))
        for genre, there in (("dark fantasy", True), ("cyberpunk", False),
                             ("a fantasy of bells", True), ("fantasyland", False)):
            with self.subTest(genre):
                es = self.entries(band, genre)
                self.assertEqual(name in [e["name"] for e in es], there)

    def test_entry_shape_and_capitalised_name(self):
        for e in self.entries():
            self.assertEqual(set(e), {"name", "item", "look", "tintable"})
            self.assertEqual(e["name"], capitalised(e["name"]))
            self.assertIn(self.BAND, IL.look_bands(e["item"], e["look"]))
            self.assertIsInstance(e["tintable"], bool)

    def test_two_items_one_band_name_keeps_the_first_by_id(self):
        def item(iid, physical):
            return {"id": iid, "category": "food", "type": "consumable",
                    "bands": ["medieval"], "quality": "common", "price": 1,
                    "names": {"*": "loaf of bread"}, "description": {"*": "d"},
                    "looks": [{"key": "k", "bands": ["*"], "physical": physical}],
                    "sources": ["authored"]}
        a = item("food.a", "The first one")
        b = item("food.b", "The second one")
        es = LIT.menu({"food.b": b, "food.a": a}, "medieval", "")
        self.assertEqual([e["name"] for e in es], ["Loaf of bread"])
        self.assertEqual(es[0]["item"]["id"], "food.a")

    def test_menu_lines_mark_recolourable(self):
        es = self.entries()
        lines = LIT.menu_lines(es)
        self.assertEqual(len(lines), len(es))
        tintable = [e for e in es if e["tintable"]]
        if not tintable:
            self.skipTest("no tintable entry for this band")
        e = tintable[0]
        self.assertIn(f"- {e['name']} | {e['item']['category']} | "
                      f"price {e['item']['price']} | recolourable", lines)
        plain = next(e2 for e2 in es if not e2["tintable"])
        line = next(l for l in lines if l.startswith(f"- {plain['name']} |"))
        self.assertEqual(line, f"- {plain['name']} | {plain['item']['category']} | "
                               f"price {plain['item']['price']}")


class TestValue(unittest.TestCase):
    def test_within_jitter_of_the_table_and_stable(self):
        for price, base in LIT.VALUE.items():
            v = LIT.value_for(price, "seed|Thing")
            self.assertGreaterEqual(v, max(1, round(base * 0.85)), price)
            self.assertLessEqual(v, round(base * 1.15), price)
            self.assertEqual(v, LIT.value_for(price, "seed|Thing"))
        self.assertGreaterEqual(LIT.value_for(1, "tiny"), 1)


class TestExpand(unittest.TestCase):
    BAND = "medieval"
    GENRE = "dark fantasy"

    @classmethod
    def setUpClass(cls):
        cls.entries = LIT.menu(real_items(), cls.BAND, cls.GENRE)

    def reply(self, first, tint_entry):
        return {
            "lootPools": {
                "Kitchen cupboard": {
                    "items": [first["name"].lower(), "Red ledger", "Blue book",
                              "Seal of the Drowned Choir", "Mystery box"],
                    "weights": {first["name"].lower(): 3, "Mystery box": 9}},
                "Barred chest": {"items": ["Mystery box"], "weights": {}},
            },
            "variants": [
                {"from": tint_entry["name"], "name": "Red ledger", "tint": "red",
                 "description": "The steward's household accounts."},
                {"from": "Not on the menu", "name": "Ghost", "tint": "red",
                 "description": "x"},
                {"from": tint_entry["name"], "name": "Bad tint", "tint": "crimson",
                 "description": "x"},
                {"from": tint_entry["name"], "name": first["name"],
                 "tint": "blue", "description": "collides with a menu name"},
                {"from": tint_entry["name"], "name": "Blue book", "tint": "blue"},
            ],
            "items": [
                {"name": "Seal of the Drowned Choir", "type": "misc",
                 "quality": "rare", "value": 400,
                 "description": "A wax seal the choir swore on.",
                 "physicalDescription": "A wax seal on a cord, white background"},
                {"name": "Broken item", "type": "gadget", "quality": "rare",
                 "value": 4, "description": "x",
                 "physicalDescription": "x, white background"},
                {"name": "Unpooled heirloom", "type": "misc", "quality": "uncommon",
                 "value": 50, "description": "A locket nobody remembers.",
                 "physicalDescription": "A locket, white background"},
            ],
        }

    def run_expand(self, seed=7):
        first = self.entries[0]
        tint_entry = next((e for e in self.entries if e["tintable"]), None)
        if tint_entry is None:
            self.skipTest("no tintable entry for this band")
        log = []
        out = LIT.expand(self.reply(first, tint_entry), self.entries,
                         self.BAND, seed, log)
        return first, tint_entry, log, out

    def by_name(self, items, name):
        return next(t for t in items if t["name"] == name)

    def test_menu_pick_becomes_a_full_template(self):
        first, _t, _l, (items, _p) = self.run_expand()
        t = self.by_name(items, first["name"])
        it, look = first["item"], first["look"]
        self.assertEqual(t["type"], it["type"])
        self.assertEqual(t["quality"], it["quality"])
        self.assertEqual(t["description"], IL.description_for(it, self.BAND))
        self.assertEqual(t["physicalDescription"],
                         look["physical"] + ", white background")
        self.assertEqual(t["library"], {"item": it["id"], "look": look["key"],
                                        "tint": None})
        lo = max(1, round(LIT.VALUE[it["price"]] * 0.85))
        hi = round(LIT.VALUE[it["price"]] * 1.15)
        self.assertGreaterEqual(t["value"], lo)
        self.assertLessEqual(t["value"], hi)

    def test_variant_gets_its_own_name_description_and_tint(self):
        _f, tint_entry, _l, (items, _p) = self.run_expand()
        it, look = tint_entry["item"], tint_entry["look"]
        t = self.by_name(items, "Red ledger")
        self.assertEqual(t["description"], "The steward's household accounts.")
        self.assertEqual(t["physicalDescription"],
                         f"red-coloured {look['physical']}, white background")
        self.assertEqual(t["type"], it["type"])
        self.assertEqual(t["library"], {"item": it["id"], "look": look["key"],
                                        "tint": "red"})
        # a variant with no description of its own falls back to its base's
        self.assertEqual(self.by_name(items, "Blue book")["description"],
                         IL.description_for(it, self.BAND))

    def test_unknown_pool_entry_and_bad_variants_are_logged_and_dropped(self):
        first, _t, log, (items, _p) = self.run_expand()
        self.assertIn(("items", "Kitchen cupboard: Mystery box is not on the menu"),
                      log)
        whys = [w for _w, w in log]
        self.assertTrue(any("variant 'Ghost' dropped" in w
                            and "is not on the menu" in w for w in whys), log)
        self.assertTrue(any("variant 'Bad tint' dropped" in w
                            and "tint 'crimson'" in w for w in whys), log)
        self.assertTrue(any("dropped: the name is already used" in w
                            and first["name"] in w for w in whys), log)
        self.assertTrue(any("Broken item" in w and "dropped" in w
                            for w in whys), log)
        names = [t["name"] for t in items]
        for gone in ("Ghost", "Bad tint", "Broken item"):
            self.assertNotIn(gone, names)

    def test_empty_pool_is_dropped(self):
        _f, _t, log, (_items, pools) = self.run_expand()
        self.assertNotIn("Barred chest", pools)
        self.assertEqual(sorted(pools), ["Kitchen cupboard"])
        self.assertTrue(any("Barred chest" in w for _w, w in log))

    def test_pools_keep_resolved_names_and_weights(self):
        first, _t, _l, (_items, pools) = self.run_expand()
        p = pools["Kitchen cupboard"]
        self.assertEqual(p["items"], [first["name"], "Red ledger", "Blue book",
                                      "Seal of the Drowned Choir"])
        self.assertEqual(p["weights"], {first["name"]: 3})

    def test_plot_items_are_kept_even_when_no_pool_names_them(self):
        _f, _t, _l, (items, _p) = self.run_expand()
        seal = self.by_name(items, "Seal of the Drowned Choir")
        self.assertTrue(seal["plot"])
        self.assertNotIn("library", seal)
        self.assertEqual(seal["value"], 400)
        heirloom = self.by_name(items, "Unpooled heirloom")
        self.assertTrue(heirloom["plot"])
        self.assertNotIn("library", heirloom)

    def test_only_pooled_and_plot_items_are_returned(self):
        _f, _t, _l, (items, pools) = self.run_expand()
        pooled = {n for p in pools.values() for n in p["items"]}
        for t in items:
            self.assertTrue(t["name"] in pooled or t.get("plot"), t["name"])
        self.assertNotIn("Ghost", pooled)

    def test_items_sorted_by_name(self):
        _f, _t, _l, (items, _p) = self.run_expand()
        self.assertEqual([t["name"] for t in items],
                         sorted(t["name"] for t in items))

    def test_values_stable_for_the_same_seed(self):
        _f, _t, _l, (items1, _p1) = self.run_expand(seed=7)
        _f, _t, _l, (items2, _p2) = self.run_expand(seed=7)
        self.assertEqual({t["name"]: t.get("value") for t in items1},
                         {t["name"]: t.get("value") for t in items2})


class TestRecolour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PIL import Image      # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Pillow is not installed")

    def sprite(self, d):
        """A sprite whose left half is red, right half grey, with a
        transparent strip: the coloured, the neutral and the empty pixels."""
        from PIL import Image
        img = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
        for x in range(40):
            for y in range(20):
                if y < 2:
                    continue
                img.putpixel((x, y), (200, 30, 30, 255) if x < 20
                             else (128, 128, 128, 255))
        path = os.path.join(d, "src.webp")
        img.save(path, "WEBP", quality=95)
        return path

    def test_red_sprite_turned_blue_keeps_greys_and_alpha(self):
        with tempfile.TemporaryDirectory() as d:
            from PIL import Image
            src = self.sprite(d)
            dst = os.path.join(d, "out.webp")
            self.assertTrue(library_art.recolour(src, dst, "blue"))
            img = Image.open(dst).convert("RGBA")
            hsv = img.convert("RGB").convert("HSV")
            hues = [h * 360.0 / 255.0
                    for (r, g, b, a), (h, s, v)
                    in zip(img.getdata(), hsv.getdata())
                    if a > 0 and s > 64]
            self.assertGreater(len(hues), 300)
            mean = sum(hues) / len(hues)
            self.assertGreater(mean, 220.0, mean)
            self.assertLess(mean, 260.0, mean)
            grey = img.getpixel((30, 10))
            self.assertTrue(all(abs(c - 128) <= 3 for c in grey[:3]), grey)
            self.assertEqual(img.getpixel((10, 0))[3], 0)

    def test_without_pillow_the_file_is_copied_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.sprite(d)
            dst = os.path.join(d, "out.webp")
            with mock.patch.dict(sys.modules, {"PIL": None}):
                self.assertFalse(library_art.recolour(src, dst, "blue"))
            self.assertEqual(read_bytes(src), read_bytes(dst))

    def test_unknown_tint_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.sprite(d)
            with self.assertRaises(ValueError):
                library_art.recolour(src, os.path.join(d, "x.webp"), "crimson")


class TestAttachItemArt(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ITEM_SPRITES, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        self.keys = [k for k in sorted(idx)
                     if os.path.exists(os.path.join(ITEM_SPRITES, k + ".webp"))]
        if len(self.keys) < 2:
            self.skipTest("fewer than two item sprites shipped")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        sprites = os.path.join(self.root, "library", "item-sprites")
        os.makedirs(sprites)
        for k in self.keys[:2]:
            shutil.copyfile(os.path.join(ITEM_SPRITES, k + ".webp"),
                            os.path.join(sprites, k + ".webp"))
        k1, k2 = self.keys[0].rsplit(".", 1), self.keys[1].rsplit(".", 1)
        self.scn = os.path.join(self.tmp, "World.scenario")
        os.makedirs(self.scn)
        with open(os.path.join(self.scn, "scenario.json"), "w", encoding="utf-8") as f:
            json.dump({"itemTemplates": [
                {"id": "itpl1", "name": "Bottle of wine"},
                {"id": "itpl2", "name": "Red ledger"},
                {"id": "itpl3", "name": "Plain thing"},
                {"id": "itpl4", "name": "Missing art"}]}, f)
        self.plan_data = {"items": [
            {"name": "Bottle of wine",
             "library": {"item": k1[0], "look": k1[1], "tint": None}},
            {"name": "Red ledger",
             "library": {"item": k2[0], "look": k2[1], "tint": "blue"}},
            {"name": "Plain thing"},
            {"name": "Missing art",
             "library": {"item": "no.such", "look": "gone", "tint": None}}]}

    def test_copies_recolours_and_skips(self):
        n, tinted = library_art.attach_item_art(self.scn, self.plan_data,
                                                root=self.root)
        self.assertEqual((n, tinted), (2, 1))
        one = os.path.join(self.scn, "media", "itpl1", "itpl1-item.webp")
        two = os.path.join(self.scn, "media", "itpl2", "itpl2-item.webp")
        self.assertTrue(os.path.exists(one))
        self.assertTrue(os.path.exists(two))
        src1 = os.path.join(self.root, "library", "item-sprites",
                            self.keys[0] + ".webp")
        self.assertEqual(read_bytes(one), read_bytes(src1))
        src2 = os.path.join(self.root, "library", "item-sprites",
                            self.keys[1] + ".webp")
        self.assertNotEqual(read_bytes(two), read_bytes(src2))
        for itpl in ("itpl3", "itpl4"):
            self.assertFalse(os.path.exists(os.path.join(self.scn, "media", itpl)))
        with zipfile.ZipFile(self.scn + ".zip") as z:
            names = set(z.namelist())
        self.assertIn("media/itpl1/itpl1-item.webp", names)
        self.assertIn("media/itpl2/itpl2-item.webp", names)
        self.assertNotIn("media/itpl3/itpl3-item.webp", names)

    def test_library_never_appears_in_the_built_item_templates(self):
        library_art.attach_item_art(self.scn, self.plan_data, root=self.root)
        with open(os.path.join(self.scn, "scenario.json"), encoding="utf-8") as f:
            scn = json.load(f)
        for t in scn["itemTemplates"]:
            self.assertNotIn("library", t)

    def test_the_plan_model_drops_the_library_link(self):
        from worldgen.model import parse_plan
        plan = {"zones": [], "templates": [], "items": [
            {"name": "Book", "type": "misc", "quality": "common", "value": 8,
             "description": "A book.",
             "physicalDescription": "A book, white background",
             "library": {"item": "document.book", "look": "leather", "tint": None},
             "plot": False}],
            "lootPools": {"shelf": {"items": ["Book"]}}}
        parsed = parse_plan(plan)
        self.assertEqual([it.name for it in parsed.items], ["Book"])
        self.assertNotIn("library", vars(parsed.items[0]))
        self.assertNotIn("plot", vars(parsed.items[0]))


if __name__ == "__main__":
    unittest.main()
