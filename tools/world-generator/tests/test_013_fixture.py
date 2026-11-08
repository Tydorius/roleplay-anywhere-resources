"""Brief 013 change 7: the framed fixtures. Ashvale with a frame, a real
population and all five systems builds and validates with 0 errors; the
cyberpunk district carries a scrip economy with a countdown; and plans from
before the frame still re-roll and build."""
import json
import os
import shutil
import tempfile
import unittest

from tests.test_013_frame import a_frame
from tests.test_model import ScriptedClient, canned_replies
from worldgen import api

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def scenario_of(summary):
    path = os.path.join(summary["out"], summary["zip"][:-len(".zip")], "scenario.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


class MockedRunsPerMode(unittest.TestCase):
    """A mocked run in each mode builds a scenario with every system filled
    in, and the default population of 20-40 is asked for, kept and reached
    (the canned batch is topped up to twenty by three scripted batches)."""

    @staticmethod
    def _replies():
        from tests.test_model import CANNED_P5
        base = [_dump(a_frame())] + canned_replies()
        topups = []
        for n in range(3):
            people = [dict(p, name=f"{p['name'].split()[0]} {chr(66 + n)}{i}")
                      for i, p in enumerate(CANNED_P5["npcs"])]
            topups.append(_dump({"npcs": people}))
        # the zone batch is base[8]; the top-ups run after it, before the player
        return base[:9] + topups + base[9:]

    def test_each_mode_fills_the_five_systems(self):
        for mode in ("quick", "short", "medium", "long"):
            with self.subTest(mode), tempfile.TemporaryDirectory() as tmp:
                client = ScriptedClient(self._replies())
                # the canned P3 replies are the old method's
                s = api.generate("a mill village", client=client, seed=1, cast=False,
                                 out_dir=tmp, library=False,
                                 questionnaire={"mode": mode, "answers": {},
                                                "population": [20, 40]})
                self.assertTrue(s["ok"], s)
                self.assertEqual(s["validator_errors"], 0, s)
                self.assertEqual(s["npcs"], 20, "topped up to the range floor")
                scn = scenario_of(s)
                for key in ("narrativeRules", "variables", "perkTrees",
                            "calendar", "quests", "skills"):
                    self.assertTrue(scn[key], f"{key} empty in {mode}")
                with open(os.path.join(s["out"], "plan.json"), encoding="utf-8") as f:
                    plan = json.load(f)
                self.assertEqual(plan["questionnaire"]["population"], [20, 40])
                self.assertEqual(plan["frame"]["genre"]["primary"], "Fantasy",
                                 "inline P0 framed the idea")


class FramedBuilds(unittest.TestCase):
    """Each framed fixture is built once through the vendored builder and
    validator, then asserted on in full."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-013-")
        cls.summaries = {}
        for name in ("ashvale-framed.plan.json", "cyberpunk-framed.plan.json"):
            cls.summaries[name] = api._layout_and_build(
                load(name), seed=1, out_dir=os.path.join(cls.tmp, name.split(".")[0]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_both_fixtures_build_with_zero_errors(self):
        for name, s in self.summaries.items():
            with self.subTest(name):
                self.assertTrue(s["ok"], s)
                self.assertEqual(s["validator_errors"], 0, s)
                self.assertEqual(s["reachability"], 1.0, s)

    def test_ashvale_carries_all_five_systems(self):
        s = self.summaries["ashvale-framed.plan.json"]
        scn = scenario_of(s)
        self.assertEqual(len(scn["variables"]), 5)
        self.assertEqual(len(scn["perkTrees"]), 3)
        self.assertEqual(len(scn["calendar"]), 6)
        self.assertEqual(len(scn["quests"]), 2)
        self.assertTrue(scn["skills"])
        self.assertTrue(scn["narrativeRules"])
        self.assertEqual(scn["currency"]["name"], "Silver bit")
        self.assertEqual(sum(scn["attributes"].values()), 25)
        self.assertEqual(scn["narrativeFlavor"], "peaceful")
        self.assertEqual(scn["difficulty"], "casual")

    def test_ashvale_holds_the_population_it_asked_for(self):
        plan = load("ashvale-framed.plan.json")
        lo, hi = plan["questionnaire"]["population"]
        s = self.summaries["ashvale-framed.plan.json"]
        self.assertEqual(s["npcs"], len(plan["npcs"]), "everyone was placed")
        self.assertTrue(lo <= s["npcs"] + 1 <= hi,
                        f"{s['npcs']} npcs + the player sit outside {lo}-{hi}")

    def test_the_calendar_and_quests_name_real_places(self):
        s = self.summaries["ashvale-framed.plan.json"]
        scn = scenario_of(s)
        regions = {r["name"] for r in scn["regions"]}
        for entry in scn["calendar"]:
            self.assertIn(entry["location"], regions, entry)
        plan = load("ashvale-framed.plan.json")
        people = {p["name"] for p in plan["npcs"]} | {plan["player"]["name"]}
        for q in scn["quests"]:
            text = json.dumps(q)
            self.assertTrue(any(n.split()[0] in text for n in people),
                            f"quest {q['title']!r} names nobody real")

    def test_cyberpunk_pays_in_scrip_and_counts_down(self):
        s = self.summaries["cyberpunk-framed.plan.json"]
        scn = scenario_of(s)
        cur = scn["currency"]
        self.assertEqual(cur["name"], "Corp scrip")
        self.assertNotIn("penny", cur["name"].lower())
        self.assertNotIn("coin", cur["name"].lower())
        self.assertTrue(any(c.isdigit() for c in cur["format"]), cur)
        clocks = [v for v in scn["variables"] if v["name"] == "Repossession clock"]
        self.assertEqual(len(clocks), 1)
        clock = clocks[0]
        self.assertEqual(clock["ratePerHour"], -1, "the deadline ticks down")
        self.assertEqual(clock["initial"], clock["max"], "it starts at the top")
        self.assertEqual(sum(scn["attributes"].values()), 25)
        for key in ("variables", "perkTrees", "calendar", "quests", "skills"):
            self.assertIn(key, scn)


class OldPlansStillReroll(unittest.TestCase):
    """Plans from before the frame carry none of it, and still re-roll."""

    def test_village_and_the_glm_plans_re_roll_without_a_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("village.json", "cyberpunk-glm-plan.json",
                         "medieval-glm-plan.json"):
                with self.subTest(name):
                    summary = api.relayout(os.path.join(FIXTURES, name), seed=2,
                                           out_dir=os.path.join(tmp, name))
                    self.assertTrue(summary["ok"], summary)
                    self.assertEqual(summary["validator_errors"], 0, summary)
                    self.assertEqual(summary["reachability"], 1.0, summary)

    def test_a_framed_plan_re_rolls_with_its_frame_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.relayout(os.path.join(FIXTURES, "ashvale-framed.plan.json"),
                                   seed=3, out_dir=os.path.join(tmp, "again"))
            self.assertTrue(summary["ok"], summary)
            self.assertEqual(summary["npcs"], 24, summary)
            scenario = scenario_of(summary)
            self.assertEqual(len(scenario["calendar"]), 6, "every entry kept")

    def test_calendar_entries_at_dropped_buildings_go_with_them(self):
        """A calendar entry whose location never made it onto the map is
        dropped and reported, and the calendar never points at a missing
        region (the builder would refuse the whole scenario otherwise).
        The plan copy points "Harvest supper" at a building that is not on
        the map, so the test no longer depends on a seed squeezing one out
        (it once relied on seed 2 dropping the inn; the 012h map growth
        made room for it)."""
        with open(os.path.join(FIXTURES, "ashvale-framed.plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
        cal = plan["calendar"] if "calendar" in plan else plan["systems"]["calendar"]
        supper = next(c for c in cal if c["name"] == "Harvest supper")
        supper["location"] = "The Burnt Mill"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(plan, f)
            summary = api.relayout(path, seed=1, out_dir=os.path.join(tmp, "out"))
            self.assertFalse(summary["ok"], "the dropped entry still fails it")
            self.assertTrue(summary["zip"], "but the scenario itself builds")
            self.assertEqual(summary["validator_errors"], 0, summary)
            scenario = scenario_of(summary)
            names = [c["name"] for c in scenario["calendar"]]
            self.assertNotIn("Harvest supper", names)
            self.assertEqual(len(names), 5)
            regions = {r["name"] for r in scenario["regions"]}
            for entry in scenario["calendar"]:
                self.assertIn(entry["location"], regions, entry)


if __name__ == "__main__":
    unittest.main()
