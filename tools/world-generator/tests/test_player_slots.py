"""Player equipment uses the game's slot names. Found by the first live 013
run: the P5 prompt's example said "weapon", the model followed it, and the
validator refused the scenario (equipment slot 'weapon')."""
import unittest

from worldgen import phases


class TestPlayerSlots(unittest.TestCase):
    ITEMS = {"Sword": {}, "Tunic": {}, "Buckler": {}, "Knife": {}}

    def _clean(self, equipment, inventory=None):
        log = []
        player = {"equipment": dict(equipment), "inventory": list(inventory or [])}
        phases._sanitize_player_items(player, log, self.ITEMS)
        return player, log

    def test_alias_maps_to_a_game_slot(self):
        p, log = self._clean({"weapon": "Sword", "chest": "Tunic"})
        self.assertEqual(p["equipment"], {"wieldable1": "Sword", "torso": "Tunic"})
        self.assertTrue(any("'weapon' -> 'wieldable1'" in m for _, m in log))

    def test_unknown_or_taken_slot_moves_the_item_to_the_inventory(self):
        p, _ = self._clean({"wieldable1": "Sword", "weapon": "Knife", "tail": "Buckler"})
        self.assertEqual(p["equipment"], {"wieldable1": "Sword"})
        self.assertIn(["Knife", 1], p["inventory"])
        self.assertIn(["Buckler", 1], p["inventory"])

    def test_check_flags_a_slot_the_game_lacks(self):
        errs = phases._player_item_errors(
            {"equipment": {"tail": "Sword", "torso": "Tunic"}}, "player", self.ITEMS)
        self.assertTrue(any("not a game slot" in e for e in errs))
        ok = phases._player_item_errors(
            {"equipment": {"weapon": "Sword", "torso": "Tunic"}}, "player", self.ITEMS)
        self.assertEqual(ok, [])

    def test_prompt_lists_the_real_slots(self):
        import os
        path = os.path.join(phases.PROMPTS_DIR, "p5-player.txt")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("wieldable1", text)
        self.assertNotIn('"weapon"', text)


if __name__ == "__main__":
    unittest.main()
