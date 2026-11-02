"""The floors extension: its contract (P1 storeys, P3 stairs/upper), and —
further down the file, added with the layout — the placed storeys, stairs
portals and openings."""
import json
import os
import unittest

import worldgen
from worldgen import phases
from worldgen.model import parse_plan

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

CATALOGUE = {"Straw Bed", "Oak Table", "Wooden Stool", "Clay Hearth", "Lamp",
             "Spiral Stair"}

GROUND = {
    "name": "The Sickle & Sheaf", "wall": "wood", "ground": "wood",
    "rooms": [
        {"name": "Common Room", "share": "large", "purpose": "ale and talk"},
        {"name": "Back Hall", "share": "small", "purpose": "the stair"},
    ],
    "connections": [["Common Room", "Back Hall"]],
    "entrance": {"room": "Common Room", "side": "south"},
    "furniture": [
        {"template": "Oak Table", "room": "Common Room", "count": 2, "hint": "center"},
        {"template": "Clay Hearth", "room": "Common Room", "count": 1, "hint": "wall:north"},
    ],
    "yard": None,
}


def upper_storey(**kw):
    u = {"storey": 2,
         "rooms": [{"name": "Gallery", "share": "large", "purpose": "seats at the rail"},
                   {"name": "Landing", "share": "small", "purpose": "the stair head"}],
         "connections": [["Gallery", "Landing"]],
         "furniture": [{"template": "Wooden Stool", "room": "Gallery", "count": 2,
                        "hint": "wall:north"}],
         "opening": {"over_room": "Common Room", "kind": "gallery"}}
    u.update(kw)
    return u


class TestP1Storeys(unittest.TestCase):
    def _errors(self, storeys, floors=True):
        b = {"name": "Inn", "kind": "inn", "sizeClass": "large", "purpose": "ale"}
        if storeys is not None:
            b["storeys"] = storeys
        zone = {"name": "Z", "kind": "village", "sizeClass": "medium",
                "description": "d", "ground": "grass", "adjacentTo": [],
                "outdoor": [], "buildings": [b]}
        d = {"worldBackground": "b", "setting": {"era": "e", "technology": "t",
                                                 "density": "normal", "climate": "c"},
             "mapSize": "small", "zones": [zone], "roads": []}
        return phases.check_p1(d, floors=floors)

    def test_1_to_3_accepted(self):
        for s in (1, 2, 3):
            self.assertEqual(self._errors(s), [], f"storeys={s}")

    def test_out_of_range_rejected(self):
        for s in (0, 4, "two", 2.5):
            self.assertTrue(any("storeys" in e for e in self._errors(s)), s)

    def test_no_field_is_fine(self):
        self.assertEqual(self._errors(None), [])

    def test_ignored_without_the_extension(self):
        self.assertEqual(self._errors(9, floors=False), [])

    def test_sanitize_clamps_and_strips(self):
        log = []
        d = {"zones": [{"name": "Z", "kind": "village", "sizeClass": "medium",
                        "description": "d", "ground": "grass", "adjacentTo": [],
                        "outdoor": [], "buildings": [
                            {"name": "A", "kind": "inn", "sizeClass": "small",
                             "purpose": "p", "storeys": 9}]}],
             "roads": []}
        phases.sanitize_p1(d, log, floors=True)
        self.assertEqual(d["zones"][0]["buildings"][0]["storeys"], 1)
        phases.sanitize_p1(d, log, floors=False)
        self.assertNotIn("storeys", d["zones"][0]["buildings"][0])


class TestP3Upper(unittest.TestCase):
    def _errors(self, d, storeys=2):
        return phases.check_p3(d, "The Sickle & Sheaf", CATALOGUE, False, storeys=storeys)

    def test_valid_upper_passes(self):
        d = dict(GROUND, stairs={"room": "Back Hall"}, upper=[upper_storey()])
        self.assertEqual(self._errors(d), [])

    def test_stairs_must_name_a_ground_room(self):
        d = dict(GROUND, stairs={"room": "Cellar"}, upper=[upper_storey()])
        self.assertTrue(any("stairs" in e for e in self._errors(d)))
        d = dict(GROUND, upper=[upper_storey()])
        self.assertTrue(any("stairs" in e for e in self._errors(d)))

    def test_storey_bounds_and_duplicates(self):
        d = dict(GROUND, stairs={"room": "Back Hall"},
                 upper=[upper_storey(storey=4), upper_storey(storey=1),
                        upper_storey(storey=2)])
        errors = self._errors(d, storeys=3)
        self.assertTrue(any("storey" in e and "2.." in e for e in errors))
        d = dict(GROUND, stairs={"room": "Back Hall"},
                 upper=[upper_storey(), upper_storey()])
        errors = self._errors(d, storeys=3)
        self.assertTrue(any("twice" in e for e in errors), errors)

    def test_upper_rooms_and_furniture_checked(self):
        d = dict(GROUND, stairs={"room": "Back Hall"},
                 upper=[upper_storey(furniture=[
                     {"template": "Not In Catalogue", "room": "Gallery", "count": 1, "hint": ""},
                     {"template": "Straw Bed", "room": "Nowhere", "count": 1, "hint": ""},
                     {"template": "Straw Bed", "room": "Gallery", "count": 99, "hint": ""}])])
        errors = self._errors(d)
        self.assertTrue(any("not in the catalogue" in e for e in errors))
        self.assertTrue(any("not one of this storey's rooms" in e for e in errors))
        self.assertTrue(any("count" in e for e in errors))

    def test_opening_over_a_ground_room_with_a_known_kind(self):
        d = dict(GROUND, stairs={"room": "Back Hall"},
                 upper=[upper_storey(opening={"over_room": "Kitchen", "kind": "gallery"})])
        errors = self._errors(d)
        self.assertTrue(any("over_room" in e for e in errors))
        d = dict(GROUND, stairs={"room": "Back Hall"},
                 upper=[upper_storey(opening={"over_room": "Common Room", "kind": "well"})])
        errors = self._errors(d)
        self.assertTrue(any("kind" in e for e in errors))

    def test_ignored_without_the_extension(self):
        d = dict(GROUND, stairs={"room": "Nowhere"}, upper=[{"storey": 9}])
        self.assertEqual(self._errors(d, storeys=None), [])

    def test_sanitize_drops_the_bad_and_keeps_the_good(self):
        d = dict(GROUND, stairs={"room": "Back Hall"},
                 upper=[upper_storey(),
                        upper_storey(storey=2, rooms=[]),
                        upper_storey(storey=9),
                        upper_storey(storey=3, furniture=[
                            {"template": "Lamp", "room": "Landing", "count": 1, "hint": "wall:zzz"}],
                            opening={"over_room": "Common Room", "kind": "well"})])
        log = []
        phases.sanitize_p3(d, "The Sickle & Sheaf", CATALOGUE, log, storeys=3)
        self.assertEqual([u["storey"] for u in d["upper"]], [2, 3])
        self.assertEqual(d["upper"][1]["opening"], None)
        self.assertEqual(d["upper"][1]["furniture"][0]["hint"], "")
        self.assertEqual(d["stairs"], {"room": "Back Hall"})
        self.assertTrue(log)

    def test_sanitize_strips_when_off_or_single_storey(self):
        d = dict(GROUND, stairs={"room": "Back Hall"}, upper=[upper_storey()])
        log = []
        phases.sanitize_p3(d, "The Sickle & Sheaf", CATALOGUE, log, storeys=None)
        self.assertEqual(d["upper"], [])
        self.assertIsNone(d["stairs"])
        d = dict(GROUND, stairs={"room": "Back Hall"}, upper=[upper_storey()])
        phases.sanitize_p3(d, "The Sickle & Sheaf", CATALOGUE, log, storeys=1)
        self.assertEqual(d["upper"], [])
        self.assertIsNone(d["stairs"])


def _plan_with_floors():
    """A minimal merged plan: one two-storey inn over a full catalogue."""
    return {
        "name": "Marrowgate", "worldBackground": "A market town.",
        "setting": {"era": "medieval", "technology": "timber",
                    "density": "normal", "climate": "wet"},
        "mapSize": "small",
        "zones": [{
            "name": "Marrowgate", "kind": "market town", "sizeClass": "medium",
            "description": "The town square.", "ground": "grass", "adjacentTo": [],
            "outdoor": ["town well"],
            "buildings": [{"name": "The Sickle & Sheaf", "kind": "inn",
                           "sizeClass": "large", "purpose": "ale and beds",
                           "storeys": 2, "yard": None}],
            "dressing": {"paths": "dirt", "props": [], "filler": []},
        }],
        "roads": [],
        "templates": [
            {"name": "Straw Bed", "size": [1, 2], "walkability": 0, "forSleep": True,
             "tags": ["bed"], "description": "A bed.",
             "physicalDescription": "a bed", "rule": "along a wall"},
            {"name": "Oak Table", "size": [2, 1], "walkability": 0, "tags": ["table"],
             "description": "A table.", "physicalDescription": "a table",
             "rule": "in the middle"},
            {"name": "Wooden Stool", "size": [1, 1], "walkability": 0, "tags": ["seat"],
             "description": "A stool.", "physicalDescription": "a stool",
             "rule": "around tables"},
            {"name": "Clay Hearth", "size": [2, 1], "walkability": 0, "tags": ["fire"],
             "description": "A hearth.", "physicalDescription": "a hearth",
             "rule": "against a wall"},
            {"name": "Lamp", "size": [1, 1], "walkability": 0, "tags": ["light"],
             "description": "A lamp.", "physicalDescription": "a lamp",
             "rule": "anywhere"},
        ],
        "buildings": [dict(
            GROUND,
            stairs={"room": "Back Hall"},
            furniture=GROUND["furniture"] + [
                {"template": "Straw Bed", "room": "Back Hall", "count": 1, "hint": "corner"},
            ],
            upper=[dict(upper_storey(),
                        furniture=[{"template": "Wooden Stool", "room": "Gallery",
                                    "count": 2, "hint": "wall:north"},
                                   {"template": "Straw Bed", "room": "Landing",
                                    "count": 1, "hint": "corner"},
                                   {"template": "Lamp", "room": "Landing",
                                    "count": 1, "hint": "center"}])])],
        "npcs": [{"name": "Sela Fox", "gender": "female", "role": "innkeeper",
                  "home": "The Sickle & Sheaf", "work": "The Sickle & Sheaf",
                  "description": "The keeper.", "physicalDescription": "stout"}],
        "player": {"name": "Tam Pike", "gender": "male", "role": "pedlar",
                   "home": "The Sickle & Sheaf", "work": "Marrowgate",
                   "description": "A pedlar.", "physicalDescription": "thin"},
    }


class TestParsePlanFloors(unittest.TestCase):
    def test_storeys_stairs_upper_parsed(self):
        plan = parse_plan(_plan_with_floors())
        b = plan.zones[0].buildings[0]
        self.assertEqual(b.storeys, 2)
        self.assertEqual(b.stairs_room, "Back Hall")
        self.assertEqual(len(b.upper), 1)
        u = b.upper[0]
        self.assertEqual(u.storey, 2)
        self.assertEqual([r.name for r in u.rooms], ["Gallery", "Landing"])
        self.assertEqual(u.opening.over_room, "Common Room")
        self.assertEqual(u.opening.kind, "gallery")
        self.assertEqual(u.furniture[0].template, "Wooden Stool")

    def test_storeys_clamped_and_upper_filtered(self):
        data = _plan_with_floors()
        data["zones"][0]["buildings"][0]["storeys"] = "two"
        data["buildings"][0]["upper"].append(upper_storey(storey=3))
        plan = parse_plan(data)
        b = plan.zones[0].buildings[0]
        self.assertEqual(b.storeys, 1)
        self.assertEqual(b.upper, [])
        self.assertEqual(b.stairs_room, "")

    def test_upper_beyond_the_count_is_dropped(self):
        data = _plan_with_floors()
        data["buildings"][0]["upper"].append(upper_storey(storey=3))
        plan = parse_plan(data)
        b = plan.zones[0].buildings[0]
        self.assertEqual(b.storeys, 2)
        self.assertEqual([u.storey for u in b.upper], [2])

    def test_no_storeys_leaves_the_plan_alone(self):
        data = _plan_with_floors()
        data["zones"][0]["buildings"][0].pop("storeys")
        plan = parse_plan(data)
        b = plan.zones[0].buildings[0]
        self.assertEqual(b.storeys, 1)
        self.assertEqual(b.upper, [])


class TestFloorsChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _plan_with_floors()
        cls.world = worldgen.run(cls.data, seed=1, extensions=("floors",))

    def test_clean_build_has_no_floor_issues(self):
        m = self.world.metrics["floors"]
        self.assertEqual(m["floors"], 1)
        self.assertEqual(m["portals"], 1)
        self.assertEqual(m["issues"], [], m["issues"])

    def test_object_names_match_the_builders_numbering(self):
        from worldgen.checks import object_entity_names
        stairs = sorted(n for o, n in object_entity_names(self.world).items()
                        if "stairs" in o.template)
        self.assertEqual(stairs, ["The Sickle & Sheaf stairs down 1",
                                  "The Sickle & Sheaf stairs up 1"])

    def test_size_mismatch_is_caught(self):
        from worldgen.model import Rect
        from worldgen import checks as checks_mod
        world = self.world
        f = world.floors[0]
        above = world.regions_by_name[f.above]
        old = above.rect
        above.rect = Rect(old.x, old.y, old.w - 2, old.h)
        try:
            issues = checks_mod._floors_checks(world, set())
        finally:
            above.rect = old
        self.assertTrue(any("sits over" in i for i in issues), issues)

    def test_missing_portal_end_is_caught(self):
        world = self.world
        world.portals.append({"name": "Ghost stairs", "from": {"object": "No Such Stair"},
                              "to": {"object": "Staircase 1"}, "twoWay": True})
        from worldgen import checks as checks_mod
        issues = checks_mod._floors_checks(world, set())
        world.portals.pop()
        self.assertTrue(any("Ghost stairs" in i for i in issues), issues)

    def test_unwalkable_stair_is_caught(self):
        world = self.world
        t = world.templates[world.floors[0].stair_down[0]]
        keep = t.walkability
        t.walkability = 0.0
        from worldgen import checks as checks_mod
        issues = checks_mod._floors_checks(world, set())
        t.walkability = keep
        self.assertTrue(any("not walkable" in i for i in issues), issues)

    def test_a_stair_ending_two_portals_is_caught(self):
        world = self.world
        f = world.floors[0]
        world.portals.append({"name": "Double-duty stair",
                              "from": {"object": f.stair_below_up_object},
                              "to": {"object": f.stair_down_object},
                              "twoWay": True})
        from worldgen import checks as checks_mod
        issues = checks_mod._floors_checks(world, set())
        world.portals.pop()
        self.assertTrue(any("already the" in i for i in issues), issues)

    def test_object_in_opening_is_caught(self):
        world = self.world
        f = world.floors[0]
        cell = sorted(f.opening_rect.cells())[0]
        world.objects.append(worldgen.ObjectOut("Lamp", cell, f.region_name))
        from worldgen import checks as checks_mod
        issues = checks_mod._floors_checks(world, set())
        world.objects.pop()
        self.assertTrue(any("sits in the opening" in i for i in issues), issues)

    def test_unreachable_upper_room_is_caught(self):
        from worldgen import checks as checks_mod
        world = self.world
        f = world.floors[0]
        openings = checks_mod.compute_openings(world)
        blocked, _doors = checks_mod.walkability_grid(world, openings)
        gallery = f.layout.rooms[0]
        blocked |= set(gallery.doors)   # wall the gallery up: only the stairs remain
        issues = checks_mod._floors_checks(world, blocked)
        self.assertTrue(any(f"{gallery.base_name} on" in i and "not reachable" in i
                            for i in issues), issues)


class TestScenarioModsRoundtrip(unittest.TestCase):
    def _scenario_dir(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        d = os.path.join(tmp, "Test.scenario")
        os.makedirs(os.path.join(d, "media"), exist_ok=True)
        with open(os.path.join(d, "scenario.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "Test", "gridSize": [10, 10], "regions": []}, f)
        with open(os.path.join(d, "media", "x.txt"), "w") as f:
            f.write("x")
        self.addCleanup(_rmtree, tmp)
        return d

    def test_inject_writes_json_and_rezips(self):
        from worldgen import mods
        d = self._scenario_dir()
        arpg = {"floors": [{"name": "F", "area": "A", "above": "B", "openings": []}],
                "portals": []}
        zpath = mods.inject_arpg_mods(d, arpg)
        self.assertTrue(os.path.exists(zpath))
        with open(os.path.join(d, "scenario.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["arpgMods"], arpg)
        import zipfile
        with zipfile.ZipFile(zpath) as z:
            self.assertIn("scenario.json", z.namelist())
            self.assertIn("media/x.txt", z.namelist())
            import io
            scn = json.load(io.TextIOWrapper(z.open("scenario.json"), encoding="utf-8"))
            self.assertEqual(scn["arpgMods"], arpg)

    def test_check_scenario_mods(self):
        from worldgen import checks as checks_mod, mods
        d = self._scenario_dir()
        arpg = {"floors": [], "portals": []}
        mods.inject_arpg_mods(d, arpg)
        self.assertEqual(checks_mod.check_scenario_mods(
            os.path.join(d, "scenario.json"), arpg), [])
        self.assertTrue(checks_mod.check_scenario_mods(
            os.path.join(d, "scenario.json"), {"floors": [{"name": "x"}], "portals": []}))

    def test_inject_hardens_the_boundary_slab(self):
        from worldgen import mods
        from worldgen.extensions.floors import SLAB_NAME
        d = self._scenario_dir()
        with open(os.path.join(d, "scenario.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "Test", "gridSize": [40, 10],
                       "objectTemplates": [{"id": "otpl_s", "name": SLAB_NAME,
                                            "size": [24, 10], "walkability": 1.0}],
                       "entities": []}, f)
        mods.inject_arpg_mods(d, {"floors": [], "portals": []})
        with open(os.path.join(d, "scenario.json"), encoding="utf-8") as f:
            scn = json.load(f)
        self.assertEqual(scn["objectTemplates"][0]["walkability"], 0.0)
        sprite = os.path.join(d, "media", "otpl_s", "otpl_s-sprite.webp")
        self.assertTrue(os.path.exists(sprite), "the slab's sprite must ship with it")

    def test_check_scenario_mods_flags_a_sealed_upper_room(self):
        from worldgen import checks as checks_mod
        d = self._scenario_dir()
        arpg = {"floors": [{"name": "F", "area": "Storey", "above": "B", "openings": []}],
                "portals": []}
        # a storey whose inner room lost its door to the seal
        with open(os.path.join(d, "scenario.json"), "w", encoding="utf-8") as f:
            json.dump({"arpgMods": arpg, "regions": [
                {"name": "Storey", "position": [10, 10], "size": [10, 8],
                 "wall": "wood", "openings": []},
                {"name": "Storey Room", "position": [11, 11], "size": [8, 6],
                 "wall": "wood", "openings": []}]}, f)
        issues = checks_mod.check_scenario_mods(
            os.path.join(d, "scenario.json"), arpg)
        self.assertTrue(any("sealed inside" in i for i in issues), issues)

    def test_check_scenario_mods_flags_a_leaky_boundary(self):
        from worldgen import checks as checks_mod
        from worldgen.extensions.floors import SLAB_NAME
        d = self._scenario_dir()
        arpg = {"floors": [{"name": "F", "area": "A", "above": "B", "openings": []}],
                "portals": []}
        # a slab that kept its build-time passability, has no sprite, and carries
        # a stale first-pass size that no longer covers the region
        with open(os.path.join(d, "scenario.json"), "w", encoding="utf-8") as f:
            json.dump({"arpgMods": arpg,
                       "regions": [{"name": "The Edge of the World", "position": [20, 0],
                                    "size": [24, 10]}],
                       "objectTemplates": [
                           {"id": "otpl_s", "name": SLAB_NAME, "size": [24, 6],
                            "walkability": 1.0}],
                       "entities": [{"id": "obj_s", "type": "object",
                                     "name": SLAB_NAME, "pos": [20, 0], "size": [24, 6],
                                     "templateId": "otpl_s"}]}, f)
        issues = checks_mod.check_scenario_mods(
            os.path.join(d, "scenario.json"), arpg)
        self.assertTrue(any("must block" in i for i in issues), issues)
        self.assertTrue(any("no sprite" in i for i in issues), issues)
        self.assertTrue(any("cover it exactly" in i for i in issues), issues)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ------------------------------------------------------------- the fixture

REAL_PLANS = ("cyberpunk-glm-plan.json", "medieval-deepseek-plan.json",
              "medieval-glm-plan.json", "modern-glm-plan.json")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


class TestFloorsFixture(unittest.TestCase):
    """fixtures/floors-plan.json: a two-storey inn with a gallery over the
    common room, a three-storey apartment block, and one single-storey
    house."""
    @classmethod
    def setUpClass(cls):
        cls.data = load_fixture("floors-plan.json")
        cls.world = worldgen.run(cls.data, seed=1, extensions=("floors",))

    def test_builds_clean(self):
        m = self.world.metrics
        self.assertEqual(m["region_overlaps"], [])
        self.assertEqual(m["object_overlaps"], [])
        self.assertEqual(m["objects_out_of_bounds"], [])
        self.assertEqual(m["objects"]["unplaced"], [])
        self.assertEqual(m["reachability"], 1.0)
        self.assertTrue(m["doors_clear"])
        self.assertTrue(m["walkways_clear"])
        self.assertEqual(m["floors"]["issues"], [])

    def test_seeds_build_clean(self):
        for seed in (2, 3, 4, 5):
            with self.subTest(seed):
                world = worldgen.run(load_fixture("floors-plan.json"),
                                     seed=seed, extensions=("floors",))
                self.assertEqual(world.metrics["floors"]["issues"], [])
                self.assertEqual(world.metrics["objects"]["unplaced"], [])
                self.assertEqual(world.metrics["reachability"], 1.0)

    def test_expected_storeys_and_names(self):
        by = {}
        for f in self.world.floors:
            by.setdefault(f.building, []).append(f.storey)
        self.assertEqual(by, {"Weaver's Rows": [2, 3],
                              "The Sickle & Sheaf": [2]})
        names = {f.region_name for f in self.world.floors}
        self.assertIn("The Sickle & Sheaf (upper floor)", names)
        self.assertIn("Weaver's Rows (upper floor)", names)
        self.assertIn("Weaver's Rows (top floor)", names)
        self.assertIn("The Sickle & Sheaf (upper floor) Gallery Well",
                      {r.name for r in self.world.regions})

    def test_each_floor_matches_its_above_region(self):
        for f in self.world.floors:
            above = self.world.regions_by_name[f.above]
            self.assertEqual((f.rect.w, f.rect.h), (above.rect.w, above.rect.h))

    def test_boundary_separates_the_band_from_the_play_area(self):
        from worldgen.extensions.floors import (BOUNDARY_COLOR, BOUNDARY_NAME,
                                                SEPARATOR_WIDTH, SLAB_NAME)
        b = self.world.regions_by_name[BOUNDARY_NAME]
        # the region spans everything east of the play area: full height, to the
        # map's east edge, unwalled, tinted the void's colour — the band's gaps
        # show the tint, so the storeys read as the only lit things there
        self.assertIsNone(b.wall)
        self.assertEqual((b.rect.y, b.rect.h), (0, self.world.grid[1]))
        self.assertEqual(b.rect.x1, self.world.grid[0] - 1)
        self.assertEqual(b.ground_color, BOUNDARY_COLOR)
        # the strip's first SEPARATOR_WIDTH cells are sealed by one slab exactly
        slab = self.world.templates[SLAB_NAME]
        self.assertEqual(slab.walkability, 0.0)
        self.assertEqual(slab.size, (SEPARATOR_WIDTH, self.world.grid[1]))
        placed = [o for o in self.world.objects if o.template == SLAB_NAME]
        self.assertEqual([o.pos for o in placed], [(b.rect.x, 0)])
        strip_cells = {(x, y) for x in range(b.rect.x, b.rect.x + SEPARATOR_WIDTH)
                       for y in range(self.world.grid[1])}
        # nothing else sits in the strip
        for o in self.world.objects:
            if o.template == SLAB_NAME:
                continue
            t = self.world.templates[o.template]
            fp = {(x, y) for x in range(o.pos[0], o.pos[0] + t.size[0])
                  for y in range(o.pos[1], o.pos[1] + t.size[1])}
            self.assertFalse(fp & strip_cells, f"{o.template} sits inside the strip")
        # every storey nests east of the slab, inside the region
        for f in self.world.floors:
            self.assertGreaterEqual(f.rect.x, b.rect.x + SEPARATOR_WIDTH,
                                    f"{f.region_name} is not east of the slab")
            self.assertLessEqual(f.rect.x1, b.rect.x1,
                                 f"{f.region_name} leaves the boundary region")

    def test_openings_exist_and_stay_empty(self):
        inn = next(f for f in self.world.floors if f.building == "The Sickle & Sheaf")
        self.assertIsNotNone(inn.opening_rect, "the inn's gallery opening was dropped")
        atrium = next(f for f in self.world.floors
                      if f.building == "Weaver's Rows" and f.storey == 2)
        self.assertIsNotNone(atrium.opening_rect, "the atrium was dropped")
        for f in (inn, atrium):
            cells = f.opening_rect.cells()
            for o in self.world.objects:
                t = self.world.templates[o.template]
                fp = {(x, y) for x in range(o.pos[0], o.pos[0] + t.size[0])
                      for y in range(o.pos[1], o.pos[1] + t.size[1])}
                self.assertFalse(fp & cells, f"{o.template} sits in {f.opening_name}")

    def test_separate_stairs_with_unique_ends(self):
        """On a storey with stairs both down and up, two stair objects in
        different cells; each stair object is the end of at most one portal."""
        from worldgen.checks import object_entity_names
        names = set(object_entity_names(self.world).values())
        for f in self.world.floors:
            for ref, label in ((f.stair_down, "down"), (f.stair_up, "up")):
                if ref is None:
                    self.assertEqual(label, "up", "only the top storey lacks an up stair")
                    continue
                self.assertIn(f"{ref[0]} 1", names)
            if f.stair_down is not None and f.stair_up is not None:
                (dx, dy), (ux, uy) = f.stair_down[1], f.stair_up[1]
                self.assertGreaterEqual(max(abs(dx - ux), abs(dy - uy)), 2,
                                        f"{f.region_name}: its two stairs are adjacent")
        ends = [p["from"]["object"] for p in self.world.portals] + \
               [p["to"]["object"] for p in self.world.portals]
        self.assertEqual(len(ends), len(set(ends)), "a stair object ends two portals")

    def test_portals_link_the_stair_pairs(self):
        self.assertEqual(len(self.world.portals), 3)
        for p in self.world.portals:
            self.assertTrue(p["twoWay"])
            self.assertIn("object", p["from"])
            self.assertIn("object", p["to"])
        # the middle storey's portals end on four distinct stairs
        weavers = sorted((f for f in self.world.floors if f.building == "Weaver's Rows"),
                         key=lambda f: f.storey)
        middle = weavers[0]
        self.assertIsNotNone(middle.stair_down)
        self.assertIsNotNone(middle.stair_up)
        self.assertIsNotNone(middle.stair_below_up)
        stairs = {middle.stair_down[1], middle.stair_up[1], middle.stair_below_up[1]}
        self.assertEqual(len(stairs), 3)

    def test_the_stair_templates_are_walkable(self):
        for f in self.world.floors:
            for ref in (f.stair_down, f.stair_up):
                if ref is not None:
                    self.assertGreater(self.world.templates[ref[0]].walkability, 0)

    def test_upstairs_people_sleep_upstairs(self):
        sleeps = {}
        for c in self.world.characters:
            for blk in c.schedule:
                if blk["role"] == "sleep":
                    sleeps[c.name] = blk["location"]
        self.assertTrue(sleeps["Sela Fox"].startswith("The Sickle & Sheaf (upper floor)"))
        self.assertTrue(sleeps["Maud Harness"].startswith("Weaver's Rows ("))
        self.assertTrue(sleeps["Ned Sparrow"].startswith("Weaver's Rows ("))
        self.assertEqual(sleeps["Hartley Green"], "Hedge Cottage Bedroom")

    def test_single_storey_house_gets_no_floor(self):
        floors = {f.building for f in self.world.floors}
        self.assertNotIn("Hedge Cottage", floors)
        self.assertFalse(any("Hedge Cottage (upper floor)" == r.name
                             for r in self.world.regions))

    def test_spec_arpg_mods_match_the_world(self):
        spec = worldgen.build_spec(self.world, self.data)
        mods = spec["arpgMods"]
        self.assertEqual(len(mods["floors"]), len(self.world.floors))
        self.assertEqual(len(mods["portals"]), len(self.world.portals))
        for f in self.world.floors:
            entry = next(e for e in mods["floors"] if e["area"] == f.region_name)
            self.assertEqual(entry["above"], f.above)
            self.assertEqual(entry["openings"],
                             [f.opening_name] if f.opening_name else [])


class TestGLMFloorsFixtures(unittest.TestCase):
    """The two real floors-enabled plans: every planned building and storey
    is placed (content sizing grows the zones and the map rather than
    dropping), no storey keeps an exterior opening, and every stair object
    ends at most one portal."""

    FLOORS_FIXTURES = (
        ("cyberpunk-glm-floors-plan.json", ("floors", "region-groups")),
        ("medieval-glm-floors-plan.json", ("floors", "region-groups")),
        ("floors-plan.json", ("floors",)),
    )

    @classmethod
    def setUpClass(cls):
        cls.worlds = {}
        for (name, exts) in cls.FLOORS_FIXTURES:
            cls.worlds[name] = worldgen.run(load_fixture(name), seed=1, extensions=exts)

    def test_cyberpunk_places_every_planned_building(self):
        data = load_fixture("cyberpunk-glm-floors-plan.json")
        world = self.worlds["cyberpunk-glm-floors-plan.json"]
        planned = {b["name"] for z in data["zones"] for b in z["buildings"]}
        self.assertEqual(len(planned), 11)
        self.assertEqual({b.layout.design.name for b in world.buildings}, planned)
        storeys = {}
        for f in world.floors:
            storeys.setdefault(f.building, []).append(f.storey)
        self.assertEqual(storeys.get("Pillar 12 Apartments"), [2, 3])
        self.assertEqual(storeys.get("Pillar 13 Apartments"), [2, 3])
        self.assertEqual(storeys.get("The Leaky Amp"), [2])
        self.assertEqual(storeys.get("Squatters' Annex"), [2])

    def test_no_dropped_buildings_or_storeys_in_any_fixture(self):
        for seed in (1, 2, 3):
            for (name, exts) in self.FLOORS_FIXTURES:
                with self.subTest(f"{name} seed {seed}"):
                    world = worldgen.run(load_fixture(name), seed=seed, extensions=exts)
                    self.assertEqual(world.metrics["errors"]["dropped"], [],
                                     world.metrics["errors"]["dropped"])
                    self.assertEqual(world.metrics["floors"]["issues"], [],
                                     world.metrics["floors"]["issues"])
                    self.assertEqual(world.metrics["reachability"], 1.0)

    def test_no_exterior_openings_on_upper_storeys(self):
        from worldgen import checks as checks_mod
        for (name, _exts) in self.FLOORS_FIXTURES:
            world = self.worlds[name]
            with self.subTest(name):
                openings = checks_mod.compute_openings(world)
                for f in world.floors:
                    ring = {c for c in f.rect.cells()
                            if c[0] in (f.rect.x, f.rect.x1) or c[1] in (f.rect.y, f.rect.y1)}
                    parts = [f.region_name] + [r.full_name for r in f.layout.rooms
                                               if r.full_name != f.region_name]
                    for part in parts:
                        hit = openings.get(part, set()) & ring
                        self.assertFalse(hit, f"{part} keeps exterior opening {sorted(hit)}")

    def test_unique_stair_ends_in_any_fixture(self):
        for (name, _exts) in self.FLOORS_FIXTURES:
            world = self.worlds[name]
            with self.subTest(name):
                ends = [e for p in world.portals
                        for e in (p["from"]["object"], p["to"]["object"])]
                self.assertEqual(len(ends), len(set(ends)))
                for f in world.floors:
                    if f.stair_down is not None and f.stair_up is not None:
                        (dx, dy), (ux, uy) = f.stair_down[1], f.stair_up[1]
                        self.assertGreaterEqual(max(abs(dx - ux), abs(dy - uy)), 2,
                                                f"{f.region_name}: adjacent stairs")


class TestGrowthNeverDrops(unittest.TestCase):
    """Content sizing is a target, not a limit: the cyberpunk plan drops
    buildings in a single sizing pass, and the growth loop places them all;
    a drop that survives a build is an error, not a note."""

    def test_growth_places_what_a_single_pass_drops(self):
        from worldgen.extensions import expand
        data = load_fixture("cyberpunk-glm-floors-plan.json")
        exts = expand({"floors", "region-groups"}
                      | {e for e in data.get("extensions", []) if isinstance(e, str)})
        once = worldgen._build_world(parse_plan(data), data, 1, exts)
        # the map sizes zones from their content (012g), so a single pass
        # places what it once dropped; no zone may be thinner than its content
        self.assertFalse(any(r == "no space in zone" for (_w, r) in once.failures),
                         "a zone thinner than its content slipped through")
        errs = once.metrics["errors"]["dropped"]
        notes = once.metrics["objects"]["unplaced"]
        self.assertFalse(any(e["what"] == u["what"] and e["reason"] == u["reason"]
                             for e in errs for u in notes),
                         "a drop must not also be a note")
        world = worldgen.run(data, seed=1, extensions=("floors", "region-groups"))
        self.assertEqual(len(world.buildings), 11)
        self.assertEqual(world.metrics["errors"]["dropped"], [])

    def test_a_single_pass_places_an_interior_drop(self):
        """A lot that will not pack beside its neighbours used to slip past
        the map's content estimate: the ashvale cottage missed its zone in
        one pass and only the growth loop placed it. Zones are measured by
        laying them out now (012h), so one pass sees the lot and places it,
        at both seeds."""
        data = load_fixture("ashvale-compound.plan.json")
        for seed in (1, 2):
            with self.subTest(seed=seed):
                once = worldgen._build_world(parse_plan(data), data, seed, frozenset())
                self.assertFalse(any(r == "no space in zone" for (_w, r) in once.failures),
                                 "a measured zone dropped a building")
                self.assertEqual(once.metrics["errors"]["dropped"], [])


class TestRealFixturesUnchanged(unittest.TestCase):
    """The four real fixture plans know nothing of the extensions: without
    --ext they build exactly as before, with no floors, portals or arpgMods."""

    def test_no_extension_leaves_no_trace(self):
        for name in REAL_PLANS:
            with self.subTest(name):
                data = load_fixture(name)
                world = worldgen.run(data, seed=1)
                spec = worldgen.build_spec(world, data)
                self.assertNotIn("arpgMods", spec)
                self.assertEqual(world.floors, [])
                self.assertEqual(world.portals, [])
                self.assertFalse(any("(upper floor)" in r.name or "(top floor)" in r.name
                                     for r in world.regions))
                self.assertEqual(world.metrics["reachability"], 1.0)


if __name__ == "__main__":
    unittest.main()
