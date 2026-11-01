"""Roads always connect: a road between two zones that do not share an edge
is routed through the zones between them (a chain of gutter crossings) or
along the corridor network between zones — never reported as unplaceable."""
import random
import unittest

import worldgen
from worldgen.layout_map import _faces, _route_through, layout_map
from worldgen.model import Rect, parse_plan


def plan(zone_defs, roads):
    """A bare plan: zones with adjacency and roads, nothing else."""
    return {
        "name": "Roads Test", "worldBackground": "A crossing of ways.",
        "setting": {"era": "medieval", "technology": "wood",
                    "density": "normal", "climate": "temperate"},
        "mapSize": "small",
        "zones": [{"name": n, "kind": k, "sizeClass": s, "description": "d",
                   "ground": "grass", "adjacentTo": adj, "outdoor": [],
                   "buildings": [], "dressing": {"paths": "dirt", "props": [],
                                                 "filler": []}}
                  for (n, k, s, adj) in zone_defs],
        "roads": [{"from": a, "to": b, "kind": "dirt"} for (a, b) in roads],
        "templates": [], "buildings": [], "npcs": [],
        "player": {"name": "Walker", "gender": "female", "role": "walker",
                   "home": "", "work": "", "description": "Walks the roads.",
                   "physicalDescription": "road-worn"},
    }


def hub_plan():
    """A hub with three leaves and a road between every pair of leaves: the
    leaves never face each other, so every road must route through the hub."""
    return plan(
        [("H", "village", "medium", ["L1", "L2", "L3"]),
         ("L1", "field", "medium", ["H"]),
         ("L2", "field", "medium", ["H"]),
         ("L3", "field", "medium", ["H"])],
        [("L1", "L2"), ("L2", "L3"), ("L1", "L3")])


class TestRoadsAlwaysConnect(unittest.TestCase):
    def test_no_road_is_ever_refused(self):
        cases = {
            "chain": plan([("A", "field", "medium", ["B"]),
                           ("B", "field", "medium", ["A", "C"]),
                           ("C", "field", "medium", ["B"])], [("A", "C")]),
            "hub leaves": hub_plan(),
            "two components": plan([("A", "field", "medium", []),
                                    ("B", "field", "medium", [])], [("A", "B")]),
            "crossed chain": plan([("A", "field", "medium", ["B"]),
                                   ("B", "field", "medium", ["A", "C"]),
                                   ("C", "field", "medium", ["B", "D"]),
                                   ("D", "field", "medium", ["C"])],
                                  [("A", "D"), ("B", "D"), ("A", "C")]),
        }
        for name, data in cases.items():
            for seed in range(1, 21):
                m = layout_map(parse_plan(data), random.Random(seed))
                self.assertEqual(
                    m.failures, [],
                    f"{name} seed {seed}: {m.failures}")
                self.assertEqual(len(m.roads), len(data["roads"]),
                                 f"{name} seed {seed}: a road went missing")

    def test_routed_road_ends_at_both_its_zones(self):
        """Every road touches both of its endpoint zones, however it routed."""
        data = hub_plan()
        for seed in range(1, 21):
            m = layout_map(parse_plan(data), random.Random(seed))
            for road in m.roads:
                cells = road.cells()
                for end in (road.a, road.b):
                    zr = m.zones[end]
                    touches = any(zr.x - 1 <= c[0] <= zr.x1 + 1
                                  and zr.y - 1 <= c[1] <= zr.y1 + 1
                                  and (c[0] in (zr.x - 1, zr.x1 + 1)
                                       or c[1] in (zr.y - 1, zr.y1 + 1))
                                  for c in cells)
                    self.assertTrue(touches,
                                    f"seed {seed}: {road.name} never reaches {end}")

    def test_road_rects_stay_between_the_zones(self):
        """Routed segments live in the gutters: they overlap no zone rect."""
        data = hub_plan()
        m = layout_map(parse_plan(data), random.Random(3))
        self.assertEqual(len(m.roads), 3)
        for road in m.roads:
            for seg in road.rects:
                for name, zr in m.zones.items():
                    self.assertFalse(seg.intersects(zr),
                                     f"{road.name} cuts through zone {name}")

    def test_routed_road_walks_the_whole_world(self):
        """The built world stays fully reachable with routed roads."""
        world = worldgen.run(hub_plan(), seed=3)
        self.assertEqual(world.metrics["reachability"], 1.0)
        self.assertEqual(world.metrics["rooms"]["reachable"],
                         world.metrics["rooms"]["total"])

    def test_faces_is_a_geometric_test(self):
        a = Rect(0, 0, 10, 10)
        self.assertTrue(_faces(a, Rect(13, 0, 10, 10)))    # 2-cell gutter east
        self.assertTrue(_faces(a, Rect(0, 12, 10, 10)))    # gutter north
        self.assertFalse(_faces(a, Rect(14, 0, 10, 10)))   # gutter too wide
        self.assertFalse(_faces(a, Rect(13, 9, 10, 10)))   # diagonal corner
        self.assertFalse(_faces(a, Rect(1, 1, 5, 5)))      # contained

    def test_route_through_returns_none_without_a_path(self):
        zones = {"A": Rect(0, 0, 10, 10), "B": Rect(30, 0, 10, 10)}
        self.assertIsNone(_route_through(zones, "A", "B", random.Random(1), []))


if __name__ == "__main__":
    unittest.main()
