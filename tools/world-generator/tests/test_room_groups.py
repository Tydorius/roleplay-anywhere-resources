"""The furniture groups: the shipped files check clean, every layout has one
recipe with one anchor, conversion matches hand-checked expectations, each
check catches its mistake, and converting twice gives the same output."""
import importlib.util
import json
import os
import tempfile
import unittest

from worldgen import library as WL
from worldgen import room_groups as RG

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def converter():
    """library-seed/layouts_to_groups.py loaded as a module."""
    path = os.path.join(GEN, "library-seed", "layouts_to_groups.py")
    spec = importlib.util.spec_from_file_location("layouts_to_groups", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestShipped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()
        cls.data = RG.load()

    def test_shipped_files_check_clean(self):
        self.assertEqual(RG.check(self.data, self.lib), [])

    def test_every_layout_has_one_recipe_with_one_anchor(self):
        for lid in self.lib.layouts:
            with self.subTest(layout=lid):
                recipe = self.data["recipes"].get(lid)
                self.assertIsNotNone(recipe, "no recipe")
                kinds = [e.get("kind") for e in recipe["groups"]]
                self.assertEqual(kinds.count("anchor"), 1)


class TestConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = converter()

    def test_bed_with_symmetric_bedsides(self):
        layout = {"id": "bedroom.hand.a", "family": "bedroom",
                  "sizeBands": ["small"],
                  "slots": [
                      {"id": "bed", "role": "sleep.couple", "size": [2, 2],
                       "anchor": "wall:far", "back": "wall"},
                      {"id": "bedsides", "role": "bedside", "size": [1, 1],
                       "anchor": "beside:bed+symmetric"},
                  ]}
        out = self.mod.convert_layout(layout)
        self.assertEqual(out["notes"], [])
        self.assertEqual(len(out["groups"]), 1)
        g = out["groups"][0]
        self.assertEqual(g.wall, "back")
        self.assertEqual([(p["role"], p["at"], p.get("back")) for p in g.pieces], [
            ("sleep.couple", [1, 0], "north"),
            ("bedside", [0, 0], None),
            ("bedside", [3, 0], None),
        ])
        self.assertEqual(g.use, ["south"])
        files, notes = self.mod.convert_all({"bedroom": [layout]})
        self.assertEqual(notes, [])
        self.assertEqual(files["bedroom"]["groups"][0]["id"],
                         "sleep.couple.bedside2")
        recipe = files["bedroom"]["recipes"][0]
        self.assertEqual(recipe["groups"],
                         [{"group": "sleep.couple.bedside2", "kind": "anchor"}])

    def test_table_with_around_chairs(self):
        layout = {"id": "dining.hand.a", "family": "dining",
                  "sizeBands": ["small"],
                  "slots": [
                      {"id": "table", "role": "table.dining", "size": [2, 1],
                       "anchor": "center"},
                      {"id": "chairs", "role": "seat", "size": [1, 1],
                       "anchor": "around:table", "count": 4},
                  ]}
        out = self.mod.convert_layout(layout)
        self.assertEqual(out["notes"], [])
        g = out["groups"][0]
        self.assertEqual(g.wall, "none")
        self.assertEqual([(p["role"], p["at"]) for p in g.pieces], [
            ("table.dining", [0, 1]),
            ("seat", [0, 0]), ("seat", [1, 0]),
            ("seat", [0, 2]), ("seat", [1, 2]),
        ])
        self.assertEqual(g.use, ["east", "west"])
        files, _ = self.mod.convert_all({"dining": [layout]})
        self.assertEqual(files["dining"]["groups"][0]["id"], "table.dining.seat4")

    def test_grow_joins_as_optional_and_alone_becomes_a_group(self):
        layout = {"id": "office.hand.a", "family": "office",
                  "sizeBands": ["medium"],
                  "slots": [
                      {"id": "desk", "role": "desk", "size": [2, 1],
                       "anchor": "wall:side", "back": "wall"},
                  ],
                  "grow": [
                      {"role": "storage.small", "size": [1, 1],
                       "anchor": "beside:desk", "minWealth": "modest"},
                      {"role": "decor.feature", "size": [1, 1],
                       "anchor": "corner", "minWealth": "wealthy"},
                  ]}
        files, notes = self.mod.convert_all({"office": [layout]})
        self.assertEqual(notes, [])
        desk, decor = files["office"]["groups"]
        self.assertEqual(desk["id"], "desk.storage.small.opt")
        self.assertEqual(desk["pieces"], [
            {"role": "desk", "size": [2, 1], "at": [1, 0], "back": "north"},
            {"role": "storage.small", "size": [1, 1], "at": [0, 0],
             "optional": True, "minWealth": "modest"},
        ])
        self.assertEqual(decor["wall"], "corner")
        self.assertEqual(decor["use"], [])
        self.assertEqual(files["office"]["recipes"][0]["groups"], [
            {"group": "desk.storage.small.opt", "kind": "anchor"},
            {"group": "decor.feature.single", "kind": "optional",
             "minWealth": "wealthy"},
        ])

    def test_converting_twice_gives_equal_output(self):
        layouts = {}
        layouts_dir = os.path.join(GEN, "library", "layouts")
        for name in sorted(os.listdir(layouts_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(layouts_dir, name), encoding="utf-8") as fh:
                for layout in json.load(fh)["layouts"]:
                    layouts.setdefault(layout["family"], []).append(layout)
        one = self.mod.convert_all(layouts)
        two = self.mod.convert_all(layouts)
        self.assertEqual(one, two)


class TestChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WL.load()

    def base(self):
        bands = self.lib.layouts["bedroom.small.a"].get("sizeBands")
        group = {"id": "sleep.couple.bedside2", "family": "bedroom",
                 "wall": "back", "use": ["south"],
                 "pieces": [
                     {"role": "sleep.couple", "size": [2, 2], "at": [1, 0],
                      "back": "north"},
                     {"role": "bedside", "size": [1, 1], "at": [0, 0]},
                     {"role": "bedside", "size": [1, 1], "at": [3, 0]},
                 ], "_file": "bedroom.json"}
        recipe = {"layout": "bedroom.small.a", "family": "bedroom",
                  "sizeBands": bands,
                  "groups": [{"group": "sleep.couple.bedside2", "kind": "anchor"}],
                  "_file": "bedroom.json"}
        return {"groups": {"sleep.couple.bedside2": group},
                "recipes": {"bedroom.small.a": recipe}}

    def errors(self, data):
        # every other layout has no recipe in this small fixture; ignore that
        return [e for e in RG.check(data, self.lib)
                if not e.startswith("layout ")]

    def broken_group(self, mutate):
        data = self.base()
        mutate(data["groups"]["sleep.couple.bedside2"])
        return self.errors(data)

    def broken_recipe(self, mutate):
        data = self.base()
        mutate(data["recipes"]["bedroom.small.a"])
        return self.errors(data)

    def test_base_is_clean_apart_from_missing_recipes(self):
        self.assertEqual(self.errors(self.base()), [])

    def test_unknown_family(self):
        self.assertTrue(self.broken_group(lambda g: g.update(family="attic")))

    def test_unknown_wall(self):
        self.assertTrue(self.broken_group(lambda g: g.update(wall="both")))

    def test_unknown_use_side(self):
        self.assertTrue(self.broken_group(lambda g: g.update(use=["up"])))

    def test_unknown_role(self):
        def mut(g):
            g["pieces"][1]["role"] = "teleport"
        self.assertTrue(self.broken_group(mut))

    def test_bad_piece_size_and_at(self):
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(size=[1, 0])))
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(at=[-1, 0])))

    def test_overlapping_pieces(self):
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(at=[1, 0])))

    def test_floating_piece(self):
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(at=[0, 4])))

    def test_back_piece_off_the_north_edge(self):
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][0].update(at=[1, 1])))

    def test_back_piece_facing_the_wrong_way(self):
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][0].update(back="east")))

    def test_back_piece_in_a_free_standing_group(self):
        self.assertTrue(self.broken_group(lambda g: g.update(wall="none")))

    def test_bad_piece_flags(self):
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(optional="yes")))
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(minWealth="rich")))
        self.assertTrue(self.broken_group(
            lambda g: g["pieces"][1].update(back="west")))

    def test_no_pieces(self):
        self.assertTrue(self.broken_group(lambda g: g.update(pieces=[])))

    def test_recipe_names_no_group(self):
        def mut(r):
            r["groups"][0]["group"] = "ghost"
        self.assertTrue(self.broken_recipe(mut))

    def test_recipe_needs_exactly_one_anchor(self):
        def two(r):
            r["groups"].append(dict(r["groups"][0]))
        self.assertTrue(self.broken_recipe(two))

        def zero(r):
            r["groups"][0]["kind"] = "required"
        self.assertTrue(self.broken_recipe(zero))

    def test_recipe_bad_kind(self):
        self.assertTrue(self.broken_recipe(
            lambda r: r["groups"][0].update(kind="sometimes")))

    def test_recipe_bad_count(self):
        def mut(r):
            r["groups"][0]["count"] = 0
        self.assertTrue(self.broken_recipe(mut))

    def test_recipe_count_singles_needs_a_sleep_piece(self):
        data = self.base()
        data["recipes"]["bedroom.small.a"]["groups"][0]["count"] = "singles"
        self.assertTrue(any("singles" in e for e in self.errors(data)))
        data["groups"]["sleep.couple.bedside2"]["pieces"][0]["role"] = "sleep"
        self.assertFalse(any("singles" in e for e in self.errors(data)))

    def test_recipe_family_and_sizebands_must_match_the_layout(self):
        self.assertTrue(self.broken_recipe(lambda r: r.update(family="cell")))
        self.assertTrue(self.broken_recipe(
            lambda r: r.update(sizeBands=["large"])))

    def test_recipe_for_no_layout(self):
        def mut(r):
            r.update(layout="bedroom.ghost.z")
        self.assertTrue(self.broken_recipe(mut))

    def test_layout_without_recipe_is_an_error(self):
        data = self.base()
        del data["recipes"]["bedroom.small.a"]
        self.assertIn("layout 'bedroom.small.a' has no recipe",
                      RG.check(data, self.lib))

    def test_unreadable_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bedroom.json"), "w", encoding="utf-8") as f:
                f.write('{"groups": [ {"id": "sleep.single",')
            errors = RG.check(RG.load(d), self.lib)
            self.assertTrue(any("cannot be read" in e for e in errors))

    def test_duplicate_id_across_files_is_an_error(self):
        group = self.base()["groups"]["sleep.couple.bedside2"]
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.json", "b.json"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    json.dump({"groups": [dict(group, _file=None)]}, f)
            errors = RG.check(RG.load(d), self.lib)
            self.assertTrue(any("appears in a.json and b.json" in e
                                for e in errors))


if __name__ == "__main__":
    unittest.main()
