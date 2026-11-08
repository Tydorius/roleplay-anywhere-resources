"""The room library: the shipped files pass the checker, every object's text
fills cleanly in every setting it allows, the core rooms can be furnished in
every band, and the checker catches the mistakes it exists for."""
import copy
import random
import unittest

from worldgen import library as L

CORE = ("bedroom", "master_bedroom", "dormitory", "kitchen", "dining", "common_room",
        "shop", "storage", "office", "washroom", "workshop")


def shipped():
    return L.load(L.LIB_DIR)


class TestShippedLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = shipped()
        cls.errors, cls.warnings = L.check(cls.lib)

    def test_no_errors(self):
        self.assertEqual(self.errors, [], "\n".join(self.errors[:40]))

    def test_it_has_content(self):
        self.assertGreaterEqual(len(self.lib.objects), 150)
        self.assertGreaterEqual(len(self.lib.layouts), 60)
        self.assertGreaterEqual(len(self.lib.suites), 40)

    def test_every_family_has_layouts(self):
        for fam in self.lib.vocab["families"]:
            self.assertTrue(self.lib.layouts_for(fam), fam)

    def test_every_object_fills_in_every_setting(self):
        lib = self.lib
        for o in lib.objects.values():
            bands = lib.bands if o["bands"] == ["*"] else o["bands"]
            for band in bands:
                for tier in o["wealth"]:
                    for cond in lib.vocab["conditions"]:
                        t = L.fill_text(lib, o, band, tier, cond, random.Random(7))
                        for key in ("description", "physical"):
                            with self.subTest(o=o["id"], band=band, tier=tier, cond=cond, key=key):
                                self.assertTrue(t[key])
                                self.assertNotIn("{", t[key])
                                self.assertNotIn("}", t[key])
                                self.assertNotIn("  ", t[key])

    def test_every_tier_has_a_double_bed_in_every_band(self):
        lib = self.lib
        for band in lib.bands:
            for tier in lib.tiers:
                with self.subTest(band=band, tier=tier):
                    self.assertTrue(L.candidates(lib, "master_bedroom", "sleep.couple", [2, 2],
                                                 band, tier))

    def test_core_rooms_have_no_hard_gaps(self):
        hard = [g for g in L.coverage(self.lib) if not g[7] and g[0] in CORE]
        self.assertEqual(hard, [], "\n".join(map(str, hard[:30])))


def tiny():
    """A one-object library to break on purpose."""
    lib = L.Library("memory")
    lib.vocab = copy.deepcopy(shipped().vocab)
    lib.objects = {"bed.single": {
        "id": "bed.single", "category": "bed", "size": [1, 2], "walkability": 0.3,
        "forSleep": True, "light": 0, "back": "north", "wealth": ["modest"], "bands": ["*"],
        "names": {"*": "bed"}, "parts": {"frame": "wood"}, "container": False,
        "lootPool": None, "sources": ["claude-authored"],
        "text": {"description": "{A:condition} {frame} {noun}.",
                 "physical": "A {frame.color} {frame} {noun}, seen from above."}}}
    lib.materials = {"wood": {b: {"modest": [{"name": "oak", "colors": ["golden"]}]}
                              for b in lib.vocab["bands"]}}
    lib.conditions = {"*": {"ruined": "wrecked", "worn": "worn", "kept": "", "pristine": "spotless"}}
    return lib


def layout(**over):
    l = {"id": "bedroom.small.a", "family": "bedroom", "sizeBands": ["small"],
         "minInterior": [4, 4], "maxInterior": [5, 5],
         "slots": [{"id": "bed", "role": "sleep", "size": [1, 2], "anchor": "wall:far",
                    "count": "singles", "back": "wall"}]}
    l.update(over)
    return l


class TestChecker(unittest.TestCase):
    def errs(self, lib):
        return L.check(lib, sources_path=None)[0]

    def test_text_fill_and_articles(self):
        lib = tiny()
        o = lib.objects["bed.single"]
        t = L.fill_text(lib, o, "medieval", "modest", "kept", random.Random(1))
        self.assertEqual(t["description"], "An oak bed.")
        t = L.fill_text(lib, o, "medieval", "modest", "worn", random.Random(1))
        self.assertEqual(t["description"], "A worn oak bed.")
        self.assertEqual(t["physical"], "A golden oak bed, seen from above.")

    def test_fixed_articles_agree_and_repeats_collapse(self):
        lib = tiny()
        o = lib.objects["bed.single"]
        lib.materials["wood"]["medieval"]["modest"] = [{"name": "oak", "colors": ["amber"]}]
        o["text"]["physical"] = "Top-down view of a {frame.color} {frame} {noun}."
        t = L.fill_text(lib, o, "medieval", "modest", "kept", random.Random(1))
        self.assertEqual(t["physical"], "Top-down view of an amber oak bed.")
        # a colour the material already names is dropped, and the article follows
        lib.materials["wood"]["medieval"]["modest"] = [{"name": "engraved oak", "colors": ["oak"]}]
        t = L.fill_text(lib, o, "medieval", "modest", "kept", random.Random(1))
        self.assertEqual(t["physical"], "Top-down view of an engraved oak bed.")
        o["names"]["*"] = "oak bed"
        lib.materials["wood"]["medieval"]["modest"] = [{"name": "oak", "colors": ["pale"]}]
        o["text"]["description"] = "{A:condition} {frame} {noun}."
        t = L.fill_text(lib, o, "medieval", "modest", "kept", random.Random(1))
        self.assertEqual(t["description"], "An oak bed.")

    def test_a_token_with_no_part_is_an_error(self):
        lib = tiny()
        lib.objects["bed.single"]["text"]["description"] = "{cover} {noun}"
        self.assertTrue(any("token {cover}" in e for e in self.errs(lib)))

    def test_a_sleep_object_must_be_lain_on(self):
        lib = tiny()
        lib.objects["bed.single"]["walkability"] = 0
        self.assertTrue(any("walkability 0.3" in e for e in self.errs(lib)))

    def test_crowded_layout_and_bad_anchor(self):
        lib = tiny()
        lib.layouts = {"x": layout(slots=[
            {"id": "bed", "role": "sleep", "size": [1, 2], "anchor": "wall:far", "count": "singles"},
            {"id": "big", "role": "storage.big", "size": [3, 3], "anchor": "wall:upward"},
            {"id": "lamp", "role": "light.small", "size": [1, 1], "anchor": "beside:nothing"}])}
        lib.layouts["x"]["id"] = "x.small.a"
        e = self.errs(lib)
        self.assertTrue(any("required slots cover" in x for x in e), e)
        self.assertTrue(any("unknown anchor 'wall:upward'" in x for x in e), e)
        self.assertTrue(any("beside:nothing names no slot" in x for x in e), e)

    def test_a_kitchen_never_sleeps(self):
        lib = tiny()
        lib.layouts = {"k": layout(id="kitchen.small.a", family="kitchen")}
        self.assertTrue(any("no sleep slots in a kitchen" in x for x in self.errs(lib)))

    def test_unbound_role_is_an_error(self):
        lib = tiny()
        lib.layouts = {"b": layout()}
        lib.purposes = {"*": {"roles": {}}, "bedroom": {"roles": {}}}
        self.assertTrue(any("role sleep (layout bedroom.small.a) is not bound" in x
                            for x in self.errs(lib)))

    def test_suite_rooms_must_be_reachable_and_bed_the_residents(self):
        lib = tiny()
        lib.suites = {"cottage.a": {
            "id": "cottage.a", "kinds": ["cottage"], "bands": ["medieval"],
            "sizeClasses": ["small"], "residents": [2, 4],
            "rooms": [{"name": "Main", "purpose": "kitchen", "share": "large"},
                      {"name": "Shed", "purpose": "storage", "share": "small"}],
            "connections": [], "entrance": {"room": "Main"}}}
        e = self.errs(lib)
        self.assertTrue(any("Shed can't be reached" in x for x in e), e)
        self.assertTrue(any("no room to sleep in" in x for x in e), e)


if __name__ == "__main__":
    unittest.main()
