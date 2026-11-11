"""Roles pick their sprite from Anywhere RPG 1.0's character sheets, so most
people no longer fall back to the casual pair."""
import types
import unittest

from worldgen import spec_writer
from worldgen.vendor import scenario_checks


def person(role, gender="female", kind=None):
    """A minimal person, as tests/test_cast.py builds one for animation_for."""
    extras = {"kind": kind} if kind else {}
    return types.SimpleNamespace(gender=gender,
                                 person=types.SimpleNamespace(role=role, extras=extras))


class OnePointZeroSprites(unittest.TestCase):
    def test_every_id_the_map_can_produce_is_a_1_0_sheet(self):
        for _, base in spec_writer.ANIMATIONS:
            ids = ([base] if base in scenario_checks.ANIMATIONS
                   else [f"{base}-man", f"{base}-woman"])
            for animation in ids:
                self.assertIn(animation, scenario_checks.ANIMATIONS)

    def test_a_town_guard(self):
        for gender, sheet in (("male", "town-guard-man"), ("female", "town-guard-woman")):
            self.assertEqual(spec_writer.animation_for(person("Town Guard", gender)), sheet)

    def test_a_head_nurse(self):
        self.assertEqual(spec_writer.animation_for(person("Head Nurse")), "nurse-woman")

    def test_an_innkeeper(self):
        self.assertEqual(spec_writer.animation_for(person("Innkeeper", gender="male")),
                         "innkeeper-man")

    def test_a_maiden_is_not_a_maid(self):
        self.assertEqual(spec_writer.animation_for(person("Maiden")), "casual-woman")

    def test_an_unknown_role_keeps_the_casual_sheet(self):
        self.assertEqual(spec_writer.animation_for(person("Tidewright", gender="male")),
                         "casual-man")
        self.assertEqual(spec_writer.animation_for(person("Tidewright")), "casual-woman")

    def test_a_child_kind_wins_over_the_role(self):
        self.assertEqual(spec_writer.animation_for(person("deckhand pirate", kind="child")),
                         "child")

    def test_a_gender_beyond_male_takes_the_woman_sheet(self):
        self.assertEqual(spec_writer.animation_for(person("sailor", gender=None)),
                         "sailor-woman")


if __name__ == "__main__":
    unittest.main()
