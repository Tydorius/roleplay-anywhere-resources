"""Brief 012 feasibility: hand-written builder specs that prove the four
arrangements the compound layout relies on, run through the vendored builder
and validator in-process. The findings and the choices they pick are written
up in reports/012-feasibility.md.

1. Doors between parts: two walled regions that touch with one wall line
   each (edges one cell apart) auto-connect in the builder when they share a
   parent, and the door opens into rooms on both sides when the room behind
   the shared wall spans the door cell (a full-width strip room, which is
   what the room layout gives a part whose entrance faces the courtyard).
2. Thin walkable walls: a 3-wide walled corridor with a 1-cell interior
   builds, validates, is reached and walked end to end.
3. Solid walls: a walkability-0 object strip blocks movement, claims no
   wall cell of the walled regions it runs between, and leaves the parts
   reachable through their own doors.
4. Upper storeys that touch: two storey regions placed touching in the band
   auto-connect (same parent: the boundary region), and the floors payload
   still maps each storey to its own building. The seal's behaviour with
   the shared door is asserted as it stands today and flipped when the
   compound storeys land (change 4): see test_seal_keeps_inter_storey_doors.
"""
import json
import os
import shutil
import tempfile
import unittest

from worldgen.vendor import validate_scenario
from worldgen.vendor.build_scenario import Builder


def _region(name, pos, size, wall=None, doors=(), ground="grass"):
    r = {"name": name, "position": list(pos), "size": list(size),
         "ground": ground, "groundTexture": ground, "description": name}
    if wall:
        r["wall"] = wall
        r["doors"] = [list(d) if not isinstance(d, str) else d for d in doors]
    return r


def _object(name, size, walkability, placements):
    return {"name": name, "size": list(size), "walkability": walkability,
            "description": name, "physicalDescription": name,
            "tags": ["wall"], "placements": [list(p) for p in placements]}


def _spec(regions, objects=(), grid=(40, 30), player=(1, 1), player_region=None):
    return {
        "name": "Feasibility", "worldBackground": "A test world.", "seed": "7",
        "gridSize": list(grid),
        "defaultTile": {"name": "Meadow", "ground": "grass", "groundTexture": "grass",
                        "ambience": {"day": "nature_outdoors"}},
        "currency": {"name": "Penny", "description": "Small coin.", "format": "5 pennies"},
        "attributes": {"strength": 5, "dexterity": 4, "intellect": 4,
                       "perception": 5, "charisma": 5},
        "regions": list(regions),
        "objectTemplates": list(objects),
        "npcs": [],
        "player": {"name": "Walker", "gender": "female", "description": "Walks.",
                   "physicalDescription": "A walker.",
                   "pos": list(player),
                   "animationId": "casual-woman",
                   "voiceProfile": {"gender": "Female", "age": ["Adult"],
                                    "pitch": ["Average"], "tags": []},
                   "schedule": [{"start": "00:00", "end": "00:00",
                                 "location": player_region or regions[0]["name"],
                                 "role": "leisure"}]},
    }


def _build(spec):
    """Run the vendored builder in-process. Returns the Builder after the
    full pipeline, with zero errors or the assertion context says why not."""
    tmp = tempfile.mkdtemp(prefix="worldgen-feas-")
    try:
        b = Builder(spec, tmp)
        b.build_regions()
        b.build_items()
        b.build_objects()
        b.build_hostile_templates()
        b.build_entities()
        b.build_systems()
        return b
    finally:
        pass


def _flood(b):
    """The builder's own reachability walk, as a cell set from the player."""
    doors = {tuple(c) for r in b.regions for c in r["openings"]}
    blocked = {c for c in b._wall_cells if c not in doors}
        # objects that block in play block at build too
    tpl = {t["id"]: t for t in b.objects}
    for e in b.entities:
        if e["type"] == "object":
            if tpl[e["templateId"]].get("walkability", 0) == 0:
                blocked.update((x, y) for x in range(e["pos"][0], e["pos"][0] + e["size"][0])
                               for y in range(e["pos"][1], e["pos"][1] + e["size"][1]))
    W, H = b.s["gridSize"]
    start = tuple(b.player["pos"])
    seen, todo = {start}, [start]
    while todo:
        x, y = todo.pop()
        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= c[0] < W and 0 <= c[1] < H and c not in seen and c not in blocked:
                seen.add(c)
                todo.append(c)
    return seen, blocked


def _openings(b):
    return {r["name"]: {tuple(c) for c in r["openings"]} for r in b.regions}


def _interior(rect):
    (x, y), (w, h) = rect
    return {(cx, cy) for cx in range(x + 1, x + w - 1) for cy in range(y + 1, y + h - 1)}


class _BuildCase(unittest.TestCase):
    def build(self, spec):
        b = _build(spec)
        self.assertEqual(b.errors, [], "the builder reported errors")
        scn = b.scenario()
        E, W = validate_scenario.validate(scn, set())
        self.assertEqual(E, [], "the validator reported errors")
        return b

    def write_and_inject(self, b, arpg_mods):
        tmp = tempfile.mkdtemp(prefix="worldgen-feas-inj-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root, _z, _n = b.write(tmp, make_zip=False)
        from worldgen import mods
        mods.inject_arpg_mods(root, arpg_mods)
        with open(os.path.join(root, "scenario.json"), encoding="utf-8") as f:
            return json.load(f)


# ------------------------------------------------------------------ 1. doors

def _hold_regions(with_compound_region):
    """A corner part with two strip rooms (entrance on the courtyard side),
   a walled corridor 3 cells wide touching it, and a gate part beyond: the
   arrangement the enclosure layout builds. ``with_compound_region`` picks
   between the two parentage candidates: parts as siblings directly in the
   zone, or an unwalled compound region holding the parts."""
    regions = [_region("The Grounds", (0, 0), (40, 16))]
    if with_compound_region:
        regions.append(_region("Ashvale Hold", (2, 2), (36, 12)))
    # the corner part: rooms stacked as strips, entrance (south) through the
    # lower strip, exactly as the room layout cuts a courtyard-facing entrance
    regions += [
        _region("SW Tower", (4, 4), (7, 7), wall="stone", doors=["south"]),
        _region("SW Tower Store", (4, 4), (7, 3), wall="stone"),
        _region("SW Tower Hall", (4, 7), (7, 4), wall="stone"),
        # the wall: 3 wide, 1-cell interior, touching both parts
        _region("South Wall", (11, 4), (3, 3), wall="stone"),
        # the gate part: lower strip holds the outside door, upper strip the
        # courtyard door, the two doors a gate part carries
        _region("Gatehouse", (14, 4), (7, 7), wall="stone",
                doors=["south", (17, 10)]),
        _region("Gatehouse Passage", (14, 4), (7, 3), wall="stone"),
        _region("Gatehouse Hall", (14, 7), (7, 4), wall="stone"),
    ]
    return regions


class TestDoorsBetweenParts(_BuildCase):
    PARENTS = (False, True)   # siblings in the zone; under a compound region

    def test_touching_parts_auto_connect_both_ways(self):
        for compound in self.PARENTS:
            with self.subTest(compound_region=compound):
                b = self.build(_spec(_hold_regions(compound), player=(2, 3)))
                ops = _openings(b)
                # the corridor's two end doors: facing pairs on the shared
                # wall lines, given by the builder's auto-connect
                self.assertIn((10, 5), ops["SW Tower"], "tower side of the west door")
                self.assertIn((11, 5), ops["South Wall"])
                self.assertIn((13, 5), ops["South Wall"])
                self.assertIn((14, 5), ops["Gatehouse"], "gate side of the east door")
                # the door opens into rooms on both sides: the cell just
                # inside each door is a room's interior, not another wall
                self.assertIn((10, 5), ops["SW Tower Store"],
                              "the west door's cell is the store room's wall cell")
                self.assertIn((14, 5), ops["Gatehouse Passage"])
                seen, blocked = _flood(b)
                self.assertFalse((9, 5) in blocked, "inside the tower at the door")
                self.assertFalse((15, 5) in blocked, "inside the gate at the door")

    def test_the_corridor_is_walked_end_to_end(self):
        b = self.build(_spec(_hold_regions(True), player=(2, 3)))
        seen, _blocked = _flood(b)
        self.assertGreaterEqual(seen, _interior(((11, 4), (3, 3))))

    def test_the_compound_region_is_the_parts_parent(self):
        b = self.build(_spec(_hold_regions(True), player=(2, 3)))
        by_name = {r["name"]: r for r in b.regions}
        self.assertEqual(by_name["SW Tower"]["_parent"]["name"], "Ashvale Hold")
        self.assertEqual(by_name["South Wall"]["_parent"]["name"], "Ashvale Hold")
        # without it the zone is the parent, and the parts still connect
        b2 = self.build(_spec(_hold_regions(False), player=(2, 3)))
        by_name2 = {r["name"]: r for r in b2.regions}
        self.assertEqual(by_name2["SW Tower"]["_parent"]["name"], "The Grounds")
        self.assertIn((10, 5), _openings(b2)["SW Tower"])


# --------------------------------------------------------- 2. thin corridors

class TestThinWalkableWalls(_BuildCase):
    def _spec_long_corridor(self, outer):
        """Two parts joined by one long straight wall: outer width 3 (a
        1-cell interior) or 4 (a 2-cell interior)."""
        w = outer
        regions = [
            _region("The Grounds", (0, 0), (44, 16)),
            _region("West Tower", (4, 4), (7, 7), wall="stone", doors=["south"]),
            _region("West Tower Store", (4, 4), (7, 3), wall="stone"),
            _region("West Tower Hall", (4, 7), (7, 4), wall="stone"),
            _region("Long Wall", (11, 4), (11, w), wall="stone"),
            _region("East Tower", (22, 4), (7, 7), wall="stone", doors=["south"]),
            _region("East Tower Store", (22, 4), (7, 3), wall="stone"),
            _region("East Tower Hall", (22, 7), (7, 4), wall="stone"),
        ]
        return _spec(regions, grid=(44, 16), player=(2, 3))

    def test_one_cell_interior_builds_validates_and_is_walked(self):
        b = self.build(self._spec_long_corridor(3))
        ops = _openings(b)
        self.assertIn((10, 5), ops["West Tower"])
        self.assertIn((21, 5), ops["Long Wall"])
        self.assertIn((22, 5), ops["East Tower"])
        seen, blocked = _flood(b)
        interior = {(x, 5) for x in range(12, 21)}   # the 1-cell walkway
        self.assertLessEqual(interior, seen, "every walkway cell is reached")
        # the corridor's wall ring blocks except at its two end doors
        ring = {(x, y) for x in range(11, 22) for y in range(4, 7)
                if x in (11, 21) or y in (4, 6)}
        self.assertLessEqual(ring - {(11, 5), (21, 5)}, blocked)

    def test_two_cell_interior_also_works(self):
        b = self.build(self._spec_long_corridor(4))
        seen, _blocked = _flood(b)
        interior = {(x, y) for x in range(12, 21) for y in (5, 6)}
        self.assertLessEqual(interior, seen)


# ------------------------------------------------------------ 3. solid walls

class TestSolidWalls(_BuildCase):
    def _spec_solid(self):
        """Two parts with the gap between them boxed shut by walkability-0
        strips (an object curtain wall), each part reached through its own
        door from outside the box."""
        regions = [
            _region("The Grounds", (0, 0), (40, 18)),
            _region("West Tower", (4, 4), (7, 7), wall="stone", doors=["north"]),
            _region("West Tower Store", (4, 4), (7, 3), wall="stone"),
            _region("West Tower Hall", (4, 7), (7, 4), wall="stone"),
            _region("East Tower", (24, 4), (7, 7), wall="stone", doors=["north"]),
            _region("East Tower Store", (24, 4), (7, 3), wall="stone"),
            _region("East Tower Hall", (24, 7), (7, 4), wall="stone"),
        ]
        objects = [
            # the gap between the parts, x 11..23, sealed on all four sides
            # by 1-thick strips: the object curtain wall (one template, one
            # object per run, exactly how a compound's solid walls place)
            _object("Curtain Wall", (13, 1), 0.0, [(11, 4), (11, 10)]),
            _object("Wall Post", (1, 5), 0.0, [(11, 5), (23, 5)]),
        ]
        return _spec(regions, objects, player=(17, 2))

    def test_strips_block_and_parts_stay_reachable(self):
        b = self.build(self._spec_solid())
        seen, blocked = _flood(b)
        # the strips block every cell they cover
        strips = {(x, 4) for x in range(11, 24)} | {(x, 10) for x in range(11, 24)} \
            | {(11, y) for y in range(5, 10)} | {(23, y) for y in range(5, 10)}
        self.assertLessEqual(strips, blocked, "the curtain wall blocks")
        # the sealed gap's ground is cut off, and neither part's rooms are
        self.assertNotIn((17, 7), seen, "the boxed gap is sealed")
        self.assertLessEqual(_interior(((4, 4), (7, 3))) | _interior(((4, 7), (7, 4))),
                             seen, "the west part's rooms are reached")
        self.assertLessEqual(_interior(((24, 4), (7, 3))) | _interior(((24, 7), (7, 4))),
                             seen, "the east part's rooms are reached")

    def test_a_strip_never_sits_on_a_walled_region(self):
        # zero builder errors already proves _claim found no wall overlap;
        # the assertion is restated because it is the rule the layout codes
        b = self.build(self._spec_solid())
        for e in b.entities:
            if e["type"] == "object" and "Wall" in e["name"]:
                for x in range(e["pos"][0], e["pos"][0] + e["size"][0]):
                    for y in range(e["pos"][1], e["pos"][1] + e["size"][1]):
                        self.assertNotIn((x, y), b._wall_cells)


# -------------------------------------------------------- 4. touching storeys

BAND_T1 = (60, 4)   # storey of the west tower, east of the 24-cell strip
BAND_T2 = (68, 4)   # storey of the east tower, one cell east: touching
STOREY_SIZE = (8, 8)


class TestTouchingStoreys(_BuildCase):
    def _spec_storeys(self):
        """A ground pair west of a boundary strip, and their storeys east of
        it: same size as the ground regions, same relative arrangement, one
        cell apart so they touch. Each storey keeps the build-time door the
        floors extension writes (opening onto the slab, passable at build)."""
        regions = [
            _region("The Grounds", (0, 0), (36, 20)),
            _region("West Tower", (6, 4), STOREY_SIZE, wall="stone", doors=["west"]),
            _region("East Tower", (16, 4), STOREY_SIZE, wall="stone", doors=["north"]),
            _region("The Edge of the World", (36, 0), (40, 20)),
            _region("West Tower (upper floor)", BAND_T1, STOREY_SIZE,
                    wall="stone", doors=["west"]),
            _region("East Tower (upper floor)", BAND_T2, STOREY_SIZE,
                    wall="stone", doors=["north"]),
        ]
        objects = [
            {"name": "The World's Edge", "size": [24, 20], "walkability": 1.0,
             "passableAtBuild": True, "maxHp": 999, "heightM": 3,
             "description": "The world's edge.", "physicalDescription": "Void.",
             "tags": ["landmark"], "placements": [[36, 0]]},
        ]
        return _spec(regions, objects, grid=(76, 20), player=(2, 2))

    def _arpg(self):
        return {"floors": [
            {"name": "West Tower floor 2", "area": "West Tower (upper floor)",
             "above": "West Tower", "openings": []},
            {"name": "East Tower floor 2", "area": "East Tower (upper floor)",
             "above": "East Tower", "openings": []},
        ], "portals": []}

    def test_touching_storeys_auto_connect_under_the_boundary(self):
        b = self.build(self._spec_storeys())
        by_name = {r["name"]: r for r in b.regions}
        self.assertEqual(by_name["West Tower (upper floor)"]["_parent"]["name"],
                         "The Edge of the World")
        self.assertEqual(by_name["East Tower (upper floor)"]["_parent"]["name"],
                         "The Edge of the World")
        ops = _openings(b)
        self.assertIn((67, 7), ops["West Tower (upper floor)"],
                      "the shared wall walk door, west side")
        self.assertIn((68, 7), ops["East Tower (upper floor)"],
                      "the shared wall walk door, east side")

    def test_each_storey_maps_to_its_own_building(self):
        b = self.build(self._spec_storeys())
        scn = self.write_and_inject(b, self._arpg())
        by_area = {f["area"]: f for f in scn["arpgMods"]["floors"]}
        self.assertEqual(by_area["West Tower (upper floor)"]["above"], "West Tower")
        self.assertEqual(by_area["East Tower (upper floor)"]["above"], "East Tower")
        return scn

    def test_seal_strips_the_fiction_doors(self):
        """What the seal does today: it takes every opening on a storey's
        border, so the build-time fiction doors go (their job) and the
        shared wall-walk door goes with them (a problem). Change 4 narrows
        the seal to the fiction doors and flips the last two assertions."""
        scn = self.test_each_storey_maps_to_its_own_building()
        by_name = {r["name"]: r for r in scn["regions"]}
        west = {tuple(c) for c in by_name["West Tower (upper floor)"]["openings"]}
        east = {tuple(c) for c in by_name["East Tower (upper floor)"]["openings"]}
        self.assertNotIn((60, 7), west, "the west fiction door is sealed away")
        self.assertNotIn((71, 11), east, "the east fiction door is sealed away")
        self.assertNotIn((67, 7), west, "today the shared door is stripped too")
        self.assertNotIn((68, 7), east, "today the shared door is stripped too")


if __name__ == "__main__":
    unittest.main()
