"""Room library step 5a: the room assembler lays one-storey library buildings
out of the library's own fixed rooms (``--room-assembler``, off by default).
With the switch off nothing changes — the two model fixture plans still build
byte-identical specs (and the flag on them changes nothing either: no room of
theirs names a library purpose). A library cottage assembles with its rooms
reached from the entrance, doors on shared walls, no overlap and every piece
inside its room; a purpose the library does not know falls back to the old
method with the reason recorded; the same seed gives the same building; a
bedroom picked for two residents sleeps two."""
import json
import os
import tempfile
import unittest

import worldgen
from worldgen import api
from worldgen.model import bed_capacity

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
DATA = os.path.join(os.path.dirname(__file__), "data")

# the fixture plans whose off-switch spec bytes are the reference; neither is
# a library plan, so the flag must leave them untouched
BYTE_FIXTURES = (
    ("medieval-glm-plan.json", "assembler-off-medieval-glm-plan.json"),
    ("cyberpunk-glm-plan.json", "assembler-off-cyberpunk-glm-plan.json"),
)

COTTAGE_PLAN = {
    "name": "Rosemere",
    "worldBackground": "A hamlet by a ford.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Rosemere", "kind": "village", "sizeClass": "small",
        "description": "The ford.", "ground": "grass", "adjacentTo": ["The Ford"],
        "outdoor": [], "buildings": [
            {"name": "Rose Cottage", "kind": "cottage", "sizeClass": "small",
             "purpose": "a cotter's home", "residents": 2, "yard": None}],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "The Ford", "kind": "farmland", "sizeClass": "medium",
        "description": "Wet meadows.", "ground": "grass", "adjacentTo": ["Rosemere"],
        "outdoor": [], "buildings": [],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [{"from": "Rosemere", "to": "The Ford", "kind": "dirt"}],
    "templates": [],
    "buildings": [
        {"name": "Rose Cottage", "wall": "wood", "ground": "wood",
         "residents": 2, "couples": 1, "wealth": "modest", "condition": "kept",
         "rooms": [
             {"name": "Hall", "share": "medium", "use": "lobby",
              "purpose": "the door and the settle"},
             {"name": "Main Room", "share": "large", "use": "living_room",
              "purpose": "hearth and table"},
             {"name": "Bedroom", "share": "small", "use": "master_bedroom",
              "purpose": "the bed under the eaves"}],
         "connections": [["Hall", "Main Room"], ["Main Room", "Bedroom"]],
         "entrance": {"room": "Hall", "side": "south"},
         "furniture": [], "yard": None},
    ],
    "npcs": [],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "Rose Cottage", "work": "Rosemere",
               "description": "Passing through.", "physicalDescription": "cloaked"},
}


def cottage_plan(**changes):
    data = json.loads(json.dumps(COTTAGE_PLAN))
    building = data["buildings"][0]
    for key, value in changes.items():
        if key in ("wealth", "condition", "residents", "couples"):
            building[key] = value
        elif key == "use":
            building["rooms"][2]["use"] = value
        else:
            raise ValueError(key)
    return data


def assembled(world, name="Rose Cottage"):
    for b in world.buildings:
        if b.layout.design.name == name:
            return b.layout
    return None


class TestOffIsByteIdentical(unittest.TestCase):
    def test_the_switch_leaves_the_fixture_plans_alone(self):
        for plan_name, ref_name in BYTE_FIXTURES:
            with self.subTest(plan_name):
                want = json.load(open(os.path.join(DATA, ref_name),
                                      encoding="utf-8"))["spec"]
                with tempfile.TemporaryDirectory() as tmp:
                    api.relayout(os.path.join(FIXTURES, plan_name), seed=1,
                                 out_dir=os.path.join(tmp, "off"))
                    api.relayout(os.path.join(FIXTURES, plan_name), seed=1,
                                 out_dir=os.path.join(tmp, "on"),
                                 room_assembler=True)
                    for run in ("off", "on"):
                        with open(os.path.join(tmp, run, "spec.py"),
                                  encoding="utf-8", newline="") as f:
                            self.assertEqual(f.read(), want, run)


class TestACottageAssembles(unittest.TestCase):
    def setUp(self):
        self.world = worldgen.run(cottage_plan(), seed=7, room_assembler=True)
        self.bl = assembled(self.world)
        self.assertIsNotNone(self.bl, "no building in the world")
        self.assertTrue(getattr(self.bl, "assembled", False),
                        "the cottage fell back to the old method")

    def test_rooms_do_not_overlap_and_doors_are_on_shared_walls(self):
        rooms = self.bl.rooms
        self.assertGreaterEqual(len(rooms), 3, [r.base_name for r in rooms])
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                self.assertFalse(a.rect.intersects(b.rect),
                                 (a.base_name, b.base_name))
        for pair in self.bl.door_pairs:
            (ax, ay), (bx, by) = pair
            self.assertEqual(abs(ax - bx) + abs(ay - by), 1, pair)
            self.assertIn(ax, (bx - 1, bx, bx + 1), pair)
            self.assertIn(ay, (by - 1, by, by + 1), pair)
            owners = [r.base_name for r in rooms if r.rect.contains_cell(pair[0])
                      or r.rect.contains_cell(pair[1])]
            self.assertGreaterEqual(len(owners), 2, (pair, owners))

    def test_every_room_is_reached_from_the_entrance(self):
        rooms = self.bl.rooms

        def cell_room(cell):
            for i, r in enumerate(rooms):
                if r.rect.contains_cell(cell):
                    return i
            return None

        edges = {i: set() for i in range(len(rooms))}
        for a, b in self.bl.door_pairs:
            ia, ib = cell_room(a), cell_room(b)
            if ia is not None and ib is not None:
                edges[ia].add(ib)
                edges[ib].add(ia)
        start = rooms.index(self.bl.entrance_room)
        seen, queue = {start}, [start]
        while queue:
            for n in edges[queue.pop(0)]:
                if n not in seen:
                    seen.add(n)
                    queue.append(n)
        self.assertEqual(seen, set(range(len(rooms))),
                          [(r.base_name, sorted(edges[i])) for i, r in enumerate(rooms)])
        # the entrance itself opens on the entrance room's ring
        self.assertIsNotNone(self.bl.entrance_door)
        self.assertTrue(self.bl.entrance_room.rect.contains_cell(self.bl.entrance_door))

    def test_every_piece_is_inside_its_room_and_the_way_stays_clear(self):
        m = self.world.metrics
        self.assertEqual(m["reachability"], 1.0, m.get("objects"))
        self.assertTrue(m["walkways_clear"], m.get("walkways"))
        self.assertTrue(m["doors_clear"], m.get("doors"))
        names = {r.base_name: r for b in self.world.buildings
                 for r in b.layout.rooms}
        placed = 0
        for o in self.world.objects:
            region = self.world.regions_by_name.get(o.region)
            self.assertIsNotNone(region, o.region)
            self.assertTrue(region.rect.contains_cell(o.pos), (o.region, o.pos))
            if o.region.startswith("Rose Cottage"):
                placed += 1
        self.assertGreater(placed, 0, "the assembled rooms shipped empty")
        self.assertTrue(all(r.base_name in names for r in self.bl.rooms))

    def test_no_fallback_was_recorded(self):
        self.assertFalse([f for f in self.world.fallbacks
                          if f[0] == "building Rose Cottage"], self.world.fallbacks)


class TestFallbacksAndSeeds(unittest.TestCase):
    def test_an_unknown_purpose_falls_back_with_the_reason(self):
        world = worldgen.run(cottage_plan(use="throne_room"), seed=7,
                             room_assembler=True)
        bl = assembled(world)
        self.assertFalse(getattr(bl, "assembled", False),
                         "a throne room is not a library room")
        notes = [f for f in world.fallbacks if f[0] == "building Rose Cottage"]
        self.assertEqual(len(notes), 1, world.fallbacks)
        self.assertIn("not in the library", notes[0][1])
        # the world itself still builds clean
        self.assertEqual(world.metrics["reachability"], 1.0)

    def test_the_same_seed_gives_the_same_building(self):
        def shape():
            w = worldgen.run(cottage_plan(), seed=11, room_assembler=True)
            bl = assembled(w)
            self.assertTrue(getattr(bl, "assembled", False))
            return (sorted((r.base_name, r.rect.x, r.rect.y, r.rect.w, r.rect.h)
                           for r in bl.rooms),
                    sorted(tuple(sorted(p)) for p in bl.door_pairs),
                    bl.entrance_door, bl.entrance_side)
        self.assertEqual(shape(), shape())

    def test_a_bedroom_for_two_sleeps_two(self):
        world = worldgen.run(cottage_plan(), seed=7, room_assembler=True)
        bl = assembled(world)
        self.assertTrue(getattr(bl, "assembled", False))
        beds = 0
        for o in world.objects:
            if not o.region.endswith("Bedroom"):
                continue
            t = world.templates[o.template]
            if t.for_sleep:
                beds += bed_capacity(t)
        self.assertGreaterEqual(beds, 2, "two residents, no two beds")


if __name__ == "__main__":
    unittest.main()
