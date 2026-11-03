"""Two buildings stamping units of the same name each put their own name in
front, so the builder never sees two "Apartment 1" regions. Found by the
live zombie-town run: Cedar Walk-Up and Dogwood Walk-Up both had units
named "Apartment", and the build failed on 46 misplaced pieces."""
import copy
import unittest

from tests import util
from worldgen import model


def _two_blocks():
    data = util.load_plan("apartment-block.plan.json")
    zone = next(z for z in data["zones"]
                if any(b.get("units") for b in z["buildings"]))
    src = next(b for b in zone["buildings"] if b.get("units"))
    twin = copy.deepcopy(src)
    twin["name"] = "Second Flats"
    zone["buildings"].append(twin)
    design = copy.deepcopy(next(g for g in data["buildings"] if g["name"] == src["name"]))
    design["name"] = "Second Flats"
    data["buildings"].append(design)
    return data, src["name"]


class TestUnitNames(unittest.TestCase):
    def test_shared_unit_names_take_the_building_name(self):
        data, first = _two_blocks()
        plan = model.parse_plan(data)
        names = sorted(b.units.name for z in plan.zones for b in z.buildings if b.units)
        self.assertEqual(names, sorted([f"{first} Apartment", "Second Flats Apartment"]))

    def test_a_lone_unit_building_keeps_the_plain_name(self):
        plan = model.parse_plan(util.load_plan("apartment-block.plan.json"))
        names = [b.units.name for z in plan.zones for b in z.buildings if b.units]
        self.assertEqual(names, ["Apartment"])


if __name__ == "__main__":
    unittest.main()
