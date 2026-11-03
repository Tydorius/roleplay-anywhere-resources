"""Whole-fixture checks: the merged village plan lays out cleanly."""
import json
import os
import unittest

import worldgen
from worldgen.checks import compute_openings, walkability_grid, flood

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "village.json")


def load(seed=1):
    with open(FIXTURE, "r", encoding="utf-8") as f:
        data = json.load(f)
    world = worldgen.run(data, seed=seed)
    return data, world


class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.world = load(1)

    def test_every_room_reachable(self):
        m = self.world.metrics["rooms"]
        self.assertEqual(m["reachable"], m["total"], f"unreachable rooms: {m['unreachable']}")
        self.assertEqual(self.world.metrics["reachability"], 1.0)

    def test_every_entrance_reachable_from_a_road(self):
        m = self.world.metrics["entrances"]
        self.assertEqual(m["reachable_from_road"], m["total"],
                         f"entrances off the roads: {m['unreachable']}")

    def test_no_unplaced_pieces(self):
        unplaced = self.world.metrics["objects"]["unplaced"]
        self.assertEqual(unplaced, [], f"unplaced pieces: {unplaced}")

    def test_no_overlaps(self):
        self.assertEqual(self.world.metrics["region_overlaps"], [])
        self.assertEqual(self.world.metrics["object_overlaps"], [])
        self.assertEqual(self.world.metrics["objects_out_of_bounds"], [])

    def test_grid_within_bounds(self):
        w, h = self.world.grid
        self.assertGreaterEqual(w, 48)
        self.assertGreaterEqual(h, 48)
        self.assertLessEqual(w, 160)
        self.assertLessEqual(h, 160)

    def test_rooms_from_every_building_entrance(self):
        """Flood each building's entrance separately: all its rooms reachable."""
        world = self.world
        openings = compute_openings(world)
        blocked, doors = walkability_grid(world, openings)
        for b in world.buildings:
            bl = b.layout
            seen = flood(world, [bl.entrance_door], blocked)
            for room in bl.rooms:
                self.assertTrue(room.rect.interior().cells() & seen,
                                f"{room.full_name} unreachable from its building entrance")

    def test_spec_regions_nest_or_are_disjoint(self):
        """The builder's own nesting rule, checked on the emitted regions."""
        data, world = load(1)
        spec = worldgen.build_spec(world, data)
        regs = [(r["position"], r["size"], r["name"]) for r in spec["regions"]]

        def tup(pos, size):
            return (pos[0], pos[1], pos[0] + size[0] - 1, pos[1] + size[1] - 1)

        for i, (pa, sa, na) in enumerate(regs):
            for pb, sb, nb in regs[i + 1:]:
                a, b = tup(pa, sa), tup(pb, sb)
                nested = (a[0] <= b[0] and a[1] <= b[1] and b[2] <= a[2] and b[3] <= a[3]) or \
                         (b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3])
                disjoint = a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]
                self.assertTrue(nested or disjoint, f"regions {na} and {nb} partially overlap")

    def test_spec_objects_off_walls_and_doors(self):
        data, world = load(1)
        spec = worldgen.build_spec(world, data)
        regions = {r["name"]: r for r in spec["regions"]}
        wall_cells = {}
        for r in spec["regions"]:
            if "wall" in r:
                x, y = r["position"]
                w, h = r["size"]
                wall_cells[r["name"]] = {(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)
                                         if cx in (x, x + w - 1) or cy in (y, y + h - 1)}
        all_walls = set().union(*wall_cells.values()) if wall_cells else set()
        doors = set()
        for r in spec["regions"]:
            for d in r.get("doors", []):
                doors.add(tuple(d))
        tmpl_sizes = {t["name"]: tuple(t["size"]) for t in spec["objectTemplates"]}
        for t in spec["objectTemplates"]:
            for pl in t.get("placements", []):
                if isinstance(pl[0], str):  # room-relative: resolve to a cell
                    r = regions[pl[0]]
                    x = r["position"][0] + 1 + pl[1]
                    y = r["position"][1] + 1 + pl[2]
                    pos = (x, y)
                else:
                    pos = (pl[0], pl[1])
                w, h = tmpl_sizes[t["name"]]
                fp = {(cx, cy) for cx in range(pos[0], pos[0] + w) for cy in range(pos[1], pos[1] + h)}
                self.assertFalse(fp & all_walls, f"{t['name']} at {pos} sits on a wall")
                self.assertFalse(fp & doors, f"{t['name']} at {pos} blocks a door cell")

    def test_schedules_cover_24h_in_known_regions(self):
        data, world = load(1)
        spec = worldgen.build_spec(world, data)
        names = {r["name"] for r in spec["regions"]}
        people = list(spec["npcs"]) + [spec["player"]]
        self.assertGreaterEqual(len(people), 4)
        for p in people:
            total = 0
            sched = p["schedule"]
            for i, blk in enumerate(sched):
                self.assertIn(blk["location"], names, f"{p['name']} sleeps/walks in unknown {blk['location']}")
                self.assertIn(blk["role"], ("work", "leisure", "sleep"))
                s = int(blk["start"][:2]) * 60 + int(blk["start"][3:])
                e = int(blk["end"][:2]) * 60 + int(blk["end"][3:])
                total += (e - s) % 1440
                nxt = sched[(i + 1) % len(sched)]
                self.assertEqual(blk["end"], nxt["start"], f"{p['name']} schedule gap")
            self.assertEqual(total, 1440, f"{p['name']} schedule does not cover 24h")

    def test_sleep_rooms_have_beds(self):
        data, world = load(1)
        spec = worldgen.build_spec(world, data)
        beds = {}
        for t in spec["objectTemplates"]:
            for pl in t.get("placements", []):
                if t.get("forSleep"):
                    beds.setdefault(pl[0] if isinstance(pl[0], str) else "*", 0)
                    beds[pl[0] if isinstance(pl[0], str) else "*"] += 1
        for p in list(spec["npcs"]) + [spec["player"]]:
            for blk in p["schedule"]:
                if blk["role"] == "sleep":
                    self.assertIn(blk["location"], beds,
                                  f"{p['name']} sleeps in {blk['location']} which has no bed")


if __name__ == "__main__":
    unittest.main()
