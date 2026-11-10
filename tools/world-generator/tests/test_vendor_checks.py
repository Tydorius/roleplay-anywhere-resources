"""The vendored validator follows the Scenario Editor's checks for Anywhere RPG 1.0: worldgen/vendor/scenario_checks.py
is an exact copy of tools/scenario-editor/scenario_checks.py, and validate_scenario.py takes its value lists and
1.0 rules from it (floors beside the map, [x, y, side] openings, npcTemplates with homes, the renamed sprites)."""
import os
import unittest

from worldgen.vendor import scenario_checks, validate_scenario

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "..", "worldgen", "vendor", "scenario_checks.py")
EDITOR = os.path.join(HERE, "..", "..", "scenario-editor", "scenario_checks.py")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def scenario(regions, entities=(), **kw):
    scn = {"name": "T", "gridSize": [30, 20], "playerId": "p", "stancesAuthored": True,
           "attributes": {"strength": 5, "dexterity": 5, "intellect": 5, "perception": 4, "charisma": 4},
           "regions": [{"id": "r_yard", "name": "Yard", "position": [0, 0], "size": [30, 20], "openings": []}]
           + list(regions),
           "entities": [{"id": "p", "type": "player", "name": "Hero", "pos": [2, 2], "gender": "female",
                         "animationId": "nurse-woman", "inventory": [], "statusEffects": []}] + list(entities)}
    scn.update(kw)
    return scn


class Vendored(unittest.TestCase):
    def test_copy_matches_the_editor(self):
        if not os.path.isfile(EDITOR):
            self.skipTest("no Scenario Editor beside the generator")
        self.assertEqual(read(VENDOR), read(EDITOR),
                         "copy tools/scenario-editor/scenario_checks.py to worldgen/vendor/ (see vendor/README.md)")

    def test_lists_come_from_the_checks(self):
        self.assertIs(validate_scenario.ANIMATIONS, scenario_checks.ANIMATIONS)
        self.assertIn("nurse-woman", validate_scenario.ANIMATIONS)


class OneZero(unittest.TestCase):
    def test_a_floor_beside_the_map_and_a_sided_door(self):
        house = {"id": "r_house", "name": "House", "wall": "wood", "position": [4, 4], "size": [6, 6],
                 "openings": [[6, 4, "s"]]}
        loft = {"id": "r_loft", "name": "Loft", "wall": "wood", "position": [54, 0], "size": [6, 6], "openings": [],
                "pocket": {"anchor": "r_house", "level": 1}}
        E, _ = validate_scenario.validate(scenario([house, loft]), set())
        self.assertEqual(E, [])

    def test_off_the_map_without_a_floor_and_a_door_off_the_edge(self):
        shed = {"id": "r_shed", "name": "Shed", "wall": "wood", "position": [40, 4], "size": [4, 4],
                "openings": [[41, 5]]}
        E, _ = validate_scenario.validate(scenario([shed]), set())
        self.assertIn("region 'Shed' out of bounds", E)
        self.assertIn("region 'Shed': opening [41, 5] not on its perimeter", E)

    def test_npc_templates_with_homes_and_old_sprite_names(self):
        rat = {"id": "ntpl_rat", "name": "Rat", "animationId": "giant-rat", "stance": "skittish",
               "homes": [{"regionId": "r_yard", "count": 3}, {"regionId": "r_gone", "count": 1}]}
        E, _ = validate_scenario.validate(scenario([], npcTemplates=[rat]), set())
        self.assertEqual(E, ["hostile template 'Rat': home region 'r_gone' does not resolve"])


if __name__ == "__main__":
    unittest.main()
