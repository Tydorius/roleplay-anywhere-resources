"""Review fix on top of the no-stairs-to-nowhere rule: a building ruined only
by its status ("abandoned", no ruin word in any name) keeps its stair, and the
shipped-scenario check accepts that stair, because the spec names it, instead
of failing the world the rule itself kept it in. A home's stair is still
reported."""
import json
import os
import tempfile
import unittest

import worldgen
from worldgen import checks as checks_mod
from tests.test_stairs_to_nowhere import _stair_scenario, small_plan


def _issues(scenario, spec):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "scenario.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(scenario, f)
        return [i for i in checks_mod.check_scenario_mods(path, spec)
                if "leads nowhere" in i]


class TestAbandonedStairIsNamedInTheSpec(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.specs = {}
        for status in ("home", "abandoned"):
            data = small_plan(status)
            cls.specs[status] = worldgen.build_spec(worldgen.run(data, seed=1), data)

    def test_the_abandoned_buildings_stair_is_named(self):
        self.assertEqual(self.specs["abandoned"]["nativeStairs"],
                         {"ruined": ["Staircase 1"]},
                         "the builder numbers it Staircase 1")

    def test_a_home_names_none(self):
        self.assertEqual(self.specs["home"]["nativeStairs"], {"ruined": []})


class TestTheNetReadsTheSpec(unittest.TestCase):

    def test_a_named_ruin_stair_in_a_plain_room_passes(self):
        scn = _stair_scenario("The Old Watch House Hall", "the cold hall")
        self.assertEqual(_issues(scn, {"nativeStairs": {"ruined": ["Staircase 1"]}}), [])

    def test_the_same_stair_unnamed_is_reported(self):
        scn = _stair_scenario("The Old Watch House Hall", "the cold hall")
        self.assertEqual(len(_issues(scn, {"nativeStairs": {"ruined": []}})), 1)
        self.assertEqual(len(_issues(scn, {})), 1)


if __name__ == "__main__":
    unittest.main()
