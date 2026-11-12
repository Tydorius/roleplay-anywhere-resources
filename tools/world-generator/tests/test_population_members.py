"""Anywhere RPG 1.0 native populations start with their members in place: the
spec carries each member's start cell by home region name, and the finished
scenario ships one npc entity per member — its templateId naming the built
npcTemplate, its npcHome naming the home region — so a generated world opens
with its livestock, vermin, crowds and patrols already there. Each home holds
its full count on cells no object covers, no two members share a cell and none
stands on a character's start; the vendored 1.0 checker and the
shipped-scenario check report nothing against them, and a broken spec (a
member whose npcHome is not a home of its template) is reported."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api, populations
from worldgen.vendor import scenario_checks
from tests.util import load_plan


def _inside(area, pos):
    x, y = area.get("position", (0, 0))
    w, h = area.get("size", (0, 0))
    return x <= pos[0] < x + w and y <= pos[1] < y + h


class TestPopulationMembers(unittest.TestCase):
    """medieval-glm-plan.json built end to end: every home starts holding its
    full count of members, in place and on free cells inside the home
    region."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-population-members-")
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

    def _members(self):
        """The scenario's population members: npc entities off a template."""
        return [e for e in self.scn["entities"]
                if e.get("type") == "npc" and e.get("templateId")]

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_each_home_holds_its_count_in_place(self):
        by_name = {r["name"]: r for r in self.scn["regions"]}
        tpl_by_name = {t["name"]: t for t in self.scn["npcTemplates"]}
        members = self._members()
        self.assertEqual(len(members),
                         populations.creature_count(
                             self.spec["nativePopulations"]),
                         "every creature of every home starts in place")
        for p in self.spec["nativePopulations"]:
            t = tpl_by_name[p["name"]]
            for h in p["homes"]:
                area = by_name[h["region"]]
                here = [e for e in members if e["templateId"] == t["id"]
                        and e["npcHome"] == area["id"]]
                self.assertEqual(len(here), h["count"],
                                 f"{p['name']} in {h['region']}")
                self.assertEqual(sorted(tuple(e["pos"]) for e in here),
                                 sorted(tuple(c) for c in h["members"]),
                                 "the members stand where the spec placed them")
                for e in here:
                    self.assertTrue(_inside(area, e["pos"]),
                                    f"{e['name']} at {e['pos']}")

    def test_members_stand_on_cells_no_object_covers(self):
        tpl = {t["id"]: t for t in self.scn["objectTemplates"]}
        covered = set()
        for e in self.scn["entities"]:
            if e.get("type") == "object":
                covered |= set(scenario_checks.footprint(e, tpl))
        for e in self._members():
            self.assertNotIn(tuple(e["pos"]), covered, e["name"])

    def test_no_two_members_share_a_cell_or_a_character_start(self):
        cells = [tuple(e["pos"]) for e in self._members()]
        self.assertEqual(len(cells), len(set(cells)))
        starts = {tuple(e["pos"]) for e in self.scn["entities"]
                  if e.get("type") in ("npc", "player")
                  and not e.get("templateId")}
        self.assertFalse(set(cells) & starts)

    def test_members_carry_their_template(self):
        tpl_by_id = {t["id"]: t for t in self.scn["npcTemplates"]}
        homes_of = {t["id"]: {h["regionId"] for h in t["homes"]}
                    for t in self.scn["npcTemplates"]}
        names_of = {}
        for e in self._members():
            t = tpl_by_id[e["templateId"]]
            self.assertIn(e["npcHome"], homes_of[e["templateId"]], e["name"])
            self.assertEqual(e["description"], t["description"])
            self.assertEqual(e["physicalDescription"],
                             t["physicalDescription"])
            self.assertEqual(e["gender"], t["gender"])
            self.assertEqual(e["stance"], t["stance"])
            self.assertEqual(e["animationId"], t["animationId"])
            self.assertEqual(e["level"], t["level"])
            self.assertEqual(e["size"], [1, 1])
            self.assertEqual(e["hp"], 100)
            self.assertEqual(e["maxHp"], 100)
            self.assertEqual(e["inventory"], [])
            self.assertEqual(e["statusEffects"], [])
            names_of.setdefault(t["name"], []).append(e["name"])
        for name, names in names_of.items():
            self.assertEqual(set(names),
                             {f"{name} {i}" for i in range(1, len(names) + 1)},
                             "numbered per template across the world")

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)

    def test_the_shipped_scenario_mods_check_is_clean(self):
        from worldgen import checks as checks_mod
        self.assertEqual(checks_mod.check_scenario_mods(self.path, self.spec),
                         [])

    def test_the_run_summary_counts_the_placed_members(self):
        placed = populations.placed_count(self.spec["nativePopulations"])
        self.assertEqual(self.summary["populations"]["placed"], placed)
        blob = "\n".join(self.lines)
        self.assertIn(f", {placed} placed at the start", blob)

    def test_a_broken_member_spec_reports_itself(self):
        from worldgen import checks as checks_mod
        spec = json.loads(json.dumps(self.spec))
        home = next(h for p in spec["nativePopulations"] for h in p["homes"]
                    if h.get("members"))
        home["region"] = "Village Green"   # a region that is no home of its own
        issues = checks_mod.check_scenario_mods(self.path, spec)
        self.assertTrue(any("member" in i for i in issues), issues)
        self.assertTrue(any("Village Green" in i for i in issues), issues)


if __name__ == "__main__":
    unittest.main()
