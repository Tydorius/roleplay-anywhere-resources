"""Brief 013 change 4: phase P6, the systems - rules and economy, perk
trees, and the story clock - validated against the guide's formats, written
by the spec writer, and falling back part by part when a call dies. All
mocked."""
import json
import os
import tempfile
import unittest

from tests.test_model import (CANNED_COTTAGE, CANNED_MILL, CANNED_P1,
                              CANNED_P4_FIELDS, CANNED_P4_VILLAGE,
                              CANNED_P5_BATCH, CANNED_P5_PLAYER,
                              CANNED_P6A, CANNED_P6B, CANNED_P6C,
                              CANNED_TEMPLATES, ScriptedClient)
from worldgen import phases
from worldgen.phases import (check_p6a, check_p6b, check_p6c, sanitize_p6a,
                             sanitize_p6b, sanitize_p6c)


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


def systems_replies(p6a=None, p6b=None, p6c=None):
    """A canned run whose P6 replies can be swapped."""
    return [
        _dump(CANNED_P1),
        _dump({"templates": CANNED_TEMPLATES}),
        _dump(CANNED_MILL),
        _dump(CANNED_COTTAGE),
        _dump(CANNED_P4_VILLAGE),
        _dump(CANNED_P4_FIELDS),
        _dump(CANNED_P5_BATCH),
        _dump(CANNED_P5_PLAYER),
        _dump(p6a if p6a is not None else CANNED_P6A),
        _dump(p6b if p6b is not None else CANNED_P6B),
        _dump(p6c if p6c is not None else CANNED_P6C),
    ]


class TestCheckP6a(unittest.TestCase):
    def test_the_canned_rules_pass(self):
        self.assertEqual(check_p6a(CANNED_P6A), [])

    def test_attributes_must_sum_to_25(self):
        d = json.loads(json.dumps(CANNED_P6A))
        d["attributes"]["strength"] = 7
        self.assertTrue(any("sum to 25" in e for e in check_p6a(d)), check_p6a(d))
        d["attributes"] = {"strength": 5}
        self.assertTrue(any("exactly the five" in e for e in check_p6a(d)))

    def test_the_currency_format_needs_a_digit(self):
        d = json.loads(json.dumps(CANNED_P6A))
        d["currency"]["format"] = "pennies"
        self.assertTrue(any("format" in e for e in check_p6a(d)))

    def test_weather_outside_the_list_is_an_error(self):
        d = json.loads(json.dumps(CANNED_P6A))
        d["weatherKinds"] = ["clear", "acid"]
        self.assertTrue(any("weatherKinds" in e for e in check_p6a(d)))

    def test_variables_need_sane_ranges(self):
        d = json.loads(json.dumps(CANNED_P6A))
        d["variables"][0]["initial"] = 99
        self.assertTrue(any("initial must sit inside" in e for e in check_p6a(d)))
        d["variables"] = d["variables"][:2]
        self.assertTrue(any("4-8" in e for e in check_p6a(d)))

    def test_sanitize_fixes_a_broken_spread_and_caps_skills(self):
        d = json.loads(json.dumps(CANNED_P6A))
        d["attributes"] = {"strength": 9, "dexterity": 4, "intellect": 4,
                           "perception": 4, "charisma": 3}
        d["skills"]["Bad skill"] = 7
        d["weatherKinds"] = ["clear", "hail"]
        log = []
        out = sanitize_p6a(d, log)
        self.assertEqual(sum(out["attributes"].values()), 25)
        self.assertNotIn("Bad skill", out["skills"], "level 7 is not a level")
        self.assertEqual(out["weatherKinds"], ["clear"])
        self.assertTrue(any("attributes" in w + r for w, r in log), log)


class TestCheckP6b(unittest.TestCase):
    def test_the_canned_trees_pass(self):
        self.assertEqual(check_p6b(CANNED_P6B), [])

    def test_wrong_tree_count_and_size_are_errors(self):
        d = {"perkTrees": CANNED_P6B["perkTrees"][:2]}
        self.assertEqual(len(check_p6b(d)), 1)
        d = json.loads(json.dumps(CANNED_P6B))
        d["perkTrees"][0]["root"]["children"] = \
            d["perkTrees"][0]["root"]["children"][:1]   # 2 perks
        self.assertTrue(any("5-8 perks" in e for e in check_p6b(d)))

    def test_depth_over_five_is_an_error(self):
        def nest(n):
            return _nest(n)
        def _nest(n):
            return {"name": f"L{n}", "type": "passive", "description": "d",
                    "physicalDescription": "p",
                    "children": [_nest(n - 1)] if n else []}
        d = json.loads(json.dumps(CANNED_P6B))
        d["perkTrees"][0]["root"]["children"][0]["children"] = [
            nest(5)]   # root(1) child(2) nest(3..8) - too deep
        self.assertTrue(any("stop 5 levels" in e for e in check_p6b(d)),
                        check_p6b(d))

    def test_sanitize_drops_deep_children_and_keeps_three_trees(self):
        # a chain six levels below the root: the sixth is dropped
        def chain(n):
            return {"name": f"C{n}", "type": "passive", "description": "d",
                    "physicalDescription": "p",
                    "children": [chain(n + 1)] if n < 6 else []}
        d = json.loads(json.dumps(CANNED_P6B))
        d["perkTrees"][0]["root"]["children"][0]["children"] = [chain(3)]
        log = []
        out = sanitize_p6b(d, log)
        self.assertEqual(len(out["perkTrees"]), 3)
        self.assertTrue(any("below level 5" in r for _w, r in log), log)

    def test_fewer_than_three_trees_means_none(self):
        d = {"perkTrees": CANNED_P6B["perkTrees"][:1]}
        log = []
        self.assertEqual(sanitize_p6b(d, log), {})
        self.assertTrue(log)


class TestCheckP6c(unittest.TestCase):
    REGIONS = {"Millbrook", "Wheatfields", "The Old Mill", "Miller's Cottage"}
    PEOPLE = {"Aldous Miller", "Berta Miller", "Edda Straw", "Wren Ash"}

    def test_the_canned_clock_passes(self):
        self.assertEqual(check_p6c(CANNED_P6C, self.REGIONS, self.PEOPLE), [])

    def test_unknown_regions_are_errors(self):
        d = json.loads(json.dumps(CANNED_P6C))
        d["calendar"][0]["location"] = "The Moon"
        self.assertTrue(any("not a region" in e for e in
                            check_p6c(d, self.REGIONS, self.PEOPLE)))

    def test_a_quest_naming_nobody_real_is_an_error(self):
        d = json.loads(json.dumps(CANNED_P6C))
        d["quests"] = [{"title": "The Sealed Letter", "objectives": [
            {"text": "Follow the courier to the old bridge",
             "prerequisites": [{"text": "Buy a lantern from the pedlar",
                                "primary": True}]}]}]
        self.assertTrue(any("name a real place or person" in e
                            for e in check_p6c(d, self.REGIONS, self.PEOPLE)),
                        check_p6c(d, self.REGIONS, self.PEOPLE))
        # the given name alone is enough (the steps speak of people plainly)
        d["quests"][0]["objectives"][0]["prerequisites"][0]["text"] = \
            "Buy a lantern from Edda"
        self.assertFalse(any("name a real place or person" in e
                             for e in check_p6c(d, self.REGIONS, self.PEOPLE)))
        # and a real region counts too
        d["quests"][0]["objectives"][0]["text"] = "Meet at The Old Mill"
        d["quests"][0]["objectives"][0]["prerequisites"] = []
        self.assertFalse(any("name a real place or person" in e
                             for e in check_p6c(d, self.REGIONS, self.PEOPLE)))

    def test_the_week_and_one_offs_are_checked(self):
        d = json.loads(json.dumps(CANNED_P6C))
        d["calendar"][2]["recurrence"] = "daily"   # only one one-off left
        self.assertTrue(any("one-off" in e for e in
                            check_p6c(d, self.REGIONS, self.PEOPLE)))
        d["calendar"][2]["day"] = 30
        self.assertTrue(any("day" in e for e in
                            check_p6c(d, self.REGIONS, self.PEOPLE)))

    def test_sanitize_drops_unknown_locations_and_bad_times(self):
        d = json.loads(json.dumps(CANNED_P6C))
        d["calendar"][0]["location"] = "Nowhere"
        d["calendar"][1]["start"] = "breakfast"
        log = []
        out = sanitize_p6c(d, log, self.REGIONS, self.PEOPLE)
        names = [c["name"] for c in out["calendar"]]
        self.assertNotIn("Morning sacking", names)
        self.assertEqual(out["calendar"][0]["start"], "08:00")
        self.assertTrue(any("not a region" in r for _w, r in log), log)

    def test_sanitize_drops_a_quest_naming_nobody_real(self):
        d = json.loads(json.dumps(CANNED_P6C))
        d["quests"] = [{"title": "The Sealed Letter", "objectives": [
            {"text": "Follow the courier to the old bridge",
             "prerequisites": [{"text": "Buy a lantern from the pedlar",
                                "primary": True}]}]}]
        log = []
        out = sanitize_p6c(d, log, self.REGIONS, self.PEOPLE)
        self.assertNotIn("quests", out)
        self.assertTrue(any("name no real place or person" in r
                            for _w, r in log), log)


class TestP6Runs(unittest.TestCase):
    def test_the_systems_land_on_the_plan(self):
        client = ScriptedClient(systems_replies())
        plan, stats = phases.run_phases("a mill village", client)
        self.assertEqual(client.calls, 11)
        self.assertEqual(stats["dropped"], [])
        self.assertEqual(plan["currency"]["name"], "Copper penny")
        self.assertEqual(sum(plan["attributes"].values()), 25)
        self.assertEqual(len(plan["skills"]), 14)
        self.assertEqual(len(plan["variables"]), 4)
        self.assertEqual(len(plan["perkTrees"]), 3)
        self.assertEqual(len(plan["calendar"]), 4)
        self.assertEqual(plan["quests"][0]["title"], "The Wheel and the Water")
        self.assertEqual(plan["weatherKinds"], ["clear", "rain", "fog", "thunderstorm"])

    def test_a_dead_call_falls_back_for_that_part_only(self):
        replies = systems_replies(p6b="garbage", p6c="also garbage")
        client = ScriptedClient(replies)
        plan, stats = phases.run_phases("a mill village", client)
        self.assertEqual(plan["currency"]["name"], "Copper penny", "6a survived")
        self.assertNotIn("perkTrees", plan)
        self.assertNotIn("calendar", plan)
        self.assertNotIn("quests", plan)
        self.assertTrue(any("perk trees fell back" in r for _w, r in stats["dropped"]))
        self.assertTrue(any("calendar and quests fell back" in r
                            for _w, r in stats["dropped"]))

    def test_time_pressure_reaches_the_6a_prompt(self):
        client = ScriptedClient(systems_replies())
        phases.run_phases("a mill village", client,
                          frame={"premise": "p", "tone": "t", "playerRole": "r",
                                 "conflict": "c", "constraints": []},
                          questionnaire={"mode": "short", "answers": {
                              "time": {"choices": ["A hard deadline in days"]}},
                              "population": [5, 6]})
        p6a_prompt = client.sent[-3][1]["content"]
        self.assertIn("TIME PRESSURE", p6a_prompt)
        self.assertIn("countdown", p6a_prompt)

    def test_the_spec_writes_all_five_systems(self):
        client = ScriptedClient(systems_replies())
        plan, _stats = phases.run_phases("a mill village", client)
        with tempfile.TemporaryDirectory() as tmp:
            phases.write_plan(plan, os.path.join(tmp, "plan.json"))
            import worldgen
            world = worldgen.run(plan, seed=1)
            spec = worldgen.build_spec(world, plan)
        for key in ("variables", "perkTrees", "calendar", "quests", "skills"):
            self.assertIn(key, spec)
        self.assertEqual(len(spec["perkTrees"]), 3)
        self.assertEqual(len(spec["calendar"]), 4)
        self.assertEqual(spec["variables"][0]["name"], "Supplies")

    def test_old_plans_fall_back_genre_neutral(self):
        """A plan without P6 output keeps building, with the fixed defaults."""
        import worldgen
        with open(os.path.join(os.path.dirname(__file__), "..", "fixtures",
                               "village.json"), encoding="utf-8") as f:
            plan = json.load(f)
        for key in ("currency", "attributes", "skills", "narrativeRules"):
            plan.pop(key, None)      # a plan from before P6 carried none of it
        world = worldgen.run(plan, seed=1)
        spec = worldgen.build_spec(world, plan)
        self.assertEqual(spec["currency"]["name"], "Coin")
        self.assertTrue(any(c.isdigit() for c in spec["currency"]["format"]))
        self.assertEqual(sum(spec["attributes"].values()), 25)
        self.assertEqual(spec["variables"], [])
        self.assertEqual(spec["perkTrees"], [])
        self.assertEqual(spec["calendar"], [])
        self.assertEqual(spec["quests"], [])


if __name__ == "__main__":
    unittest.main()
