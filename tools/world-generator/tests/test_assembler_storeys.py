"""The assembler's upper storeys (rl-06c): floors on by default through the
api — generate and layout, the off switch, a plan that records its extensions
keeping what it recorded — and the partition rule (design 8.1f): a square-ish
outline takes a landing with its rooms in a 2x2 around it, a long one a
corridor with rooms both sides, three rooms split 2+1, the stair cells line
up storey over storey, a slot nothing fits becomes a closet or store and the
run says so, the slots follow the sizes the pool could give (the size-first
splits of rl-16), and a purpose's fit rules (purposeFit) hold through the
build: a living room never serves across a counter, a taproom always does."""
import os
import random
import tempfile
import unittest

import worldgen
from tests.test_model import ScriptedClient, canned_replies
from worldgen import api
from worldgen import assembler
from worldgen.model import Rect, RoomSpec

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


# ------------------------------------------------------------------ the plans

def _plan(building, kind="house", storeys=2):
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
                           "storeys": storeys, "yard": None}],
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
# a two-storey house whose run hands the split case below a live assembly
# context: the case partitions a storey of its own directly, so no outline
# the walk would reach has to line up
PACKED_UP = [
    {"name": "Bedroom", "share": "small", "use": "bedroom", "purpose": "a"},
    {"name": "Guest Chamber", "share": "small", "use": "guest_room",
     "purpose": "b"},
    {"name": "Guest Room", "share": "small", "use": "guest_room",
     "purpose": "c"},
    {"name": "Maid Room", "share": "small", "use": "bedroom",
     "purpose": "d"},
    {"name": "Nurse Room", "share": "small", "use": "bedroom",
     "purpose": "e"}]
PACKED_BUILDING = _building("Gable House", GABLE_GROUND, PACKED_UP, 4, 0)


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
    """The shared plumbing: one building of the storey count its case
    names, assembled with the room assembler and the floors extension, and
    the soundness every partition promises of its upper storeys."""

    @classmethod
    def build(cls, building, seed, kind="house", storeys=2):
        world = worldgen.run(_plan(building, kind, storeys), seed=seed,
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

    def assert_sound(self, world, bl, f, stacked=True, top=True):
        """What any partitioned storey owes: the checks pass, the storey
        covers the ground's whole outline without overlap, its doors sit
        between two rooms, the stair lands on the ground stair's own cell
        (a first upper storey's promise — a storey above the first passes
        stacked=False and owes only the checks every storey owes), every
        room is reached from it, and every piece sits inside its room."""
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
        # plane, and the top storey grows no stair of its own; a storey above
        # the first (stacked=False) keeps only what every storey owes — its
        # stair lands in a room, which the walk below from the stair proves
        if stacked:
            self.assertEqual((bl.stair_cell[0] - bl.rect.x,
                              bl.stair_cell[1] - bl.rect.y),
                             (f.stair_down[1][0] - f.rect.x,
                              f.stair_down[1][1] - f.rect.y),
                             "the stair cells do not line up")
        if top:
            self.assertIsNone(f.stair_up)
        else:
            self.assertIsNotNone(f.stair_up)

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


class TestSameNamedRoomsOnTwoStoreys(StoreyCase):
    """rl-19: two rooms named alike on different storeys of one P1 building
    come out with two names, so each keeps its own share of the sleepers —
    four residents over two bedchambers, two asked of each, never the whole
    four asked of both."""

    @classmethod
    def setUpClass(cls):
        building = _building("Gable House", GABLE_GROUND, [
            {"name": "Bedroom", "share": "small", "use": "bedroom",
             "purpose": "a"},
            {"name": "Sewing Room", "share": "small", "use": "study",
             "purpose": "b"}], 4, 0)
        building["upper"].append({
            "storey": 3, "connections": [],
            "rooms": [
                {"name": "Bedroom", "share": "small", "use": "bedroom",
                 "purpose": "c"},
                {"name": "Study", "share": "small", "use": "study",
                 "purpose": "d"}]})
        captured = {}
        orig = assembler._lay_split

        def spy(ctx, design, *a, **k):
            captured.setdefault("ctx", ctx)
            return orig(ctx, design, *a, **k)

        assembler._lay_split = spy
        try:
            cls.world, cls.bl = cls.build(building, seed=1, storeys=3)
        finally:
            assembler._lay_split = orig
        cls.ctx = captured["ctx"]
        cls.floors = sorted((f for f in cls.world.floors
                             if f.building == "Gable House"),
                            key=lambda f: f.storey)

    def _beds(self, room):
        from worldgen.model import bed_capacity
        return sum(bed_capacity(self.world.templates[t])
                   for (t, _p) in room.furniture.placements
                   if self.world.templates[t].for_sleep)

    def test_the_two_bedrooms_take_two_names(self):
        self.assertEqual([f.storey for f in self.floors], [2, 3])
        self.assertIn("Bedroom",
                      {r.base_name for r in self.floors[0].layout.rooms})
        self.assertIn("Bedroom 2",
                      {r.base_name for r in self.floors[1].layout.rooms})

    def test_each_bedroom_is_asked_its_share_not_the_whole(self):
        asks = {n: self.ctx.sleepers[n] for n in ("Bedroom", "Bedroom 2")}
        self.assertEqual(asks, {"Bedroom": (2, 0), "Bedroom 2": (2, 0)},
                         asks)
        beds = {r.base_name: self._beds(r)
                for f in self.floors for r in f.layout.rooms
                if r.base_name in ("Bedroom", "Bedroom 2")}
        for name, (singles, couples) in asks.items():
            self.assertGreaterEqual(beds[name], singles + 2 * couples,
                                    (name, beds))

    def test_the_storeys_are_sound(self):
        middle, top = self.floors
        self.assert_sound(self.world, self.bl, middle, stacked=False,
                          top=False)
        self.assert_sound(self.world, self.bl, top, stacked=False)


class TestAnUnevenSplitSeatsEveryRoomAtFullBeds(StoreyCase):
    """The size-first split's promise (rl-16): a band of five rooms whose
    equal tiles run 5, 5, 5, 5 and 4 cells — a 4-cell slot doors no
    bedchamber, so the equal partition hands the last one a closet. The
    split packs the band at the widths the catalogue gives — the privy the
    one room with a 4-wide turn — and every room keeps its own room at its
    full bed ask. The storey is partitioned directly on the context of one
    real run, so the case needs no outline the walk would reach."""

    SPECS = [
        RoomSpec(name="Bedroom", share="small", use="bedroom"),
        RoomSpec(name="Guest Chamber", share="small", use="guest_room"),
        RoomSpec(name="Guest Room", share="small", use="guest_room"),
        RoomSpec(name="Privy", share="small", use="privy"),
        RoomSpec(name="Servant Room", share="small", use="bedroom"),
        RoomSpec(name="Sewing Room", share="small", use="study"),
        RoomSpec(name="Study", share="small", use="study"),
        RoomSpec(name="Weaving Room", share="small", use="study"),
        RoomSpec(name="Work Room", share="small", use="study")]
    RECT = Rect(0, 0, 24, 20)
    ANCHOR = (12, 10)

    @classmethod
    def setUpClass(cls):
        captured = {}
        orig = assembler._lay_split

        def spy(ctx, design, *a, **k):
            captured.setdefault("ctx", ctx)
            captured.setdefault("design", design)
            return orig(ctx, design, *a, **k)

        assembler._lay_split = spy
        try:
            cls.world, cls.bl = cls.build(PACKED_BUILDING, seed=1)
        finally:
            assembler._lay_split = orig
        cls.ctx, cls.design = captured["ctx"], captured["design"]
        cls.ctx.sleepers = {"Bedroom": (2, 0), "Guest Chamber": (2, 0),
                            "Guest Room": (2, 0), "Servant Room": (2, 0),
                            "Privy": (0, 0)}
        cls.ctx._size_catalogues = {}
        cls.storey = assembler.partition_storey(
            cls.ctx, cls.design, cls.SPECS, cls.RECT, cls.ANCHOR,
            "modest", "kept", 2)

    def test_the_split_hands_the_narrow_slot_to_the_privy(self):
        rooms = {r.name: r.rect for r in self.storey.rooms}
        # every bedchamber kept a bedchamber's room — the servant room the
        # equal tiles closet included — and the run's notes stay silent
        for n in ("Bedroom", "Guest Chamber", "Guest Room",
                  "Servant Room"):
            self.assertEqual((rooms[n].w, rooms[n].h), (5, 8), n)
        # the one 4-wide tile goes to the room whose catalogue has a
        # 4-wide turn: the privy
        self.assertEqual((rooms["Privy"].w, rooms["Privy"].h), (4, 5))
        self.assertEqual(self.storey.notes, [])

    def test_the_equal_tiles_closet_the_last_bedchamber(self):
        orig = assembler._ranked_splits
        assembler._ranked_splits = lambda *a, **k: []
        try:
            storey = assembler.partition_storey(
                self.ctx, self.design, self.SPECS, self.RECT, self.ANCHOR,
                "modest", "kept", 2)
        finally:
            assembler._ranked_splits = orig
        self.assertIn(("Servant Room",
                       "storey 2 slot took a closet instead: "
                       "no bedroom room of the pool fits"),
                      storey.notes)

    def test_the_rooms_tile_the_outline_without_overlap(self):
        for i, a in enumerate(self.storey.rooms):
            self.assertTrue(self.RECT.contains_rect(a.rect), a.name)
            for b in self.storey.rooms[i + 1:]:
                self.assertFalse(a.rect.intersects(b.rect),
                                 (a.name, b.name))


class TestTheBandSplitProgram(unittest.TestCase):
    """The exact 1D split (rl-16) on the example it was specced from: a
    band 10 cells long and 5 deep — its floor 3 across — a catalogue whose
    rooms give outer footprints 5x3, 4x4, 7x5 and 7x7. The 7x7 fits
    neither turn at that depth, the 7x5 only the turn 5 cells along, and
    the rooms tile side by side each keeping its own walls, so a 10-cell
    band seats the 5-wide footprint beside the 4-wide one with one cell to
    spare — a band one cell longer packs the 7-wide turn against the far
    wall with no slack at all."""

    CATALOGUE = [
        {"id": "five-by-three", "size": [3, 1],
         "doors": {"north": [1], "south": [0, 1, 2], "east": [0],
                   "west": [0]}},
        {"id": "four-by-four", "size": [2, 2],
         "doors": {"north": [0, 1], "south": [0, 1], "east": [0, 1],
                   "west": [0, 1]}},
        {"id": "seven-by-five", "size": [5, 3],
         "doors": {"north": [0, 1, 2, 3, 4], "south": [0, 1, 2, 3, 4],
                   "east": [0, 1, 2], "west": [0, 1, 2]}},
        {"id": "seven-by-seven", "size": [5, 5],
         "doors": {"north": [0, 1, 2, 3, 4], "south": [0, 1, 2, 3, 4],
                   "east": [0, 1, 2, 3, 4], "west": [0, 1, 2, 3, 4]}}]

    def test_the_depth_drops_sizes_and_keeps_the_fitting_turns(self):
        entries = assembler._oriented_sizes(self.CATALOGUE)
        # the band is 5 cells deep less its wall pair: 3 across
        self.assertEqual(
            assembler._catalogue_widths(entries, "south", 3, True),
            [3, 4, 5, 7])

    def test_the_best_split_packs_the_band_with_no_slack(self):
        # the 7-wide turn and the 4-wide room want 11 cells together: the
        # 10-cell band takes the 5-wide footprint instead, one cell spare
        splits = assembler._band_splits(
            10, [[(3, 0), (4, 0), (5, 0), (7, 0)], [(4, 0)]])
        self.assertEqual(splits, [((5, 4), 1), ((4, 4), 2), ((3, 4), 3)])
        # one cell more and the 7x5's fitting turn packs exactly
        splits = assembler._band_splits(
            11, [[(3, 0), (4, 0), (5, 0), (7, 0)], [(4, 0)]])
        self.assertEqual(splits[0], ((7, 4), 0), splits)

    def test_a_width_that_loses_beds_ranks_behind_the_full_ask(self):
        # a wider room would pack tighter, but it costs three beds: the
        # split that seats the full ask wins first
        splits = assembler._band_splits(10, [[(5, 0), (6, 3)], [(4, 0)]])
        self.assertEqual(splits[0], ((5, 4), 1), splits)


class TestAPlannedWidthTriesOnlyTheFullAsk(StoreyCase):
    """rl-19: a slot the size-first split planned around one width tries
    only the full ask — no room of that width sleeping everyone the spec
    was asked to take misses the split, and the caller falls to the next
    ranked split, never a smaller bedroom squeezed into the planned width.
    The slot is the real one a build's split planned; its pool is replaced
    by one holding a room of the width only for a smaller ask."""

    @classmethod
    def setUpClass(cls):
        captured = []
        orig = assembler._fill_slot

        def spy(ctx, design, sasm, spec, slot, facing, horizontal, tier,
                rng, storey, target=None):
            if spec is not None and target is not None and not captured:
                captured.append((ctx, design, sasm, spec, slot, facing,
                                 horizontal, tier, storey, target))
            return orig(ctx, design, sasm, spec, slot, facing, horizontal,
                        tier, rng, storey, target=target)

        assembler._fill_slot = spy
        try:
            cls.world, cls.bl = cls.build(PACKED_BUILDING, seed=1)
        finally:
            assembler._fill_slot = orig
        (cls.ctx, cls.design, cls.sasm, cls.spec, cls.slot, cls.facing,
         cls.horizontal, cls.tier, cls.storey, cls.target) = captured[0]

    def test_no_room_of_the_width_sleeping_everyone_misses_the_split(self):
        W = self.target
        # the planned width's only room sleeps fewer than the four asked
        fake = {"id": "planned.width.two.bed",
                "size": [W, 2] if self.horizontal else [2, W],
                "doors": {"north": list(range(W if self.horizontal else 2)),
                          "south": list(range(W if self.horizontal else 2)),
                          "west": list(range(2 if self.horizontal else W)),
                          "east": list(range(2 if self.horizontal else W))}}
        orig_pool = assembler._room_pool

        def pool(ctx, design, spec, fam, tier, rng):
            if ctx.sleepers.get(spec.name) == (4, 0):
                return [], "no room of the width sleeps four"
            return [dict(fake)], ""

        self.ctx.sleepers[self.spec.name] = (4, 0)
        notes = list(self.sasm.notes)
        assembler._room_pool = pool
        try:
            with self.assertRaises(assembler._SplitMiss):
                assembler._fill_slot(
                    self.ctx, self.design, self.sasm, self.spec, self.slot,
                    self.facing, self.horizontal, self.tier,
                    random.Random(0), self.storey, target=W)
        finally:
            assembler._room_pool = orig_pool
        # never a smaller bedroom: the miss left no note behind
        self.assertEqual(self.sasm.notes, notes)


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
