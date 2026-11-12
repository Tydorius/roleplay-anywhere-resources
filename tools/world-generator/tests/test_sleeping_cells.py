"""A "cell" in a chapel, temple or monastery is a monk's or keeper's bedroom,
not a jail. The model test locked a "Chapel Keeper's cell" in two castles
(the keeper held the key, so nothing broke, but it was wrong). When "cell" is
the room's only lock word and the room or its building reads as religious,
the room stays unlocked. A jail cell, or a cell called a lock-up, still locks,
wherever it is."""
import copy
import unittest

import worldgen
from tests.test_locks_theft import WATCH_HOUSE_PLAN


def _locked(plan):
    spec = worldgen.build_spec(worldgen.run(plan, seed=1), plan)
    return [e["room"] for e in spec["nativeLocks"]["locks"]]


def _variant(building_purpose, cell_purpose):
    plan = copy.deepcopy(WATCH_HOUSE_PLAN)
    for z in plan["zones"]:
        for b in z["buildings"]:
            if b["name"] == "Weffling Watch House":
                b["purpose"] = building_purpose
    for b in plan["buildings"]:
        if b["name"] == "Weffling Watch House":
            for r in b["rooms"]:
                if r["name"] == "Cell":
                    r["purpose"] = cell_purpose
    return plan


class TestSleepingCells(unittest.TestCase):

    def test_the_watch_houses_jail_cell_still_locks(self):
        self.assertIn("Weffling Watch House Cell", _locked(WATCH_HOUSE_PLAN))

    def test_a_chapel_keepers_sleeping_cell_does_not(self):
        plan = _variant("the village chapel", "the keeper's sleeping cell")
        self.assertNotIn("Weffling Watch House Cell", _locked(plan))

    def test_a_lock_up_in_a_chapel_still_locks(self):
        plan = _variant("the village chapel", "the lock-up")
        self.assertIn("Weffling Watch House Cell", _locked(plan))


if __name__ == "__main__":
    unittest.main()
