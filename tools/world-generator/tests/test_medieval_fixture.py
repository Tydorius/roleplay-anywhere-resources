"""The first real model run's plan (GLM 5.3 Flash, a medieval village with
an inn, a mill and a chapel) lays out cleanly: every road placed, every
sleeper in a bed, nothing important left unplaced."""
import json
import os
import unittest

import worldgen

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures",
                       "medieval-glm-plan.json")


def load(seed=1):
    with open(FIXTURE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data, worldgen.run(data, seed=seed)


class TestMedievalFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.world = load(1)

    def test_every_road_is_placed(self):
        road_failures = [f for (w, r) in self.world.failures if "road" in w]
        self.assertEqual(road_failures, [])
        self.assertEqual(len(self.world.roads), len(self.data["roads"]))

    def test_every_room_reachable(self):
        m = self.world.metrics["rooms"]
        self.assertEqual(m["reachable"], m["total"],
                         f"unreachable rooms: {m['unreachable']}")
        self.assertEqual(self.world.metrics["reachability"], 1.0)

    def test_every_entrance_reachable_from_a_road(self):
        m = self.world.metrics["entrances"]
        self.assertEqual(m["reachable_from_road"], m["total"],
                         f"entrances off the roads: {m['unreachable']}")

    def test_at_most_three_unplaced_pieces(self):
        unplaced = self.world.metrics["objects"]["unplaced"]
        self.assertLessEqual(len(unplaced), 3, f"unplaced pieces: {unplaced}")

    def test_all_sleepers_in_beds(self):
        bedded = {o.region for o in self.world.objects
                  if self.world.templates[o.template].for_sleep}
        for c in self.world.characters:
            for blk in c.schedule:
                if blk["role"] == "sleep":
                    self.assertIn(blk["location"], bedded,
                                  f"{c.name} sleeps in {blk['location']} "
                                  "which has no forSleep object")

    def test_sleep_rooms_in_the_spec_have_beds(self):
        """The builder's own check, against the emitted spec."""
        spec = worldgen.build_spec(self.world, self.data)
        beds = set()
        for t in spec["objectTemplates"]:
            if t.get("forSleep"):
                for pl in t.get("placements", []):
                    beds.add(pl[0] if isinstance(pl[0], str) else "*")
        people = list(spec["npcs"]) + [spec["player"]]
        self.assertGreaterEqual(len(people), 9)
        for p in people:
            for blk in p["schedule"]:
                if blk["role"] == "sleep":
                    self.assertIn(blk["location"], beds,
                                  f"{p['name']} sleeps in {blk['location']} "
                                  "which has no forSleep object")

    def test_no_overlaps(self):
        self.assertEqual(self.world.metrics["region_overlaps"], [])
        self.assertEqual(self.world.metrics["object_overlaps"], [])
        self.assertEqual(self.world.metrics["objects_out_of_bounds"], [])

    def test_doors_and_walkways_clear(self):
        self.assertTrue(self.world.metrics["doors_clear"])
        self.assertTrue(self.world.metrics["walkways_clear"])


if __name__ == "__main__":
    unittest.main()
