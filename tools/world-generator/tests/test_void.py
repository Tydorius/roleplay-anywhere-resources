"""Interior-only zones (brief 012e change 5): a zone may set
``"exterior": "void"`` and everything walkable outside its walled regions
becomes out of bounds. The ship fixture is a plan whose zones are all void,
so the whole map outside the corridors and compartments must be sealed by
walkability-0 slabs — no walkable open ground anywhere — while the build
stays fully reachable (the roads became walled connector tubes, so the
flat-map walk still runs end to end)."""
import os
import unittest

from tests import util


class TestVoidZones(unittest.TestCase):
    def build(self, seed=1):
        return util.build_world("ship-void.plan.json", seed=seed)

    def test_every_zone_is_void(self):
        w = self.build()
        self.assertTrue(w.void_default)
        self.assertEqual(w.void_zones, {"Relay Dock", "The Merian"})

    def test_every_walkable_cell_is_inside_a_walled_region(self):
        w = self.build()
        walled = set()
        for r in w.regions:
            if r.wall:
                walled |= r.rect.cells()
        slabbed = set()
        for o in w.objects:
            if "Void Slab" in o.template:
                t = w.templates[o.template]
                self.assertEqual(t.walkability, 0.0,
                                 f"{o.template} must seal, not decorate")
                wdt, hgt = t.size
                slabbed |= {(x, y) for x in range(o.pos[0], o.pos[0] + wdt)
                            for y in range(o.pos[1], o.pos[1] + hgt)}
        every = {(x, y) for x in range(w.grid[0]) for y in range(w.grid[1])}
        self.assertEqual(every - walled - slabbed, set(),
                         "open walkable ground left outside the walls")

    def test_void_roads_are_walled_tubes_not_open_ground(self):
        w = self.build()
        self.assertFalse([r for r in w.regions if r.kind == "road"])
        pieces = [r for r in w.regions
                  if (r.name or "").startswith("Relay Dock to The Merian Road")]
        self.assertTrue(pieces)
        road = next(r for r in w.roads
                    if r.name == "Relay Dock to The Merian Road")
        walled = {(x, y) for r in w.regions if r.wall
                  for (x, y) in r.rect.cells()}
        for r in pieces:
            self.assertEqual(r.wall, "stone")
        for cell in road.cells():
            self.assertIn(cell, walled,
                          f"road cell {cell} left as open ground")

    def test_the_ship_builds_clean_and_reachable(self):
        for seed in (1, 2):
            with self.subTest(seed=seed):
                w = self.build(seed)
                self.assertEqual(w.metrics["errors"]["dropped"], [])
                self.assertEqual(w.metrics["reachability"], 1.0)
                self.assertEqual(w.failures, [])


if __name__ == "__main__":
    unittest.main()
