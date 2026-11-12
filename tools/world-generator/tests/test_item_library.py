"""The item library: the fixtures check clean, every rule the checker exists
for catches its mistake, looks cover the item's bands exactly once, and the
art scenarios split looks into the right sets with stable template ids."""
import copy
import importlib.util
import json
import os
import tempfile
import unittest

from worldgen import item_library as IL

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "items")


def maker():
    """library-seed/make_item_art_scenarios.py loaded as a module."""
    path = os.path.join(GEN, "library-seed", "make_item_art_scenarios.py")
    spec = importlib.util.spec_from_file_location("make_item_art_scenarios", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = IL.load(FIXTURES)

    def broken(self, iid, mutate):
        it = copy.deepcopy(self.items[iid])
        mutate(it)
        return IL.check({it.get("id"): it})

    def test_fixtures_check_clean(self):
        self.assertEqual(IL.check(self.items), [])

    def test_helpers_pick_the_bands_look_and_text(self):
        wine, phone = self.items["drink.wine_bottle"], self.items["tech.phone"]
        self.assertIs(IL.looks_for_band(wine, "scifi"), wine["looks"][0])   # "*" expands
        self.assertIsNone(IL.looks_for_band(phone, "medieval"))
        self.assertEqual(IL.name_for(phone, "modern"), "smartphone")
        self.assertEqual(IL.description_for(phone, "scifi"),
                         "A slate that holds a person's whole life.")
        self.assertEqual(IL.name_for(wine, "industrial"), "bottle of wine")

    def test_bad_id(self):
        errs = self.broken("drink.wine_bottle", lambda it: it.update(id="Wine Bottle"))
        self.assertTrue(any("id must be" in e and e.startswith("Wine Bottle")
                            for e in errs), errs)

    def test_id_must_start_with_its_category(self):
        errs = self.broken("drink.wine_bottle", lambda it: it.update(id="food.wine_bottle"))
        self.assertTrue(any("must start with its category" in e for e in errs), errs)

    def test_enums(self):
        for field, bad in (("category", "soup"), ("type", "gadget"), ("quality", "fine")):
            errs = self.broken("drink.wine_bottle", lambda it, f=field, v=bad: it.update({f: v}))
            self.assertTrue(any(f"unknown {field}" in e for e in errs), (field, errs))

    def test_price(self):
        for bad in (0, 7, "2", 2.5, None):
            errs = self.broken("drink.wine_bottle", lambda it, v=bad: it.update(price=v))
            self.assertTrue(any("price must be 1-6" in e for e in errs), (bad, errs))

    def test_bands(self):
        for bad in (["cyber"], ["*", "medieval"], ["modern", "modern"], []):
            errs = self.broken("tech.phone", lambda it, v=bad: it.update(bands=v))
            self.assertTrue(any("bands must be" in e for e in errs), (bad, errs))

    def test_names_and_description_need_every_band(self):
        def drop(it):
            del it["names"]["scifi"]
        errs = self.broken("tech.phone", drop)
        self.assertTrue(any('names needs "*" or an entry for every band' in e for e in errs),
                        errs)
        errs = self.broken("tech.phone", lambda it: it["names"].update(colonial="brick"))
        self.assertTrue(any("names has unknown band 'colonial'" in e for e in errs), errs)
        errs = self.broken("tech.phone", lambda it: it.__setitem__("description", {}))
        self.assertTrue(any("description must be" in e for e in errs), errs)

    def test_look_gap_and_overlap(self):
        def gap(it):
            it["looks"] = [l for l in it["looks"] if l["key"] != "flat"]
        errs = self.broken("tech.phone", gap)
        self.assertTrue(any("no look covers band modern" in e for e in errs), errs)

        def overlap(it):
            it["looks"][0]["bands"] = ["*"]
        errs = self.broken("tech.phone", overlap)
        self.assertTrue(any("looks flat and holo all cover band scifi" in e for e in errs),
                        errs)

    def test_look_outside_the_items_bands(self):
        errs = self.broken("tech.phone", lambda it: it["looks"][0].update(bands=["medieval"]))
        self.assertTrue(any("look flat covers band medieval which the item doesn't have"
                            in e for e in errs), errs)

    def test_duplicate_look_keys(self):
        def twice(it):
            it["looks"][1]["key"] = it["looks"][0]["key"]
        errs = self.broken("tech.phone", twice)
        self.assertTrue(any("look key 'flat' repeats" in e for e in errs), errs)

    def test_physical_rules(self):
        def set_physical(text):
            return lambda it: it["looks"][0].update(physical=text)
        wine = "drink.wine_bottle"
        for text, why in (("", "needs a physical sentence"),
                          ("x" * 300, "characters"),
                          ("An icon of a bottle", "icon"),
                          ("A bottle on a white background", "background")):
            errs = self.broken(wine, set_physical(text))
            self.assertTrue(any(why in e for e in errs), (why, errs))

    def test_sources(self):
        for bad in (["ebay"], []):
            errs = self.broken("drink.wine_bottle", lambda it, v=bad: it.update(sources=v))
            self.assertTrue(any("sources must list" in e for e in errs), (bad, errs))

    def test_duplicate_id_across_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"items": [self.items["drink.wine_bottle"]]}
            for name in ("food_drink.json", "tools.json"):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                    json.dump(data, f)
            errs = IL.check(IL.load(tmp))
            self.assertTrue(any("id appears in food_drink.json and tools.json" in e
                                for e in errs), errs)

    def test_missing_dir_loads_empty(self):
        self.assertEqual(IL.load(os.path.join(FIXTURES, "nope")), {})


class TestCoverage(unittest.TestCase):
    def test_counts(self):
        c = IL.coverage(IL.load(FIXTURES))
        self.assertEqual(c["items"], 3)
        self.assertEqual(c["looks"], 4)
        self.assertEqual(c["shared_looks"], 2)          # wine and bread, bands "*"
        self.assertEqual(c["bands"]["medieval"],
                         {"items": 2, "looks": 2, "categories": {"drink": 1, "food": 1}})
        self.assertEqual(c["bands"]["modern"],
                         {"items": 3, "looks": 3,
                          "categories": {"drink": 1, "food": 1, "tech": 1}})
        self.assertEqual(c["bands"]["scifi"]["looks"], 3)


class TestArtScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = maker()
        cls.items = IL.load(FIXTURES)

    def ids(self, tmp, name):
        root = os.path.join(tmp, name, f"Library-Items-{name.title()}.scenario")
        with open(os.path.join(root, "scenario.json"), encoding="utf-8") as f:
            scn = json.load(f)
        with open(os.path.join(tmp, name, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)["looks"]
        return sorted(t["id"] for t in scn["itemTemplates"]), man, scn

    def test_sets_hold_the_right_looks_with_stable_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            n, code, _ = self.mod.build_set(self.items, "shared", tmp)
            self.assertEqual((n, code), (2, 0))
            first, man, scn = self.ids(tmp, "shared")
            self.assertEqual(set(man), set(first))      # the ids the scenario carries
            wine = self.mod.template_id("drink.wine_bottle", "glass")
            self.assertEqual(man[wine], {"item": "drink.wine_bottle", "look": "glass",
                                         "bands": list(IL.BANDS),
                                         "physical": self.items["drink.wine_bottle"]
                                         ["looks"][0]["physical"]})
            name = next(t["name"] for t in scn["itemTemplates"] if t["id"] == wine)
            self.assertEqual(name, "Bottle of wine [drink.wine_bottle#glass]")

            for band, count in (("medieval", 0), ("industrial", 0), ("modern", 1),
                                ("scifi", 1)):
                n, code, _ = self.mod.build_set(self.items, band, tmp)
                self.assertEqual((n, code), (count, 0), band)

            _, man_mod, _ = self.ids(tmp, "modern")
            flat = self.mod.template_id("tech.phone", "flat")
            self.assertEqual(man_mod[flat]["item"], "tech.phone")
            self.assertEqual(man_mod[flat]["bands"], ["modern"])

            with tempfile.TemporaryDirectory() as tmp2:
                self.mod.build_set(self.items, "shared", tmp2)
                again, _, _ = self.ids(tmp2, "shared")
                self.assertEqual(again, first)


class TestRealItems(unittest.TestCase):
    def test_shipped_items_check_clean(self):
        items = IL.load()
        if not items:
            self.skipTest("library/items/ is empty or missing")
        self.assertEqual(IL.check(items), [])


if __name__ == "__main__":
    unittest.main()
