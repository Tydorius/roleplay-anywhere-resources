"""Room library step 5a: the room assembler lays one-storey library buildings
out of the library's own fixed rooms (``--room-assembler``, off by default).
With the switch off nothing changes — the two model fixture plans still build
byte-identical specs (and the flag on them changes nothing either: no room of
theirs names a library purpose). A library cottage assembles with its rooms
reached from the entrance, doors on shared walls, no overlap and every piece
inside its room; a purpose the library does not know falls back to the old
method with the reason recorded; the same seed gives the same building; a
bedroom picked for two residents sleeps two. A fixed family with no stored
fit composes its room on the spot (noted in the run's notes, never a
fallback); a share whose band gives nothing takes the family's next band one
step larger first; the live run's tenant cottage assembles, its children's
loft sleeping two.

rl-09 adds the wing mode: the same design asked to fill a target rectangle
(``wing_footprint`` / ``wing_build``) fills it exactly with its entrance
and outward doors pinned to the ring, no piece on a pinned cell and every
room still reached; a target the closers cannot meet still assembles and
reports the rectangle it grew to; a door pin no room can honour falls the
ask back with the reason, an entrance pin takes the free pick and says so.
A compound's parts are buildings like any other — the ashvale fixture's
parts, given library uses, qualify: every one of them assembles (towers,
gatehouse and keep included, their upper storeys partitioned to fit), the
doors the compound opens between touching parts clear of furniture, every
entrance reached from the road and the checks clean; the use keys change
nothing with the switch off."""
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
    # the parsed design reads residents, couples, wealth and condition from
    # the zone's building entry, so a change has to reach both
    zone_b = data["zones"][0]["buildings"][0]
    for key, value in changes.items():
        if key in ("wealth", "condition", "residents", "couples"):
            building[key] = value
            zone_b[key] = value
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
                                 out_dir=os.path.join(tmp, "off"),
                                 room_assembler=False)
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


# the live run's tenant cottage: the plan whose children's loft (two singles,
# poor, tight) once missed every stored bedroom and fell back
TENANT_COTTAGE_PLAN = {
    "name": "Millet Hollow",
    "worldBackground": "A forgotten village.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Millet Hollow", "kind": "village", "sizeClass": "medium",
        "description": "The hollow.", "ground": "grass", "adjacentTo": [],
        "outdoor": [], "buildings": [
            {"name": "Tenant Cottage", "kind": "cottage", "sizeClass": "small",
             "purpose": "a cotter's home", "residents": 4, "couples": 1,
             "wealth": "poor", "yard": None}],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [],
    "templates": [],
    "buildings": [
        {"name": "Tenant Cottage", "wall": "wood", "ground": "wood",
         "residents": 4, "couples": 1, "wealth": "poor", "condition": "kept",
         "rooms": [
             {"name": "Hearth Room", "share": "large", "use": "living_room",
              "purpose": "the fire and the pot"},
             {"name": "Bedchamber", "share": "medium", "use": "master_bedroom",
              "purpose": "the cotter's bed"},
             {"name": "Children's Loft", "share": "small", "use": "bedroom",
              "purpose": "the children sleep tight under the eaves"}],
         "connections": [["Hearth Room", "Bedchamber"],
                         ["Hearth Room", "Children's Loft"]],
         "entrance": {"room": "Hearth Room", "side": "south"},
         "furniture": [], "yard": None},
    ],
    "npcs": [],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "Tenant Cottage", "work": "Millet Hollow",
               "description": "Passing through.", "physicalDescription": "cloaked"},
}


class TestTheTenantCottageAssembles(unittest.TestCase):
    """The live run's fallback: a children's loft for two singles at small,
    tight and poor, before the two-sleeper bedrooms shipped."""

    def test_the_cottage_assembles_and_the_loft_sleeps_two(self):
        world = worldgen.run(TENANT_COTTAGE_PLAN, seed=1, room_assembler=True)
        bl = assembled(world, "Tenant Cottage")
        self.assertIsNotNone(bl, "no building in the world")
        self.assertTrue(getattr(bl, "assembled", False),
                        [f for f in world.fallbacks
                         if f[0] == "building Tenant Cottage"])
        self.assertEqual(len(bl.rooms), 3, [r.base_name for r in bl.rooms])
        beds = 0
        for o in world.objects:
            if not o.region.endswith("Children's Loft"):
                continue
            t = world.templates[o.template]
            if t.for_sleep:
                beds += bed_capacity(t)
        self.assertGreaterEqual(beds, 2, "two children, no two beds")


class TestBuildOnTheSpot(unittest.TestCase):
    """A fixed family with no stored fit composes its room live — noted as a
    run note, never a fallback."""

    def test_a_bedroom_for_three_singles_builds_on_the_spot(self):
        world = worldgen.run(cottage_plan(residents=3, couples=0, use="bedroom"),
                             seed=7, room_assembler=True)
        bl = assembled(world)
        self.assertTrue(getattr(bl, "assembled", False), world.fallbacks)
        notes = [n for n in world.notes if n[0] == "room Bedroom in building Rose Cottage"]
        self.assertEqual(len(notes), 1, world.notes)
        self.assertIn("built on the spot", notes[0][1])
        self.assertFalse([f for f in world.fallbacks
                          if f[0] == "building Rose Cottage"], world.fallbacks)
        beds = 0
        for o in world.objects:
            if not o.region.endswith("Bedroom"):
                continue
            t = world.templates[o.template]
            if t.for_sleep:
                beds += bed_capacity(t)
        self.assertGreaterEqual(beds, 3, "three residents, no three beds")

    def test_a_stored_fit_leaves_no_note(self):
        world = worldgen.run(cottage_plan(residents=2, couples=0, use="bedroom"),
                             seed=7, room_assembler=True)
        bl = assembled(world)
        self.assertTrue(getattr(bl, "assembled", False), world.fallbacks)
        self.assertEqual([n for n in world.notes
                          if "Bedroom" in n[0] and "built on the spot" in n[1]],
                         [], world.notes)


class TestBandTolerance(unittest.TestCase):
    """A share whose band gives nothing takes the family's neighbouring band,
    one step larger first (the live run's sickroom: a ward that cannot fit
    two beds at small composes at medium)."""

    def test_a_ward_share_small_takes_the_medium_band(self):
        import random
        from worldgen import assembler, model
        plan_data = {"name": "c", "setting": {"era": "medieval",
                                               "technology": "iron",
                                               "density": "normal",
                                               "climate": "mild"},
                     "zones": [{"name": "Z", "kind": "village",
                                "sizeClass": "medium", "adjacentTo": [],
                                "outdoor": [], "buildings": [],
                                "dressing": {"paths": "dirt", "props": [],
                                             "filler": []}}],
                     "roads": [], "templates": [], "buildings": [], "npcs": [],
                     "player": {"name": "x"}}
        ctx = assembler.activate(model.parse_plan(plan_data), plan_data, "c", {})
        try:
            from worldgen.model import BuildingDesign, RoomSpec
            d = BuildingDesign(name="Hut", kind="clinic", wealth="poor",
                               condition="kept", residents=1,
                               rooms=[RoomSpec(name="Sickroom", share="small",
                                               use="infirmary", purpose="")],
                               connections=[], entrance_room="Sickroom",
                               entrance_side="south")
            pool, reason = assembler._room_pool(ctx, d, d.rooms[0], "ward",
                                                 "poor", random.Random(0))
            self.assertTrue(pool, reason)
            self.assertEqual({r.get("sizeBand") for r in pool}, {"medium"},
                             [r.get("id") or r.get("size") for r in pool])
        finally:
            assembler.deactivate()



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


class TestAnEndOnBathFindsAnObject(unittest.TestCase):
    """The shipped washrooms set their bath end-on to the wall (a 2x1 piece
    backing west), while every bath object backs on its long side: no object
    faces that way, so one that covers the piece's cells must do, or every
    such washroom falls back."""

    def test_a_bath_backing_on_its_short_side_picks_an_object(self):
        import random
        from worldgen import assembler, model
        for era, band in (("modern", "modern"), ("scifi", "scifi")):
            plan_data = {"name": "c", "setting": {"era": era, "technology": "iron",
                                                  "density": "normal", "climate": "mild"},
                         "zones": [{"name": "Z", "kind": "village", "sizeClass": "medium",
                                    "adjacentTo": [], "outdoor": [], "buildings": [],
                                    "dressing": {"paths": "dirt", "props": [], "filler": []}}],
                         "roads": [], "templates": [], "buildings": [], "npcs": [],
                         "player": {"name": "x"}}
            ctx = assembler.activate(model.parse_plan(plan_data), plan_data, "c", {})
            try:
                self.assertEqual(ctx.band, band)
                piece = {"role": "wash.bath", "size": [2, 1], "at": [0, 0], "back": "west"}
                obj, _rot, _tier, why = assembler._pick_for(
                    ctx, "washroom", piece, "modest", random.Random(0))
                with self.subTest(band=band):
                    self.assertIsNotNone(obj, why)
                    self.assertEqual(obj["category"], "bath")
            finally:
                assembler.deactivate()


# the live floors run's waystation (out/sundered-forgotten-village-floors):
# its bunk room — guests, no residents — once resolved its anchor to zero
# copies and fell back
WAYSTATION_BUNK_ROOM_PLAN = {
    "name": "The Sundered Boundary",
    "worldBackground": "A forgotten village's western waystation.",
    "setting": {"era": "1200 years after the Sundering",
                "technology": "medieval Xianxia with qi-based cultivation",
                "density": "sparse", "climate": "thin dry mountain air",
                "band": "medieval", "genre": "xianxia"},
    "mapSize": "small",
    "zones": [{
        "name": "Western Waystation", "kind": "station",
        "sizeClass": "medium", "description": "The roadside waystation.",
        "ground": "dirt", "adjacentTo": [], "outdoor": [],
        "buildings": [{"name": "Waystation Bunk Room", "kind": "dormitory",
                       "sizeClass": "small", "purpose": "bunk lodging",
                       "wealth": "modest", "condition": "kept",
                       "status": "staffed", "yard": None}],
        "dressing": {"paths": "dirt", "props": [], "filler": []}}],
    "roads": [],
    "templates": [],
    "buildings": [
        {"name": "Waystation Bunk Room", "wall": "wood",
         "ground": "packed earth", "wealth": {}, "yard": None,
         "rooms": [{"name": "Bunk Room", "share": "small",
                    "use": "dormitory",
                    "purpose": "A cramped bunk room for exhausted roadside travellers."}],
         "connections": [], "entrance": {"room": "Bunk Room", "side": "north"},
         "furniture": [], "upper": [], "stairs": None}],
    "npcs": [],
    "player": {"name": "The Wanderer", "gender": "female",
               "role": "traveller", "home": "Waystation Bunk Room",
               "work": "Western Waystation", "description": "Passing through.",
               "physicalDescription": "cloaked"},
}


class TestGuestRoomsGetBeds(unittest.TestCase):
    """rl-06d: a room for guests or lodgers no residents were assigned to
    takes the family's usual occupancy, so the beds are always furnished."""

    def test_the_bunk_room_assembles_with_a_bed(self):
        world = worldgen.run(WAYSTATION_BUNK_ROOM_PLAN, seed=1,
                             room_assembler=True)
        bl = assembled(world, "Waystation Bunk Room")
        self.assertIsNotNone(bl, "no building in the world")
        self.assertTrue(getattr(bl, "assembled", False),
                        [f for f in world.fallbacks
                         if "Bunk Room" in f[0]])
        beds = 0
        for o in world.objects:
            if not o.region.endswith("Bunk Room"):
                continue
            t = world.templates[o.template]
            if t.for_sleep:
                beds += bed_capacity(t)
        self.assertGreaterEqual(beds, 1, "a guest room, no bed")

    def test_an_empty_dormitory_sleeps_two_or_more(self):
        # rl-15: a dormitory is a shared room — barracks and crew quarters
        # are the same family — so its fallback occupancy is the family's
        # own, never the composer's floor of one
        world = worldgen.run(json.loads(json.dumps(WAYSTATION_BUNK_ROOM_PLAN)),
                             seed=2, room_assembler=True)
        beds = 0
        for o in world.objects:
            if not o.region.endswith("Bunk Room"):
                continue
            t = world.templates[o.template]
            if t.for_sleep:
                beds += bed_capacity(t)
        self.assertGreaterEqual(beds, 2, "a shared room, one bed")


class TestABarnGetsAHayloft(unittest.TestCase):
    """rl-06d: a barn standing at two storeys gets a hayloft upstairs —
    hay storage (the barn purpose: feed, sacks, crates, barrels), never
    beds."""

    BARN_P3 = {"name": "The Old Barn", "suite": None, "wall": "wood",
               "ground": "packed earth",
               "rooms": [{"name": "Barn floor", "share": "large",
                          "use": "barn",
                          "purpose": "hay and the stalls through winter"},
                         {"name": "Tack corner", "share": "small",
                          "use": "storage",
                          "purpose": "harnesses and pitchforks"}],
               "connections": [["Barn floor", "Tack corner"]],
               "entrance": {"room": "Barn floor", "side": "south"},
               "stairs": {"room": "Barn floor"},
               "wealth": {}, "yard": None}

    def test_the_upper_storey_is_a_hayloft_not_beds(self):
        from tests.test_library_generate import LIB_P3
        from tests.test_model import (CANNED_COTTAGE, CANNED_MILL, CANNED_P1,
                                      ScriptedClient, _dump, canned_replies)

        class BarnClient(ScriptedClient):
            # every p3 call gets a design: the barn's for the barn, the
            # library's loft-bearing one for the mill and the cottage
            def call(self, phase, system, user, validate=None, max_retries=2):
                if phase.startswith("p3-"):
                    reply = self.BARN_P3 if "The Old Barn" in user else LIB_P3
                    self._queue.insert(0, _dump(reply))
                return super().call(phase, system, user, validate, max_retries)

        p1 = json.loads(json.dumps(CANNED_P1))
        p1["zones"][0]["buildings"].append(
            {"name": "The Old Barn", "kind": "barn", "sizeClass": "large",
             "purpose": "hay and stalls through winter", "storeys": 2,
             "yard": None})
        queue = [r for r in canned_replies()
                 if r not in (_dump(CANNED_MILL), _dump(CANNED_COTTAGE))]
        queue[0] = _dump(p1)      # the canned P1 with the barn added
        client = BarnClient(queue)
        client.BARN_P3 = self.BARN_P3
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=client, seed=3,
                                   cast=False, out_dir=tmp)
            self.assertTrue(summary["ok"], summary)
            with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
            again = api.relayout(os.path.join(tmp, "plan.json"), seed=4,
                                 out_dir=os.path.join(tmp, "again"))
            self.assertTrue(again["ok"], again)
        barn = next(b for b in plan["buildings"] if b["name"] == "The Old Barn")
        self.assertEqual([r["name"] for r in barn["rooms"]],
                         ["Barn floor", "Tack corner"])
        upper = barn["upper"]
        self.assertEqual(len(upper), 1, upper)
        self.assertEqual(upper[0]["storey"], 2)
        self.assertEqual([r["name"] for r in upper[0]["rooms"]], ["Hayloft"])
        self.assertEqual(upper[0]["rooms"][0]["use"], "hayloft")
        t_by_name = {t["name"]: t for t in plan["templates"]}
        sleep_upstairs = [f["template"] for f in upper[0].get("furniture") or []
                          if t_by_name[f["template"]].get("forSleep")]
        self.assertFalse(sleep_upstairs, sleep_upstairs)
        self.assertTrue(upper[0].get("furniture"), "the loft shipped empty")


class TestARerunOverOnePlan(unittest.TestCase):
    """rl-22: a second run over the same plan dict (the relayout path) must
    not re-add the templates the first run injected: each library template
    enters the plan once and the re-run parses. The first run's world is not
    the second's (the registry's reuse preference, on from the first carried
    templates, is the old behavior) — but from the second run on the plan is
    a record, and the same seed builds the same spec again."""

    def test_each_template_enters_once_and_reruns_settle(self):
        plan = json.loads(json.dumps(COTTAGE_PLAN))
        worldgen.run(plan, seed=5)
        names = [t["name"] for t in plan["templates"]]
        self.assertEqual(len(names), len(set(names)),
                         "a template entered the plan twice")
        second = worldgen.run(plan, seed=5)
        spec = worldgen.build_spec(second, plan)
        self.assertEqual([t["name"] for t in plan["templates"]], names)
        third = worldgen.run(plan, seed=5)
        self.assertEqual(worldgen.build_spec(third, plan), spec)


WING_PLAN = {
    "name": "Wingmere", "worldBackground": "A keep wing.",
    "setting": {"era": "medieval", "technology": "iron",
                "density": "normal", "climate": "mild"},
    "mapSize": "small",
    "zones": [{
        "name": "Wingmere", "kind": "village", "sizeClass": "small",
        "description": "The green.", "ground": "grass",
        "adjacentTo": ["The Ford"], "outdoor": [], "buildings": [
            {"name": "Wing Hall", "kind": "house", "sizeClass": "small",
             "purpose": "a wing", "residents": 4, "yard": None}],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }, {
        "name": "The Ford", "kind": "farmland", "sizeClass": "medium",
        "description": "Meadows.", "ground": "grass",
        "adjacentTo": ["Wingmere"], "outdoor": [], "buildings": [],
        "dressing": {"paths": "dirt", "props": [], "filler": []},
    }],
    "roads": [{"from": "Wingmere", "to": "The Ford", "kind": "dirt"}],
    "templates": [],
    "buildings": [
        {"name": "Wing Hall", "wall": "wood", "ground": "wood",
         "residents": 4, "couples": 2, "wealth": "modest", "condition": "kept",
         "rooms": [
             {"name": "Hall", "share": "medium", "use": "lobby",
              "purpose": "the door"},
             {"name": "Main Room", "share": "medium", "use": "living_room",
              "purpose": "hearth and table"},
             {"name": "Bedroom", "share": "small", "use": "master_bedroom",
              "purpose": "the bed"},
             {"name": "Pantry", "share": "small", "use": "cellar",
              "purpose": "stores"}],
         "connections": [["Hall", "Main Room"], ["Main Room", "Bedroom"],
                         ["Hall", "Pantry"]],
         "entrance": {"room": "Hall", "side": "south"},
         "furniture": [], "yard": None},
    ],
    "npcs": [],
    "player": {"name": "The Wanderer", "gender": "female", "role": "traveller",
               "home": "Wing Hall", "work": "Wingmere",
               "description": "Passing through.", "physicalDescription":
               "cloaked"},
}

# the ashvale parts' rooms mapped to library purposes, so the fixture's
# model plan qualifies where its purposes are ones the library knows
ASHVALE_USES = {
    "Northwest Tower": {"Guard Room": "guardroom", "Watch Room": "guardroom",
                        "Lookout": "guardroom"},
    "Northeast Tower": {"Guard Room": "guardroom", "Watch Room": "guardroom",
                        "Lookout": "guardroom"},
    "Southeast Tower": {"Guard Room": "guardroom", "Watch Room": "guardroom",
                        "Lookout": "guardroom"},
    "Southwest Tower": {"Guard Room": "guardroom", "Watch Room": "guardroom",
                        "Lookout": "guardroom"},
    "Gatehouse": {"Gate Passage": "hallway", "Gate Chamber": "guardroom",
                  "Gate Watch": "guardroom"},
    "Ashvale Keep": {"Great Hall": "great_hall", "Lord's Chamber":
                     "master_bedroom", "Solar": "master_bedroom"},
    "Garrison Barracks": {"Barracks Floor": "barracks", "Store": "cellar"},
}


def wing_plan():
    return json.loads(json.dumps(WING_PLAN))


class TestAWingFillsItsTarget(unittest.TestCase):
    """rl-09: the assembler's wing mode. A four-room design asked to fill a
    target rectangle does — its entrance and one outward door pinned to the
    ring, both honoured, no piece on a pinned cell, every room reached, and
    no fallback or note anywhere."""

    def setUp(self):
        from worldgen import assembler, model
        self.plan = wing_plan()
        self.parsed = model.parse_plan(self.plan)
        self.design = next(d for d in self.parsed.zones[0].buildings
                           if d.name == "Wing Hall")
        self.ctx = assembler.activate(self.parsed, self.plan, "s", {})
        self.addCleanup(assembler.deactivate)

    def furniture_cells(self, bl):
        cells = set()
        for room in bl.rooms:
            for (tname, pos) in room.furniture.placements:
                tw, th = self.ctx.world_templates[tname].size
                cells |= {(pos[0] + dx, pos[1] + dy)
                          for dx in range(tw) for dy in range(th)}
        return cells

    def rooms_reached(self, bl):
        """The rooms a walk from the entrance reaches over the door pairs."""
        rooms = bl.rooms
        entry = next(r for r in rooms if r.rect.contains_cell(bl.entrance_door))
        seen, queue = {id(entry)}, [entry]
        while queue:
            room = queue.pop()
            for (a, b) in bl.door_pairs:
                nxt = None
                if room.rect.contains_cell(a):
                    nxt = next((q for q in rooms if q is not room
                                and q.rect.contains_cell(b)), None)
                elif room.rect.contains_cell(b):
                    nxt = next((q for q in rooms if q is not room
                                and q.rect.contains_cell(a)), None)
                if nxt is not None and id(nxt) not in seen:
                    seen.add(id(nxt))
                    queue.append(nxt)
        return {r.base_name for r in rooms if id(r) in seen}

    def test_four_rooms_fill_the_target_with_two_pinned_doors(self):
        from worldgen import assembler
        bl = assembler.wing_build(self.design, (0, 0), (18, 12),
                                  entrance=("south", 8), doors=[("east", 4)])
        self.assertIsNotNone(bl, assembler.fallback_note("Wing Hall"))
        self.assertTrue(getattr(bl, "assembled", False))
        # the footprint is the target, and nothing fell back or was noted
        self.assertEqual((bl.rect.w, bl.rect.h), (18, 12),
                         (bl.rect, [r.base_name for r in bl.rooms]))
        self.assertIsNone(assembler.fallback_note("Wing Hall"))
        self.assertEqual(assembler.spot_notes("Wing Hall", "south"), [])
        # the pinned entrance: south offset 8 of an 18-wide target, on the
        # target's south (low) edge
        self.assertEqual(bl.entrance_door, (9, 0))
        # the pinned east door at offset 4, opened by exactly one room
        pin = (17, 5)
        owners = [r for r in bl.rooms if pin in r.doors]
        self.assertEqual(len(owners), 1, [(r.base_name, sorted(r.doors))
                                          for r in bl.rooms])
        # every room of the wing is reached from the entrance, the pin's
        # owner among them
        reached = self.rooms_reached(bl)
        self.assertEqual(reached, {r.base_name for r in bl.rooms}, reached)
        self.assertIn(owners[0].base_name, reached)
        # no piece stands on a pinned door cell
        cells = self.furniture_cells(bl)
        self.assertNotIn(bl.entrance_door, cells)
        self.assertNotIn(pin, cells)

    def test_an_over_large_target_reports_the_rectangle_it_grew_to(self):
        from worldgen import assembler
        fp = assembler.wing_footprint(self.design, (30, 20))
        self.assertIsNotNone(fp, assembler.fallback_note("Wing Hall"))
        self.assertEqual(fp, (29, 20))
        notes = assembler.spot_notes("Wing Hall", "south")
        self.assertTrue(any("fills 29x20 of the 30x20 target" in note
                            for (_label, note) in notes), notes)

    def test_a_door_pin_no_room_can_honour_falls_back_with_the_reason(self):
        from worldgen import assembler
        # the target's corner cell can never open a door
        fp = assembler.wing_footprint(self.design, (18, 12),
                                      doors=[("south", 16)])
        self.assertIsNone(fp)
        note = assembler.fallback_note("Wing Hall")
        self.assertIsNotNone(note)
        self.assertIn("the pinned south door at offset 16", note[1])

    def test_an_entrance_pin_no_room_can_honour_takes_the_free_pick(self):
        from worldgen import assembler
        bl = assembler.wing_build(self.design, (0, 0), (18, 12),
                                  entrance=("south", 16))
        self.assertIsNotNone(bl, assembler.fallback_note("Wing Hall"))
        self.assertNotEqual(bl.entrance_door, (17, 0))
        notes = assembler.spot_notes("Wing Hall", "south")
        self.assertTrue(any("could not be opened" in note
                            for (_label, note) in notes), notes)


class TestCompoundPartsAssemble(unittest.TestCase):
    """rl-09/rl-15: a compound's parts are buildings like any other — the
    assembler no longer refuses them by name. The ashvale fixture's parts,
    given library uses, all qualify: the towers, the gatehouse and the keep
    assemble with their upper storeys, every door the compound opens between
    touching parts clear of furniture, every entrance reached from the road
    and the checks clean."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(FIXTURES, "ashvale-compound.plan.json"),
                  encoding="utf-8") as f:
            cls.base = json.load(f)

    def plan_with_uses(self):
        data = json.loads(json.dumps(self.base))
        for b in data["buildings"]:
            uses = ASHVALE_USES.get(b["name"])
            if not uses:
                continue
            for r in b["rooms"]:
                r["use"] = uses[r["name"]]
            for s in b.get("upper") or []:
                for r in s["rooms"]:
                    r["use"] = uses[r["name"]]
        return data

    def test_the_qualifying_parts_assemble_with_the_compound_doors_clear(self):
        from worldgen.layout_compound import shared_wall_cells
        world = worldgen.run(self.plan_with_uses(), seed=1,
                             room_assembler=True)
        m = world.metrics
        self.assertEqual(m["region_overlaps"], [])
        self.assertEqual(m["object_overlaps"], [])
        self.assertEqual(m["reachability"], 1.0)
        self.assertTrue(m["doors_clear"])
        self.assertTrue(m["walkways_clear"])
        made = sorted(b.layout.design.name for b in world.buildings
                      if b.compound and getattr(b.layout, "assembled", False))
        # every part of the castle assembles — towers, gatehouse and keep
        # with their upper storeys partitioned to fit — and none falls back
        self.assertEqual(made, ["Ashvale Keep", "Garrison Barracks", "Gatehouse",
                                "Northeast Tower", "Northwest Tower",
                                "Southeast Tower", "Southwest Tower"],
                         world.fallbacks)
        fell = {label[len("building "):] for (label, _reason)
                in world.fallbacks if label.startswith("building ")}
        self.assertEqual(fell, set(), world.fallbacks)
        # every door the compound opened on an assembled part: no piece on
        # the cell, and it opened in exactly one of the part's rooms. A part
        # that stands clear (the keep, its walking room round it) carries
        # none and owes none
        for comp in world.compounds:
            for b in comp.parts:
                if not getattr(b.layout, "assembled", False):
                    continue
                rects = [o.layout.rect for o in comp.parts if o is not b]
                rects += [c.rect for c in comp.corridors]
                touches = any(shared_wall_cells(b.layout.rect, r)
                              for r in rects)
                cells = set()
                for room in b.layout.rooms:
                    for (tname, pos) in room.furniture.placements:
                        tw, th = world.templates[tname].size
                        cells |= {(pos[0] + dx, pos[1] + dy)
                                  for dx in range(tw) for dy in range(th)}
                extra = getattr(b.layout, "extra_doors", None) or []
                self.assertEqual(bool(extra), touches,
                                 (b.layout.design.name, extra))
                for door in extra:
                    self.assertNotIn(door, cells,
                                     (b.layout.design.name, door))
                    owners = [r for r in b.layout.rooms if door in r.doors]
                    self.assertEqual(len(owners), 1,
                                     (b.layout.design.name, door))

    def test_the_use_keys_change_nothing_with_the_switch_off(self):
        with open(os.path.join(DATA, "compound-off-ashvale.json"),
                  encoding="utf-8") as f:
            want = json.load(f)["spec"]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ashvale.plan.json")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(self.plan_with_uses(), f)
            api.relayout(path, seed=1, out_dir=os.path.join(tmp, "off"),
                         room_assembler=False)
            with open(os.path.join(tmp, "off", "spec.py"),
                      encoding="utf-8", newline="") as f:
                self.assertEqual(f.read(), want)
