"""The assembler's upper storeys (rl-06c): floors on by default through the
api — generate and layout, the off switch, a plan that records its extensions
keeping what it recorded — and the partition rule (design 8.1f): a square-ish
outline takes a landing with its rooms in a 2x2 around it, a long one a
corridor with rooms both sides, three rooms split 2+1, the stair cells line
up storey over storey, a slot nothing fits becomes a closet or store and the
run says so, and a purpose's fit rules (purposeFit) hold through the build: a
living room never serves across a counter, a taproom always does."""
import os
import tempfile
import unittest

import worldgen
from tests.test_model import ScriptedClient, canned_replies
from worldgen import api

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


# ------------------------------------------------------------------ the plans

def _plan(building, kind="house"):
    """A two-zone hamlet with a road, so the building's entrance counts
    toward the reachability metric the way a real plan's does."""
    return {
        "name": "Millet Hollow", "worldBackground": "A hamlet by a ford.",
        "setting": {"era": "medieval", "technology": "iron",
                    "density": "normal", "climate": "mild"},
        "mapSize": "small",
        "zones": [{
            "name": "Millet Hollow", "kind": "village", "sizeClass": "small",
            "description": "The green.", "ground": "grass",
            "adjacentTo": ["The Ford"], "outdoor": [],
            "buildings": [{"name": building["name"], "kind": kind,
                           "sizeClass": "medium", "purpose": "a roof",
                           "residents": building.get("residents", 4),
                           "storeys": 2, "yard": None}],
            "dressing": {"paths": "dirt", "props": [], "filler": []},
        }, {
            "name": "The Ford", "kind": "farmland", "sizeClass": "medium",
            "description": "Wet meadows.", "ground": "grass",
            "adjacentTo": ["Millet Hollow"], "outdoor": [],
            "buildings": [],
            "dressing": {"paths": "dirt", "props": [], "filler": []},
        }],
        "roads": [{"from": "Millet Hollow", "to": "The Ford", "kind": "dirt"}],
        "templates": [],
        "buildings": [building],
        "npcs": [],
        "player": {"name": "The Wanderer", "gender": "female",
                   "role": "traveller", "home": building["name"],
                   "work": "Millet Hollow", "description": "Passing through.",
                   "physicalDescription": "cloaked"},
    }


def _building(name, ground, upper, residents, couples):
    return {"name": name, "wall": "wood", "ground": "wood",
            "residents": residents, "couples": couples,
            "wealth": "modest", "condition": "kept", "rooms": ground,
            "connections": [[ground[0]["name"], r["name"]]
                            for r in ground[1:]],
            "entrance": {"room": ground[0]["name"], "side": "south"},
            "stairs": {"room": "Stair Room"},
            "upper": [{"storey": 2, "rooms": upper, "connections": []}],
            "furniture": [], "yard": None}


GABLE_GROUND = [
    {"name": "Hall", "share": "medium", "use": "great_hall", "purpose": "p"},
    {"name": "Kitchen", "share": "medium", "use": "kitchen", "purpose": "p"},
    {"name": "Stair Room", "share": "small", "use": "lobby", "purpose": "p"},
    {"name": "Workroom", "share": "small", "use": "workshop", "purpose": "p"}]
INN_GROUND = [
    {"name": "Taproom", "share": "large", "use": "taproom", "purpose": "p"},
    {"name": "Kitchen", "share": "medium", "use": "kitchen", "purpose": "p"},
    {"name": "Stair Room", "share": "medium", "use": "lobby", "purpose": "p"},
    {"name": "Stores", "share": "medium", "use": "storage", "purpose": "p"}]
SMALL4 = [
    {"name": "Bedroom", "share": "small", "use": "bedroom", "purpose": "a"},
    {"name": "Guest Room", "share": "small", "use": "guest_room", "purpose": "b"},
    {"name": "Study", "share": "small", "use": "study", "purpose": "c"},
    {"name": "Sewing Room", "share": "small", "use": "study", "purpose": "d"}]
# four rooms an inn's shallow corridor slots hold: no medium bedroom, which
# the residents' bed count grows past the slot depth
INN_UP = [
    {"name": "Guest Room", "share": "small", "use": "guest_room", "purpose": "b"},
    {"name": "Study", "share": "small", "use": "study", "purpose": "c"},
    {"name": "Sewing Room", "share": "small", "use": "study", "purpose": "d"},
    {"name": "Reading Room", "share": "small", "use": "study", "purpose": "e"}]
UP3 = INN_UP[1:]
# the medium shares whose bedrooms the inn's slot depth cannot hold — the
# closet case
INN_BEDS = [
    {"name": "Bedroom", "share": "medium", "use": "bedroom", "purpose": "a"},
    {"name": "Guest Room", "share": "medium", "use": "guest_room", "purpose": "b"},
    {"name": "Study", "share": "small", "use": "study", "purpose": "c"},
    {"name": "Sewing Room", "share": "small", "use": "study", "purpose": "d"}]

LANDING_BUILDING = _building("Gable House", GABLE_GROUND, SMALL4, 6, 2)
INN_BUILDING = _building("The Long Saddle", INN_GROUND, INN_UP, 8, 3)
SPLIT_BUILDING = _building("The Long Saddle", INN_GROUND, UP3, 8, 3)
CLOSET_BUILDING = _building("The Long Saddle", INN_GROUND, INN_BEDS, 8, 3)


def assembled(world, name):
    for b in world.buildings:
        if b.layout.design.name == name:
            return b.layout
    return None


# ------------------------------------------------------------- floors default

class TestFloorsOnByDefault(unittest.TestCase):
    """The api turns the floors extension on unless told otherwise, and a
    plan that records its extensions keeps exactly what it recorded."""

    def test_generate_defaults_to_floors(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village",
                                   client=ScriptedClient(canned_replies()),
                                   seed=3, cast=False, out_dir=tmp,
                                   library=False)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["extensions"], ["floors"])

    def test_the_generate_flag_turns_floors_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village",
                                   client=ScriptedClient(canned_replies()),
                                   seed=3, cast=False, out_dir=tmp,
                                   library=False, floors=False)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["extensions"], [])

    def test_layout_defaults_to_floors(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.relayout(os.path.join(FIXTURES, "village.json"),
                                   seed=5, out_dir=tmp)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["extensions"], ["floors"])

    def test_the_layout_flag_turns_floors_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.relayout(os.path.join(FIXTURES, "village.json"),
                                   seed=5, out_dir=tmp, floors=False)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["extensions"], [])

    def test_a_plan_recording_its_extensions_keeps_them(self):
        # apartment-block.plan.json records ["floors"], ashvale-framed.plan.json
        # records []: neither follows the new default
        for plan_name, want in (("apartment-block.plan.json", ["floors"]),
                                ("ashvale-framed.plan.json", [])):
            with self.subTest(plan_name):
                with tempfile.TemporaryDirectory() as tmp:
                    summary = api.relayout(os.path.join(FIXTURES, plan_name),
                                           seed=1, out_dir=tmp)
                self.assertTrue(summary["ok"], summary)
                self.assertEqual(summary["extensions"], want)


# ------------------------------------------------------------ the storey case

class StoreyCase(unittest.TestCase):
    """The shared plumbing: one two-storey building assembled with the room
    assembler and the floors extension, and the soundness every partition
    promises of its upper storey."""

    @classmethod
    def build(cls, building, seed, kind="house"):
        world = worldgen.run(_plan(building, kind), seed=seed,
                             room_assembler=True, extensions=("floors",))
        bl = assembled(world, building["name"])
        assert bl is not None, "no building in the world"
        assert getattr(bl, "assembled", False), \
            [f for f in world.fallbacks
             if f[0] == f"building {building['name']}"]
        return world, bl

    @classmethod
    def the_floor(cls, world, name):
        floors = [f for f in world.floors if f.building == name]
        assert len(floors) == 1, [f.building for f in world.floors]
        return floors[0]

    def assert_sound(self, world, bl, f):
        """What any partitioned storey owes: the checks pass, the storey
        covers the ground's whole outline without overlap, its doors sit
        between two rooms, the stair lands on the ground stair's own cell,
        every room is reached from it, and every piece sits inside its
        room."""
        m = world.metrics
        self.assertEqual(m["floors"]["issues"], [], m["floors"]["issues"])
        self.assertEqual(m["reachability"], 1.0, m["rooms"])
        self.assertTrue(m["doors_clear"])
        self.assertTrue(m["walkways_clear"])
        lay = f.layout
        self.assertEqual((lay.rect.w, lay.rect.h), (bl.rect.w, bl.rect.h),
                         "the storey is not the ground's whole outline")
        for i, a in enumerate(lay.rooms):
            self.assertTrue(lay.rect.contains_rect(a.rect), a.base_name)
            for b in lay.rooms[i + 1:]:
                self.assertFalse(a.rect.intersects(b.rect),
                                 (a.base_name, b.base_name))
        for (ax, ay), (bx, by) in lay.door_pairs:
            self.assertEqual(abs(ax - bx) + abs(ay - by), 1,
                             ((ax, ay), (bx, by)))
            owners = [r.base_name for r in lay.rooms
                      if r.rect.contains_cell((ax, ay))
                      or r.rect.contains_cell((bx, by))]
            self.assertGreaterEqual(len(owners), 2,
                                    ((ax, ay), (bx, by), owners))

        # the stair from below lands on the ground stair's own cell of the
        # plane, and the top storey grows no stair of its own
        self.assertEqual((bl.stair_cell[0] - bl.rect.x,
                          bl.stair_cell[1] - bl.rect.y),
                         (f.stair_down[1][0] - f.rect.x,
                          f.stair_down[1][1] - f.rect.y),
                         "the stair cells do not line up")
        self.assertIsNone(f.stair_up)

        def cell_room(cell):
            for i, r in enumerate(lay.rooms):
                if r.rect.contains_cell(cell):
                    return i
            return None

        edges = {i: set() for i in range(len(lay.rooms))}
        for a, b in lay.door_pairs:
            ia, ib = cell_room(a), cell_room(b)
            if ia is not None and ib is not None:
                edges[ia].add(ib)
                edges[ib].add(ia)
        start = cell_room(f.stair_down[1])
        self.assertIsNotNone(start, "the stair lands in no room")
        seen, queue = {start}, [start]
        while queue:
            for n in edges[queue.pop(0)]:
                if n not in seen:
                    seen.add(n)
                    queue.append(n)
        self.assertEqual(seen, set(range(len(lay.rooms))),
                          [(r.base_name, sorted(edges[i]))
                           for i, r in enumerate(lay.rooms)])

        for o in world.objects:
            if not o.region.startswith(f.region_name):
                continue
            room = next((r for r in lay.rooms
                         if o.region == f"{f.region_name} {r.base_name}"),
                        None)
            self.assertIsNotNone(room, o.region)
            self.assertTrue(room.rect.contains_cell(o.pos),
                            (o.region, o.pos, o.template))

    def sides_of_landing(self, lay, landing):
        """Each room's side of the landing on the outline's short axis (a
        vertical landing splits west/east, a horizontal one south/north)."""
        if lay.rect.w >= lay.rect.h:
            def side(r):
                return "S" if r.rect.y1 < landing.rect.y else "N"
        else:
            def side(r):
                return "W" if r.rect.x1 < landing.rect.x else "E"
        return {r.base_name: side(r) for r in lay.rooms if r is not landing}


class TestALandingStorey(StoreyCase):
    """A square-ish outline (4 rooms upstairs, ratio under 3:2): the storey
    is a 2x2 of rooms around a landing centred on the stair."""

    @classmethod
    def setUpClass(cls):
        cls.world, cls.bl = cls.build(LANDING_BUILDING, seed=1)
        cls.f = cls.the_floor(cls.world, "Gable House")

    def test_four_rooms_in_a_2x2_around_the_landing(self):
        lay = self.f.layout
        landing = next((r for r in lay.rooms if r.base_name == "Landing"),
                       None)
        self.assertIsNotNone(landing, [r.base_name for r in lay.rooms])
        long_dim = max(lay.rect.w, lay.rect.h)
        short_dim = min(lay.rect.w, lay.rect.h)
        self.assertLessEqual(long_dim, 1.5 * short_dim,
                             "a square outline took a corridor")
        named = {"Bedroom", "Guest Room", "Study", "Sewing Room"}
        self.assertLessEqual(named, {r.base_name for r in lay.rooms})
        sides = self.sides_of_landing(lay, landing)
        for side in ("W", "E") if lay.rect.h > lay.rect.w else ("S", "N"):
            got = {n for n, s in sides.items() if s == side and n in named}
            self.assertEqual(len(got), 2,
                             f"{side} of the landing holds {sorted(got)}")

    def test_the_storey_is_sound(self):
        self.assert_sound(self.world, self.bl, self.f)


class TestACorridorStorey(StoreyCase):
    """A long outline (4 rooms upstairs, ratio past 3:2): a corridor runs
    the long way with rooms both sides."""

    @classmethod
    def setUpClass(cls):
        cls.world, cls.bl = cls.build(INN_BUILDING, seed=1, kind="inn")
        cls.f = cls.the_floor(cls.world, "The Long Saddle")

    def test_a_corridor_runs_the_long_way_with_rooms_both_sides(self):
        lay = self.f.layout
        corr = next((r for r in lay.rooms if r.base_name == "Corridor"), None)
        self.assertIsNotNone(corr, [r.base_name for r in lay.rooms])
        long_dim = max(lay.rect.w, lay.rect.h)
        short_dim = min(lay.rect.w, lay.rect.h)
        self.assertGreater(long_dim, 1.5 * short_dim,
                           "a long outline took a landing")
        # the corridor spans the outline end to end on its long axis
        self.assertEqual(max(corr.rect.w, corr.rect.h), long_dim)
        named = {"Guest Room", "Study", "Sewing Room", "Reading Room"}
        self.assertLessEqual(named, {r.base_name for r in lay.rooms})
        sides = self.sides_of_landing(lay, corr)
        for side in ("W", "E") if lay.rect.h > lay.rect.w else ("S", "N"):
            got = {n for n, s in sides.items() if s == side and n in named}
            self.assertTrue(got, f"{side} of the corridor holds no room")

    def test_the_storey_is_sound(self):
        self.assert_sound(self.world, self.bl, self.f)


class TestAThreeRoomStoreySplitsTwoAndOne(StoreyCase):
    """Three rooms upstairs: the slots go 2+1, one side of the landing
    holding two rooms and the other one."""

    @classmethod
    def setUpClass(cls):
        cls.world, cls.bl = cls.build(SPLIT_BUILDING, seed=2, kind="inn")
        cls.f = cls.the_floor(cls.world, "The Long Saddle")

    def test_the_rooms_split_two_and_one(self):
        lay = self.f.layout
        landing = next(r for r in lay.rooms
                       if r.base_name in ("Landing", "Corridor"))
        named = {"Study", "Sewing Room", "Reading Room"}
        self.assertLessEqual(named, {r.base_name for r in lay.rooms})
        sides = self.sides_of_landing(lay, landing)
        counts = {}
        for n, s in sides.items():
            if n in named:
                counts[s] = counts.get(s, 0) + 1
        self.assertEqual(sorted(counts.values()), [1, 2], counts)

    def test_the_storey_is_sound(self):
        self.assert_sound(self.world, self.bl, self.f)


class TestAClosetSlotIsNoted(StoreyCase):
    """A slot nothing fits — the inn's medium bedrooms outgrow the corridor
    slots — becomes a store, and the run's notes say which room lost its
    slot; the storey itself still builds sound."""

    @classmethod
    def setUpClass(cls):
        cls.world, cls.bl = cls.build(CLOSET_BUILDING, seed=1, kind="inn")
        cls.f = cls.the_floor(cls.world, "The Long Saddle")

    def test_the_lost_slot_became_a_store_and_the_note_names_the_room(self):
        names = {r.base_name for r in self.f.layout.rooms}
        self.assertNotIn("Bedroom", names,
                         "the bedroom fit where the note says it cannot")
        self.assertTrue([n for n in names if n.startswith("Store")],
                        sorted(names))
        notes = [n for n in self.world.notes
                 if n[0] == "room Bedroom in building The Long Saddle"]
        self.assertEqual(len(notes), 1, self.world.notes)
        self.assertIn("took a closet instead", notes[0][1])

    def test_the_storey_is_sound(self):
        self.assert_sound(self.world, self.bl, self.f)


class TestTheSameSeedGivesTheSameStorey(StoreyCase):
    def test_two_runs_place_the_same_rooms(self):
        def shape():
            world, bl = self.build(LANDING_BUILDING, seed=1)
            f = self.the_floor(world, "Gable House")
            return (sorted((r.base_name, r.rect.x, r.rect.y, r.rect.w, r.rect.h)
                           for r in f.layout.rooms),
                    sorted(tuple(sorted(p)) for p in f.layout.door_pairs),
                    f.stair_down[1], f.rect)
        self.assertEqual(shape(), shape())


class TestPurposeFitHoldsThroughTheBuild(unittest.TestCase):
    """The purposeFit table through a built world: the taproom's rules
    require a serving counter, the living room's forbid one — every object
    the counter.serve binding can place is named for it, so the placed
    templates tell the story."""

    PLAN = {
        "name": "Millet Hollow", "worldBackground": "A hamlet by a ford.",
        "setting": {"era": "medieval", "technology": "iron",
                    "density": "normal", "climate": "mild"},
        "mapSize": "small",
        "zones": [{
            "name": "Millet Hollow", "kind": "village", "sizeClass": "small",
            "description": "The green.", "ground": "grass",
            "adjacentTo": ["The Ford"], "outdoor": [],
            "buildings": [
                {"name": "The Gable House", "kind": "house",
                 "sizeClass": "medium", "purpose": "a roof",
                 "residents": 6, "storeys": 1, "yard": None},
                {"name": "The Long Saddle", "kind": "inn",
                 "sizeClass": "medium", "purpose": "bed and beer",
                 "residents": 8, "storeys": 1, "yard": None}],
            "dressing": {"paths": "dirt", "props": [], "filler": []},
        }, {
            "name": "The Ford", "kind": "farmland", "sizeClass": "medium",
            "description": "Wet meadows.", "ground": "grass",
            "adjacentTo": ["Millet Hollow"], "outdoor": [],
            "buildings": [],
            "dressing": {"paths": "dirt", "props": [], "filler": []},
        }],
        "roads": [{"from": "Millet Hollow", "to": "The Ford", "kind": "dirt"}],
        "templates": [],
        "buildings": [
            {"name": "The Gable House", "wall": "wood", "ground": "wood",
             "residents": 6, "couples": 2, "wealth": "modest",
             "condition": "kept",
             "rooms": [
                 {"name": "Hall", "share": "medium", "use": "lobby",
                  "purpose": "the door"},
                 {"name": "Main Room", "share": "large", "use": "living_room",
                  "purpose": "hearth and table"},
                 {"name": "Bedroom", "share": "small", "use": "master_bedroom",
                  "purpose": "the bed"}],
             "connections": [["Hall", "Main Room"],
                             ["Main Room", "Bedroom"]],
             "entrance": {"room": "Hall", "side": "south"},
             "furniture": [], "yard": None},
            {"name": "The Long Saddle", "wall": "wood", "ground": "wood",
             "residents": 8, "couples": 3, "wealth": "modest",
             "condition": "kept",
             "rooms": [
                 {"name": "Taproom", "share": "large", "use": "taproom",
                  "purpose": "beer"},
                 {"name": "Kitchen", "share": "medium", "use": "kitchen",
                  "purpose": "the pots"},
                 {"name": "Stores", "share": "medium", "use": "storage",
                  "purpose": "sacks"}],
             "connections": [["Taproom", "Kitchen"], ["Taproom", "Stores"]],
             "entrance": {"room": "Taproom", "side": "south"},
             "furniture": [], "yard": None}],
        "npcs": [],
        "player": {"name": "The Wanderer", "gender": "female",
                   "role": "traveller", "home": "The Gable House",
                   "work": "Millet Hollow", "description": "Passing through.",
                   "physicalDescription": "cloaked"},
    }

    @classmethod
    def setUpClass(cls):
        cls.world = worldgen.run(cls.PLAN, seed=7, room_assembler=True)

    def _objects(self, building, room):
        return [o.template for o in self.world.objects
                if o.region == f"{building} {room}"]

    def test_both_buildings_assembled(self):
        for name in ("The Gable House", "The Long Saddle"):
            bl = assembled(self.world, name)
            self.assertIsNotNone(bl, name)
            self.assertTrue(getattr(bl, "assembled", False),
                            [f for f in self.world.fallbacks])

    def test_the_taproom_always_serves_across_a_counter(self):
        counters = [t for t in self._objects("The Long Saddle", "Taproom")
                    if "counter" in t.lower()]
        self.assertTrue(counters,
                        "a taproom without its serving counter")

    def test_the_living_room_never_does(self):
        counters = [t for t in self._objects("The Gable House", "Main Room")
                    if "counter" in t.lower()]
        self.assertEqual(counters, [],
                         "a living room serving across a counter")


if __name__ == "__main__":
    unittest.main()
