"""Anywhere RPG small water, marked by the plan itself: a zone may carry
"water": "deep"|"shallow" and an outdoor entry may be {"name", "water":
"pond"|"pool"|"stream"|"ford"}. The marks win over name guessing (a plan that
marks anything stops guessing — an unmarked "Lake Road Inn" is dry ground),
each small feature ships as one unwalled water region laid out in free ground
— pond 5-9 cells a side, pool 3-5, a stream or ford a band 2-3 wide, a ford
always shallow — never as a prop, while the built water holders (a fountain,
a well) stay props."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api, native, phases
from worldgen.model import parse_plan
from worldgen.model import Rect
from worldgen.vendor import scenario_checks
from tests.test_locks_theft import WATCH_HOUSE_PLAN
from tests.test_sleep import CATALOGUE, _tmpl


def _world(*regions, grid=(24, 12)):
    """A bare world of just regions, for the classifier."""
    w = worldgen.World()
    w.grid = grid
    for r in regions:
        w.regions.append(r)
        w.regions_by_name[r.name] = r
    return w


class TestWaterMarks(unittest.TestCase):
    """A zone's own "water" mark decides, whatever its name or kind says."""

    def test_a_deep_mark_makes_water_despite_the_name_and_kind(self):
        inn = worldgen.RegionOut("The Sturdy Inn", Rect(0, 0, 24, 12), "zone")
        world = _world(inn)
        world.zone_kinds = {"The Sturdy Inn": "village"}
        world.zone_water = {"The Sturdy Inn": "deep"}
        world.water_marks = True
        self.assertEqual(native.water_regions(world, world.zone_kinds),
                         {"The Sturdy Inn": "deep"})

    def test_a_shallow_mark_overrides_the_short_side_rule(self):
        loch = worldgen.RegionOut("Weffling Waters", Rect(0, 0, 24, 12), "zone")
        world = _world(loch)
        world.zone_water = {"Weffling Waters": "shallow"}
        world.water_marks = True
        water = native.water_regions(world)
        self.assertEqual(water, {"Weffling Waters": "shallow"})
        self.assertEqual(native.water_surfaces(world, water),
                         {"Weffling Waters": "shallow water"},
                         "a wide but shallow loch is waded, not blocked")

    def test_a_lake_named_zone_is_dry_once_the_plan_marks_anything(self):
        road_inn = worldgen.RegionOut("Lake Road Inn", Rect(0, 0, 10, 12), "zone")
        mill = worldgen.RegionOut("Mill Pond Zone", Rect(10, 0, 14, 12), "zone")
        world = _world(road_inn, mill)
        world.zone_kinds = {"Lake Road Inn": "village",
                            "Mill Pond Zone": "village"}
        world.zone_water = {"Mill Pond Zone": "deep"}
        world.water_marks = True
        self.assertEqual(native.water_regions(world, world.zone_kinds),
                         {"Mill Pond Zone": "deep"},
                         "the name says lake, the plan marks nothing: dry")

    def test_a_plan_without_marks_still_gets_water_from_a_water_name(self):
        pond = worldgen.RegionOut("Mill Pond", Rect(0, 0, 24, 12), "zone")
        world = _world(pond)
        world.zone_kinds = {"Mill Pond": "village"}
        self.assertEqual(native.water_regions(world, world.zone_kinds),
                         {"Mill Pond": "deep"},
                         "older plans carry no marks: the name still counts")


def _water_plan():
    """The watch-house village beside a wet moor: the moor's outdoor list
    marks a pond, a stream and a ford as water objects, the village's marks a
    pool and names a fountain and a well (which hold water without being
    water). The village's dressing still catalogues every feature as a prop,
    the way P2 did before it knew the object form — the drop must clear them
    wherever they sit, not only in the feature's own zone."""
    data = json.loads(json.dumps(WATCH_HOUSE_PLAN))
    data["templates"] = CATALOGUE + [
        _tmpl("Duck Pond", 3, 3, ["water"]),
        _tmpl("Wishing Pool", 2, 2, ["water"]),
        _tmpl("Mill Stream", 3, 2, ["water"]),
        _tmpl("Horse Ford", 3, 2, ["water"]),
        _tmpl("Village Fountain", 2, 2, ["landmark"]),
        _tmpl("Old Well", 2, 2, ["landmark"]),
    ]
    village = data["zones"][0]
    village["outdoor"] = [{"name": "wishing pool", "water": "pool"},
                          "village fountain", "old well"]
    village["dressing"]["props"] = [
        {"template": "Duck Pond", "count": 1},
        {"template": "Wishing Pool", "count": 1},
        {"template": "Mill Stream", "count": 1},
        {"template": "Horse Ford", "count": 1},
        {"template": "Village Fountain", "count": 1},
        {"template": "Old Well", "count": 1},
    ]
    data["zones"].append({
        "name": "Weffling Moor", "kind": "moor", "sizeClass": "large",
        "description": "A wet moor.", "ground": "grass",
        "adjacentTo": ["Weffling"],
        "outdoor": [{"name": "duck pond", "water": "pond"},
                    {"name": "mill stream", "water": "stream"},
                    {"name": "horse ford", "water": "ford"}],
        "buildings": [],
        "dressing": {"paths": "none", "props": [], "filler": []},
    })
    data["roads"] = [{"from": "Weffling", "to": "Weffling Moor"}]
    return data


class TestSmallWaterValidation(unittest.TestCase):
    """The P1 contract check and the plan parse both reject junk marks."""

    def test_p1_rejects_a_bad_zone_water(self):
        d = json.loads(json.dumps(WATCH_HOUSE_PLAN))
        d["zones"][0]["water"] = "lava"
        errors = phases.check_p1(d)
        self.assertTrue(any("zones[0].water: must be deep or shallow, "
                            "not 'lava'" in e for e in errors), errors)

    def test_p1_rejects_a_bad_feature_water(self):
        d = json.loads(json.dumps(WATCH_HOUSE_PLAN))
        d["zones"][0]["outdoor"] = [{"name": "x", "water": "sea"}]
        errors = phases.check_p1(d)
        self.assertTrue(any("zones[0].outdoor[0].water: must be one of "
                            "['pond', 'pool', 'stream', 'ford'], not 'sea'"
                            in e for e in errors), errors)

    def test_p1_accepts_good_marks(self):
        d = _water_plan()
        for z in d["zones"]:
            z.pop("dressing", None)     # P1 knows no dressing yet
        errors = phases.check_p1(d)
        self.assertEqual([e for e in errors if "water" in e], [], errors)

    def test_parse_plan_rejects_bad_marks(self):
        d = json.loads(json.dumps(WATCH_HOUSE_PLAN))
        d["zones"][0]["water"] = "lava"
        with self.assertRaises(ValueError) as cm:
            parse_plan(d)
        self.assertIn("bad water 'lava'", str(cm.exception))
        d = json.loads(json.dumps(WATCH_HOUSE_PLAN))
        d["zones"][0]["outdoor"] = [{"name": "x", "water": "sea"}]
        with self.assertRaises(ValueError) as cm:
            parse_plan(d)
        self.assertIn("water must be one of", str(cm.exception))

    def test_parse_plan_carries_the_marks_and_the_features(self):
        plan = parse_plan(_water_plan())
        by_name = {z.name: z for z in plan.zones}
        self.assertEqual(by_name["Weffling Moor"].water, "")
        self.assertEqual(by_name["Weffling Moor"].water_features,
                         [("duck pond", "pond"), ("mill stream", "stream"),
                          ("horse ford", "ford")])
        self.assertEqual(by_name["Weffling"].water_features,
                         [("wishing pool", "pool")])


class TestSmallWaterWorld(unittest.TestCase):
    """The watch-house plan with marked small water, built end to end: each
    feature is one unwalled water region of its kind's size on free ground,
    the pond (5x5 and up) organic, the ford shallow, none overlapping
    anything built or placed, and no feature ships as a prop while the
    fountain and the well do."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-small-water-")
        cls.data = _water_plan()
        cls.world = worldgen.run(cls.data, seed=1)
        cls.spec = worldgen.build_spec(cls.world, cls.data)
        cls.summary = api._layout_and_build(cls.data, seed=1, out_dir=cls.tmp)
        path = os.path.join(cls.summary["out"],
                            cls.summary["zip"][:-len(".zip")], "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)
        cls.path = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _region(self, name):
        return next(r for r in self.scn["regions"] if r["name"] == name)

    def _cells(self, name):
        r = self.world.regions_by_name[name]
        return r.rect.cells()

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_each_feature_is_one_unwalled_water_region(self):
        for name in ("Duck Pond", "Wishing Pool", "Mill Stream", "Horse Ford"):
            kinds = [r.kind for r in self.world.regions if r.name == name]
            self.assertEqual(kinds, ["water"], name)
            area = self._region(name)
            self.assertFalse(area.get("wall"), name)
            self.assertEqual(area.get("surface"), "water", name)

    def test_sizes_follow_the_kinds(self):
        pond = self.world.regions_by_name["Duck Pond"].rect
        self.assertTrue(5 <= pond.w <= 9 and 5 <= pond.h <= 9, pond)
        pool = self.world.regions_by_name["Wishing Pool"].rect
        self.assertTrue(3 <= pool.w <= 5 and 3 <= pool.h <= 5, pool)
        stream = self.world.regions_by_name["Mill Stream"].rect
        self.assertTrue(min(stream.w, stream.h) in (2, 3)
                        and max(stream.w, stream.h) >= 4, stream)
        ford = self.world.regions_by_name["Horse Ford"].rect
        self.assertTrue(min(ford.w, ford.h) in (2, 3)
                        and max(ford.w, ford.h) >= 4, ford)

    def test_the_pond_is_organic_and_the_bands_are_not(self):
        pond = self._region("Duck Pond")
        self.assertIn(pond.get("shape"), ("natural", "organic"),
                      "5x5 and up ships organic")
        for name in ("Mill Stream", "Horse Ford"):
            area = self._region(name)
            w, h = area.get("size", [0, 0])
            if min(w, h) < 5:
                self.assertNotIn(area.get("shape"), ("natural", "organic"),
                                 f"{name} keeps its rectangle below 5 wide")
        pool = self._region("Wishing Pool")
        w, h = pool.get("size", [0, 0])
        if min(w, h) >= 5:
            self.assertIn(pool.get("shape"), ("natural", "organic"))

    def test_the_ford_is_always_shallow(self):
        water = native.water_regions(self.world)
        self.assertEqual(water["Horse Ford"], "shallow",
                         "a ford is waded at band width 2-3")

    def test_no_water_overlaps_anything_built_planted_or_placed(self):
        blocked = set()
        for r in self.world.regions:
            if r.kind in ("building", "room", "path", "yard", "field",
                          "square", "road"):
                blocked |= r.rect.cells()
        for o in self.world.objects:
            if o.template in self.world.templates:
                blocked |= native.footprint(self.world, o)
        for name in ("Duck Pond", "Wishing Pool", "Mill Stream", "Horse Ford"):
            self.assertEqual(self._cells(name) & blocked, set(), name)

    def test_no_feature_ships_as_a_prop_but_the_holders_do(self):
        placed = {o.template for o in self.world.objects}
        for name in ("Duck Pond", "Wishing Pool", "Mill Stream", "Horse Ford"):
            self.assertNotIn(name, placed, name)
        self.assertIn("Village Fountain", placed)
        self.assertIn("Old Well", placed)
        self.assertTrue(any("dropped: water in this plan" in r
                            for (_w, r) in self.world.failures),
                        "the P2-era props are dropped with a note")

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)

    def test_the_shipped_scenario_mods_check_is_clean(self):
        from worldgen import checks as checks_mod
        self.assertEqual(checks_mod.check_scenario_mods(self.path, self.spec),
                         [])


if __name__ == "__main__":
    unittest.main()
