"""Brief rl-25: basements and cellars — the machinery, proven on the medieval
inn. A suite inn keeps its cellar below the ground as a level -1 pocket plane
sealed under the building's footprint, one two-way stair portal joins the
kitchen to it, its containers stock from the cellar loot pool, --no-basements
(and a settings file that says false) folds the room back onto the ground
floor, a world with no cellar rooms anywhere builds byte-identical with the
switch on, and floors off leaves no cellar, no crash and a summary line."""
import argparse
import json
import os
import random
import shutil
import tempfile
import unittest

from worldgen import api, library_plan, settings
from worldgen.library import load as library_load
from worldgen.vendor import scenario_checks

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
INN = "The Green Dragon Inn"
CELLAR = f"{INN} (cellar)"
POOL_ITEMS = ["Bread", "Cask of ale", "Wax candle", "Sack of flour",
              "Bottle of wine", "Wheel of cheese"]


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def plan_items(names):
    """Plan item entries for the pools, the shape P2 writes (checked names,
    types, qualities and a white-background physical description)."""
    return [{"name": n, "type": "misc", "quality": "common", "value": 2,
             "description": f"{n}.", "physicalDescription": f"{n}, white background"}
            for n in names]


def inn_with_cellar():
    """The village fixture with its inn laid out from the coaching-inn
    suite, cellar below the kitchen, and a cellar loot pool in the plan."""
    data = load("village.json")
    data["setting"]["band"] = "medieval"
    lib = library_load()
    for i, b in enumerate(data["buildings"]):
        if str(b.get("name", "")) == INN:
            design = library_plan.design_from_suite(
                lib.suites["inn.coaching"], b, "medieval", random.Random(1))
            library_plan.trim_rooms(lib, design, b)
            design["name"] = b["name"]
            design["kind"] = b.get("kind", "inn")
            data["buildings"][i] = design
            break
    data["items"] = plan_items(POOL_ITEMS)
    data["lootPools"] = {"Cellar": {"items": POOL_ITEMS}}
    return data


def _inside(entity, region):
    x, y = entity["pos"]
    rx, ry = region["position"]
    rw, rh = region["size"]
    return rx <= x < rx + rw and ry <= y < ry + rh


class TestInnCellar(unittest.TestCase):
    """The default path: nothing stamped, nothing switched — the inn's suite
    cellar simply builds below the ground."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-basements-")
        cls.lines = []
        cls.summary = api._layout_and_build(inn_with_cellar(), seed=1,
                                            out_dir=cls.tmp,
                                            extra_exts=("floors",),
                                            emit=cls.lines.append)
        path = os.path.join(cls.summary["out"], cls.summary["zip"][:-len(".zip")],
                            "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)
        cls.path = path
        with open(os.path.join(cls.summary["out"], "metrics.json"),
                  "r", encoding="utf-8") as f:
            cls.metrics = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _region(self, name):
        return next(r for r in self.scn["regions"] if r["name"] == name)

    def _objects(self):
        return [e for e in self.scn["entities"] if e.get("type") == "object"]

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)
        self.assertEqual(self.metrics["floors"]["issues"], [])

    def test_the_cellar_is_a_pocket_below_the_inn(self):
        cellar = self._region(CELLAR)
        inn = self._region(INN)
        self.assertEqual(cellar["pocket"],
                         {"anchor": inn["id"], "level": -1})
        self.assertTrue(cellar["wall"], "the cellar plane must be walled")
        self.assertEqual(cellar["openings"], [], "the cellar plane must be sealed")
        cw, ch = cellar["size"]
        iw, ih = inn["size"]
        self.assertLessEqual(cw, iw, "the cellar is wider than the inn")
        self.assertLessEqual(ch, ih, "the cellar is deeper than the inn")

    def test_the_stairs_join_the_kitchen_to_the_cellar_both_ways(self):
        ents = {e["id"]: e for e in self._objects()}
        kitchen = next(r for r in self.scn["regions"]
                       if r["name"].startswith(INN) and r["name"].endswith("Kitchen"))
        cellar = self._region(CELLAR)
        down = next(e for e in ents.values() if e["name"] == f"{INN} stairs down 1")
        up = next(e for e in ents.values() if e["name"] == f"{INN} stairs up 1")
        self.assertTrue(_inside(down, kitchen),
                        f"the down stair sits outside {kitchen['name']}")
        self.assertTrue(_inside(up, cellar), "the up stair sits outside the cellar")
        self.assertEqual(down["portal"], {"to": up["id"]})
        self.assertEqual(up["portal"], {"to": down["id"]})

    def test_the_cellar_containers_stock_from_its_pool(self):
        cellar = self._region(CELLAR)
        stocked = [e for e in self._objects()
                   if _inside(e, cellar) and e.get("inventory")]
        self.assertTrue(stocked, "no cellar container drew from the pool")
        templates = {t["id"]: t["name"] for t in self.scn["itemTemplates"]}
        allowed = set(POOL_ITEMS)
        names = {templates[i["templateId"]] for e in stocked for i in e["inventory"]}
        self.assertTrue(names <= allowed, names - allowed)

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)


class TestSwitchOff(unittest.TestCase):
    """--no-basements folds the inn's cellar back onto the ground floor."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-basements-off-")
        data = inn_with_cellar()
        data["basements"] = False
        cls.summary = api._layout_and_build(data, seed=1, out_dir=cls.tmp,
                                            extra_exts=("floors",))
        path = os.path.join(cls.summary["out"], cls.summary["zip"][:-len(".zip")],
                            "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_cellar_plane_and_the_room_back_on_the_ground(self):
        self.assertFalse([r for r in self.scn["regions"] if r.get("pocket")])
        inn = next(r for r in self.scn["regions"] if r["name"] == INN)
        ground = next(r for r in self.scn["regions"]
                      if r["name"] == f"{INN} Cellar")
        gx, gy = ground["position"]
        gw, gh = ground["size"]
        ix, iy = inn["position"]
        iw, ih = inn["size"]
        self.assertTrue(ix <= gx and gx + gw <= ix + iw
                        and iy <= gy and gy + gh <= iy + ih,
                        "the cellar room did not fold back inside the inn")


class TestSettingsSwitch(unittest.TestCase):
    """A settings file records the cellars choice; the CLI's --no-basements
    overrides it, nothing else does."""

    def test_make_and_check_carry_the_choice(self):
        self.assertIs(settings.make(mode="quick", idea="x")["basements"], True)
        self.assertIs(settings.make(mode="quick", idea="x",
                                    basements=False)["basements"], False)
        old = {"kind": settings.KIND, "version": 1, "idea": "x"}
        self.assertIs(settings.check(old)["basements"],
                      True, "an older settings file defaults to cellars on")

    def test_the_file_rules_unless_the_flag_is_given(self):
        from worldgen.__main__ import _generate_args
        tmp = tempfile.mkdtemp(prefix="worldgen-basements-settings-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "settings.json")
        settings.write(path, settings.make(mode="quick", idea="a world",
                                           basements=False))

        def ns(**kw):
            base = {"settings": path, "idea": None, "seed": None, "ext": [],
                    "library": None, "item_library": None, "room_assembler": None,
                    "no_floors": False, "basements": None}
            base.update(kw)
            return argparse.Namespace(**base)

        self.assertIs(_generate_args(ns())["basements"],
                      False, "the settings file's false must rule")
        self.assertIs(_generate_args(ns(basements=False))["basements"], False)
        plain = ns(settings=None, idea="a world")
        self.assertIs(_generate_args(plain)["basements"],
                      True, "with no file and no flag, cellars stay on")


class TestNoCellarWorldUnchanged(unittest.TestCase):
    """A world with no cellar rooms anywhere builds byte-identical with the
    switch on: the plain village fixture, spec against spec."""

    @classmethod
    def setUpClass(cls):
        cls.builds = []
        for basements in (True, False):
            tmp = tempfile.mkdtemp(prefix="worldgen-basements-plain-")
            data = load("village.json")
            data["basements"] = basements
            summary = api._layout_and_build(data, seed=1, out_dir=tmp,
                                            extra_exts=("floors",))
            with open(os.path.join(summary["out"], "spec.json"),
                      "r", encoding="utf-8") as f:
                cls.builds.append(f.read())
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_spec_is_byte_identical(self):
        self.assertEqual(self.builds[0], self.builds[1])


class TestFloorsOff(unittest.TestCase):
    """Floors off: no cellar, no crash, and the summary says so."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-basements-floorsoff-")
        cls.lines = []
        cls.summary = api._layout_and_build(inn_with_cellar(), seed=1,
                                            out_dir=cls.tmp, extra_exts=(),
                                            floors=False, emit=cls.lines.append)
        path = os.path.join(cls.summary["out"], cls.summary["zip"][:-len(".zip")],
                            "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_cellar_and_a_summary_line(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertFalse([r for r in self.scn["regions"] if r.get("pocket")])
        self.assertTrue(any("floors off" in line for line in self.lines),
                        "the summary never notes the skipped cellars")


if __name__ == "__main__":
    unittest.main()
