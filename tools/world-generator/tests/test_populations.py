"""Anywhere RPG 1.0 native populations on a generated world: the game's own
nameless livestock, vermin, crowds and patrols ride the spec by home region
name and ship as npcTemplates (one per kind, its homes resolved to the ids
the build assigned). Livestock graze a pasture-matched region 2-5 strong,
vermin nest 2-3 in the cellars and stores and crows settle the crop plots,
townsfolk cross a market or square of an urban or town zone 3-5 strong and the
town watch walks the main street of a town the cast does not already guard —
nothing spawns where the player starts, the whole world holds twenty
creatures, and the choice is deterministic given the run's seed."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api, populations
from worldgen.model import Plan, Person, Rect, Zone
from worldgen.vendor import scenario_checks
from tests.util import load_plan


def _world(*regions, grid=(48, 48), seed=1):
    """A bare world of just regions, for the chooser."""
    w = worldgen.World()
    w.grid = grid
    w.seed = seed
    for r in regions:
        w.regions.append(r)
        w.regions_by_name[r.name] = r
    return w


def _plan(*zones, setting=None):
    return Plan(name="Test World", zones=list(zones),
                setting=dict(setting or {}))


def _pastures(n=12):
    """A down of n ten-by-ten pastures, each big enough for three stock."""
    world = _world(grid=(48, 48))
    for i in range(n):
        x, y = 2 + (i % 4) * 11, 2 + (i // 4) * 11
        r = worldgen.RegionOut(f"West Pasture {i + 1}", Rect(x, y, 10, 10),
                               "square", parent="Downs")
        world.regions.append(r)
        world.regions_by_name[r.name] = r
    return world, _plan(Zone(name="Downs", kind="pastureland"))


def _crowd_world(kind="town"):
    """A town and its square (or a market kind of zone, when asked)."""
    zone = Zone(name="Corvi", kind=kind)
    quarter = worldgen.RegionOut("Corvi", Rect(0, 0, 40, 40), "zone",
                                 group="Corvi")
    square = worldgen.RegionOut("Corvi Square", Rect(6, 6, 10, 10),
                                "square", parent="Corvi")
    return _world(quarter, square), _plan(zone)


def _patrol_world():
    """A town with a main street and a square."""
    zone = Zone(name="Weffling", kind="town")
    ground = worldgen.RegionOut("Weffling", Rect(0, 0, 40, 40), "zone")
    street = worldgen.RegionOut("Weffling Path", Rect(20, 4, 1, 30), "path",
                                parent="Weffling")
    square = worldgen.RegionOut("Weffling Square", Rect(6, 6, 8, 8), "square",
                                parent="Weffling")
    return _world(ground, street, square), _plan(zone)


def _cellar_world():
    """A village with the inn's cellar under it."""
    zone = Zone(name="Weffling", kind="village")
    ground = worldgen.RegionOut("Weffling", Rect(0, 0, 30, 30), "zone")
    cellar = worldgen.RegionOut("The Green Ox Cellar", Rect(4, 4, 6, 6),
                                "room", parent="Weffling", wall="wood")
    return _world(ground, cellar), _plan(zone)


def _guard():
    """A named watchman standing in the world."""
    from worldgen import CharOut
    return CharOut(Person(name="Bram Hale", role="town guard"), (2, 2),
                   "Weffling Square")


class TestLivestock(unittest.TestCase):
    """Sheep, cows, goats and pigs on the pasture; chickens and ducks in the
    farmyard."""

    def test_a_pasture_gets_one_skittish_livestock_template(self):
        zone = Zone(name="Millfield", kind="farmland")
        field = worldgen.RegionOut("Millfield", Rect(0, 0, 40, 40), "zone")
        pasture = worldgen.RegionOut("Millfield Pasture", Rect(2, 2, 8, 8),
                                     "square", parent="Millfield")
        pops = populations.choose(_world(field, pasture), _plan(zone))
        self.assertEqual(len(pops), 1)
        stock = pops[0]
        self.assertIn(stock["name"], populations.GRAZING_KINDS)
        self.assertEqual(stock["stance"], "skittish")
        self.assertEqual(stock["homes"],
                         [{"region": "Millfield Pasture", "count": 3}])

    def test_the_count_grows_with_the_pastures_area(self):
        zone = Zone(name="Millfield", kind="farmland")
        field = worldgen.RegionOut("Millfield", Rect(0, 0, 48, 48), "zone")
        small = worldgen.RegionOut("Millfield Pasture", Rect(1, 1, 5, 5),
                                   "square", parent="Millfield")
        big = worldgen.RegionOut("Millfield West Pasture", Rect(1, 20, 20, 20),
                                 "square", parent="Millfield")
        pops = populations.choose(_world(field, small, big), _plan(zone))
        homes = {h["region"]: h["count"] for p in pops for h in p["homes"]}
        self.assertEqual(homes["Millfield Pasture"], 2)
        self.assertEqual(homes["Millfield West Pasture"], 5,
                         "a 20x20 pasture holds the most stock")

    def test_a_pasture_kind_zone_grazes_its_whole_ground(self):
        zone = Zone(name="Sheep Downs", kind="pasture")
        ground = worldgen.RegionOut("Sheep Downs", Rect(0, 0, 20, 20), "zone")
        pops = populations.choose(_world(ground), _plan(zone))
        self.assertEqual([h["region"] for p in pops for h in p["homes"]],
                         ["Sheep Downs"])

    def test_a_farmyard_gets_yard_stock(self):
        zone = Zone(name="Harrow Farm", kind="farm")
        field = worldgen.RegionOut("Harrow Farm", Rect(0, 0, 30, 30), "zone")
        yard = worldgen.RegionOut("Harrow Farmyard", Rect(4, 4, 8, 6), "yard",
                                  parent="Harrow Farm")
        pops = populations.choose(_world(field, yard), _plan(zone))
        self.assertEqual(len(pops), 1)
        self.assertIn(pops[0]["name"], populations.YARD_KINDS)
        self.assertEqual(pops[0]["stance"], "skittish")
        self.assertEqual(pops[0]["homes"][0]["region"], "Harrow Farmyard")


class TestVermin(unittest.TestCase):
    """Rats in the cellars and stores, crows on the crop plots."""

    def test_a_cellar_and_a_granary_each_get_rats(self):
        for room in ("The Green Ox Cellar", "Tithe Barn Granary"):
            zone = Zone(name="Weffling", kind="village")
            ground = worldgen.RegionOut("Weffling", Rect(0, 0, 30, 30), "zone")
            nest = worldgen.RegionOut(room, Rect(4, 4, 6, 6), "room",
                                      parent="Weffling", wall="wood")
            pops = populations.choose(_world(ground, nest), _plan(zone))
            self.assertEqual([p["name"] for p in pops], ["Rats"], room)
            self.assertEqual(pops[0]["homes"][0]["region"], room)
            self.assertEqual(pops[0]["stance"], "skittish")

    def test_the_rat_count_follows_the_rooms_size(self):
        zone = Zone(name="Weffling", kind="village")
        field = worldgen.RegionOut("Weffling", Rect(0, 0, 30, 30), "zone")
        tight = worldgen.RegionOut("Smiddy Store", Rect(4, 4, 4, 4), "room",
                                   parent="Weffling", wall="wood")
        roomy = worldgen.RegionOut("Smiddy Storehouse", Rect(4, 12, 6, 6),
                                   "room", parent="Weffling", wall="wood")
        pops = populations.choose(_world(field, tight, roomy), _plan(zone))
        homes = {h["region"]: h["count"] for p in pops for h in p["homes"]}
        self.assertEqual(homes["Smiddy Store"], 2)
        self.assertEqual(homes["Smiddy Storehouse"], 3)

    def test_the_arable_fields_take_crows(self):
        zone = Zone(name="Millfield", kind="farmland")
        ground = worldgen.RegionOut("Millfield", Rect(0, 0, 40, 40), "zone")
        small = worldgen.RegionOut("North Turnip Field", Rect(2, 2, 6, 6),
                                   "field", parent="Millfield")
        big = worldgen.RegionOut("South Wheat Field", Rect(2, 20, 10, 10),
                                 "field", parent="Millfield")
        pops = populations.choose(_world(ground, small, big), _plan(zone))
        self.assertEqual(len(pops), 1)
        self.assertEqual(pops[0]["name"], "Crows")
        self.assertEqual(pops[0]["homes"],
                         [{"region": "North Turnip Field", "count": 2},
                          {"region": "South Wheat Field", "count": 3}])


class TestCrowds(unittest.TestCase):
    """Townsfolk cross the market or square of an urban or town zone — never
    a village green — in a period-fitting sprite."""

    def test_a_town_square_gets_townsfolk(self):
        world, plan = _crowd_world()
        pops = populations.choose(world, plan)
        self.assertEqual(len(pops), 1)
        crowd = pops[0]
        self.assertEqual(crowd["name"], "Townsfolk")
        self.assertEqual(crowd["stance"], "neutral")
        self.assertEqual(crowd["homes"][0]["region"], "Corvi Square")
        self.assertEqual(crowd["homes"][0]["count"], 3,
                         "a 10x10 square carries three")
        self.assertIn(crowd["animationId"], ("peasant-man", "peasant-woman"))

    def test_a_market_kind_zone_draws_its_own_crowd(self):
        zone = Zone(name="Shambles", kind="street market")
        row = worldgen.RegionOut("Shambles", Rect(0, 0, 30, 12), "zone")
        pops = populations.choose(_world(row), _plan(zone))
        self.assertEqual([p["name"] for p in pops], ["Townsfolk"])
        self.assertEqual(pops[0]["homes"], [{"region": "Shambles", "count": 4}])

    def test_a_village_green_gets_no_crowd(self):
        zone = Zone(name="Weffling", kind="village")
        ground = worldgen.RegionOut("Weffling", Rect(0, 0, 30, 30), "zone")
        green = worldgen.RegionOut("Weffling Square", Rect(6, 6, 8, 8),
                                   "square", parent="Weffling")
        self.assertEqual(populations.choose(_world(ground, green), _plan(zone)),
                         [])

    def test_the_crowd_dresses_for_the_setting(self):
        for band, sprite in (("medieval", "peasant"), ("modern", "casual"),
                             ("scifi", "casual")):
            world, plan = _crowd_world()
            plan.setting["band"] = band
            crowd = populations.choose(world, plan)[0]
            self.assertIn(crowd["animationId"],
                          (f"{sprite}-man", f"{sprite}-woman"), band)


class TestPatrols(unittest.TestCase):
    """The town watch walks the main street of a town the cast does not
    already guard."""

    def test_an_unguarded_town_gets_a_crowd_and_a_watch(self):
        world, plan = _patrol_world()
        pops = {p["name"]: p for p in populations.choose(world, plan)}
        self.assertEqual(sorted(pops), ["Town watch", "Townsfolk"])
        watch = pops["Town watch"]
        self.assertEqual(watch["stance"], "neutral")
        self.assertEqual(watch["homes"],
                         [{"region": "Weffling Path", "count": 2}],
                         "the watch walks the main street, not the square")
        self.assertIn(watch["animationId"],
                      ("town-guard-man", "town-guard-woman"))

    def test_a_cast_watchman_means_no_patrol(self):
        world, plan = _patrol_world()
        world.characters.append(_guard())
        pops = populations.choose(world, plan)
        self.assertEqual([p["name"] for p in pops], ["Townsfolk"],
                         "the square keeps its crowd; nobody patrols")

    def test_a_village_gets_no_watch_of_its_own(self):
        zone = Zone(name="Weffling", kind="village")
        ground = worldgen.RegionOut("Weffling", Rect(0, 0, 30, 30), "zone")
        street = worldgen.RegionOut("Weffling Path", Rect(15, 4, 1, 20),
                                    "path", parent="Weffling")
        self.assertEqual(
            populations.choose(_world(ground, street), _plan(zone)), [])


class TestLimits(unittest.TestCase):
    """The start cell, the water, the cap and the seed."""

    def test_no_population_spawns_where_the_player_starts(self):
        world, plan = _pastures(n=1)
        world.player = worldgen.CharOut(Person(name="The Player"), (5, 5),
                                        "West Pasture 1")
        self.assertEqual(populations.choose(world, plan), [],
                         "the only pasture holds the start cell")

    def test_no_population_spawns_on_the_water(self):
        world, plan = _pastures(n=1)
        self.assertEqual(
            populations.choose(world, plan,
                               water={"West Pasture 1": "deep"}), [])

    def test_the_world_holds_at_most_twenty_creatures(self):
        pops = populations.choose(*_pastures())
        self.assertEqual(populations.creature_count(pops), 20)
        for p in pops:
            for h in p["homes"]:
                self.assertGreaterEqual(h["count"], 1,
                                        "a trimmed region keeps at least one")

    def test_the_same_seed_chooses_the_same_populations(self):
        self.assertEqual(populations.choose(*_pastures()),
                         populations.choose(*_pastures()))

    def test_every_sprite_is_one_the_game_knows(self):
        for world, plan in (_pastures(), _crowd_world(), _patrol_world(),
                            _cellar_world()):
            for p in populations.choose(world, plan):
                self.assertIn(p["animationId"], scenario_checks.ANIMATIONS,
                              p["name"])


class TestFixtureWorldPopulations(unittest.TestCase):
    """medieval-glm-plan.json built end to end: the populations ship as the
    game's own npcTemplates with their homes resolved to the built regions'
    ids, the run summary lists them by region, and neither the vendored 1.0
    checker nor the shipped-scenario check reports anything against them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-populations-")
        cls.data = load_plan("medieval-glm-plan.json")
        cls.spec = worldgen.build_spec(worldgen.run(cls.data, seed=1), cls.data)
        cls.lines = []
        cls.summary = api._layout_and_build(cls.data, seed=1, out_dir=cls.tmp,
                                            emit=cls.lines.append)
        path = os.path.join(cls.summary["out"],
                            cls.summary["zip"][:-len(".zip")], "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)
        cls.path = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_the_spec_carries_vermin_only(self):
        pops = self.spec["nativePopulations"]
        self.assertEqual([p["name"] for p in pops], ["Rats", "Crows"],
                         "the village has no market square and no town watch "
                         "of its own (Wat Fell watches)")
        for p in pops:
            self.assertEqual(p["stance"], "skittish")
            self.assertEqual(p["level"], 1)
            self.assertEqual(p["money"], 0)
            self.assertEqual(p["lootPoolIds"], [])
            self.assertIn(p["animationId"], scenario_checks.ANIMATIONS)

    def test_the_populations_ship_as_npc_templates(self):
        by_name = {r["name"]: r for r in self.scn["regions"]}
        built = {t["name"]: t for t in self.scn["npcTemplates"]}
        self.assertEqual(sorted(built),
                         sorted(p["name"] for p in self.spec["nativePopulations"]))
        for p in self.spec["nativePopulations"]:
            t = built[p["name"]]
            self.assertEqual(t["stance"], p["stance"])
            self.assertEqual(t["animationId"], p["animationId"])
            self.assertEqual(t["gender"], p["gender"])
            homes = {h["regionId"]: h["count"] for h in t["homes"]}
            for h in p["homes"]:
                area = by_name[h["region"]]
                self.assertEqual(homes[area["id"]], h["count"])

    def test_the_summary_lists_the_populations_by_region(self):
        pops = self.summary["populations"]
        self.assertEqual(pops["templates"], len(self.spec["nativePopulations"]))
        self.assertEqual(pops["creatures"],
                         populations.creature_count(self.spec["nativePopulations"]))
        listed = {(row["template"], row["region"], row["count"])
                  for row in pops["regions"]}
        wanted = {(p["name"], h["region"], h["count"])
                  for p in self.spec["nativePopulations"] for h in p["homes"]}
        self.assertEqual(listed, wanted)
        blob = "\n".join(self.lines)
        self.assertIn(f"populations: {pops['creatures']} creatures "
                      f"in {len(wanted)} regions "
                      f"({len(self.spec['nativePopulations'])} templates)", blob)
        for p in self.spec["nativePopulations"]:
            self.assertIn(f"\n  - {p['name']}: ", blob)
            for h in p["homes"]:
                self.assertIn(f"{h['region']} x{h['count']}", blob)

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)

    def test_the_shipped_scenario_mods_check_is_clean(self):
        from worldgen import checks as checks_mod
        self.assertEqual(checks_mod.check_scenario_mods(self.path, self.spec),
                         [])

    def test_a_broken_population_spec_reports_itself(self):
        from worldgen import checks as checks_mod
        spec = json.loads(json.dumps(self.spec))
        spec["nativePopulations"][0].update(
            {"animationId": "wraith-pirate",
             "homes": [{"region": "Village Green", "count": 9}]})
        spec["nativePopulations"][1]["homes"] = [{"region": "Atlantis",
                                                  "count": 9}]
        issues = checks_mod.check_scenario_mods(self.path, spec)
        self.assertTrue(any("Atlantis" in i for i in issues), issues)
        self.assertTrue(any("unknown sprite" in i for i in issues), issues)
        self.assertTrue(any("lost its home" in i for i in issues), issues)


if __name__ == "__main__":
    unittest.main()
