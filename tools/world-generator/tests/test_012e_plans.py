"""Brief 012e change 6: the four shape fixtures — a 6-storey 24-unit
apartment block, a strip of 5 shops with parking, a hospital spine with two
6-room wards and a station hub, and the all-void ship (its sealing is
asserted in test_void). Each builds with 0 dropped and full reachability;
renders live in out/012e-*.png."""
import unittest

from tests import util


class TestApartmentBlock(unittest.TestCase):
    def build(self, seed=1):
        return util.build_world("apartment-block.plan.json",
                                extensions=("floors",), seed=seed)

    def test_builds_clean_and_reachable(self):
        for seed in (1, 2):
            with self.subTest(seed=seed):
                w = self.build(seed)
                self.assertEqual(w.metrics["errors"]["dropped"], [])
                self.assertEqual(w.metrics["reachability"], 1.0)
                self.assertEqual(w.failures, [])

    def test_twenty_four_units_over_six_storeys(self):
        w = self.build()
        self.assertEqual(len(w.floors), 5)      # 5 upper storeys
        self.assertEqual(len(w.portals), 5)
        bl = next(b.layout for b in w.buildings
                  if b.layout.design.name == "Grendel Flats")
        import re
        units = sorted((r.name for r in w.regions
                        if r.name and re.fullmatch(r"Apartment \d+", r.name)),
                       key=lambda n: int(n.split()[1]))
        self.assertEqual(len(units), 24, units)
        self.assertEqual(units[0], "Apartment 1")
        self.assertEqual(units[-1], "Apartment 24")
        self.assertEqual(bl.residents, 8)       # the ground storey's copies


class TestShopStrip(unittest.TestCase):
    def build(self, seed=1):
        return util.build_world("shop-strip.plan.json", seed=seed)

    def test_builds_clean_and_reachable(self):
        w = self.build()
        self.assertEqual(w.metrics["errors"]["dropped"], [])
        self.assertEqual(w.metrics["reachability"], 1.0)
        self.assertEqual(w.failures, [])

    def test_five_shops_on_a_parking_front(self):
        w = self.build()
        comp = w.compounds[0]
        self.assertEqual(comp.front_kind, "parking")
        self.assertEqual(len(comp.parts), 5)
        self.assertIsNotNone(comp.parking)
        _name, _rect, slots = comp.parking
        self.assertTrue(slots, "the parking strip carries vehicle slots")
        for (tmpl, pos) in slots:
            self.assertEqual(tmpl, "Parked van")


class TestHospitalSpine(unittest.TestCase):
    def build(self, seed=1):
        return util.build_world("hospital-spine.plan.json", seed=seed)

    def test_builds_clean_and_reachable(self):
        for seed in (1, 2):
            with self.subTest(seed=seed):
                w = self.build(seed)
                self.assertEqual(w.metrics["errors"]["dropped"], [])
                self.assertEqual(w.metrics["reachability"], 1.0)
                self.assertEqual(w.failures, [])

    def test_two_wards_of_six_rooms_and_a_station_hub(self):
        w = self.build()
        names = {r.name for r in w.regions if r.name}
        for i in range(1, 7):
            self.assertIn(f"North Room {i}", names)
            self.assertIn(f"South Room {i}", names)
        self.assertIn("Nurses' Station", names)
        comp = w.compounds[0]
        self.assertEqual(comp.gate_side, "south")   # the hub gates the block


if __name__ == "__main__":
    unittest.main()
