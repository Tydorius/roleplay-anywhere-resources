"""Review fix on top of the turned footprints: upper-storey furniture ships
with the quarter turn its room layout gave it, as ground-floor furniture
always has. Before, every upstairs piece shipped unturned, on cells the
layout never checked. Only templates with a `back` edge turn, and no fixture
furnishes an upper storey with one, so the test builds its own: a counter
against the loft's east wall."""
import unittest

import worldgen
from tests.test_stairs_to_nowhere import small_plan


def _loft_plan():
    d = small_plan("home")
    d["extensions"] = ["floors"]
    d["templates"].append({
        "name": "Shop counter", "size": [3, 1], "walkability": 0,
        "tags": ["counter"], "back": "north", "description": "A counter.",
        "physicalDescription": "a long counter", "rule": "against a wall"})
    d["zones"][0]["buildings"][0]["storeys"] = 2
    b = d["buildings"][0]
    b["stairs"] = {"room": "Hall"}
    b["upper"] = [{"storey": 2,
                   "rooms": [{"name": "Loft", "share": "large", "purpose": "the loft"}],
                   "connections": [],
                   "furniture": [{"template": "Shop counter", "room": "Loft",
                                  "count": 1, "hint": "wall:east"}]}]
    return d


class TestUpstairsFurnitureKeepsItsTurn(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(_loft_plan(), seed=1)

    def _counter(self):
        for b in self.world.buildings:
            for f in getattr(b, "floors", []) or []:
                for room in f.layout.rooms:
                    for (t, pos) in room.furniture.placements:
                        if t == "Shop counter":
                            shipped = [o for o in self.world.objects
                                       if o.template == t and tuple(o.pos) == tuple(pos)]
                            return room.furniture.rot(t, pos), shipped
        return None, []

    def test_the_loft_counter_is_turned_by_its_layout(self):
        rot, shipped = self._counter()
        self.assertEqual(len(shipped), 1, "the counter is placed upstairs")
        self.assertTrue(rot % 4, "against an east wall a north-backed counter turns")

    def test_it_ships_with_that_turn(self):
        rot, shipped = self._counter()
        self.assertEqual(shipped[0].rot % 4, rot % 4)


if __name__ == "__main__":
    unittest.main()
