"""Rooms are sized from what goes in them: each room's area is its furniture
footprints x2.5 plus a walkway (3x3 minimum), the building covers the sum
with the sizeClass as a floor and 28x22 as a cap, a room that still cannot
hold its furniture splits into an annex before pieces drop, and past that
point the lowest-value pieces (decorative before functional) are dropped and
recorded."""
import unittest

import worldgen
from worldgen.layout_building import (CAP, MIN_ROOM_AREA, ROOM_WALKWAY,
                                      _resolve_plan, building_footprint,
                                      layout_building)
from worldgen.model import ObjectTemplate, parse_plan

TMPL = {
    "Straw Bed": ObjectTemplate(name="Straw Bed", size=(1, 2), tags=["bed"]),
    "Oak Table": ObjectTemplate(name="Oak Table", size=(2, 2), tags=["table", "eat"]),
    "Stool": ObjectTemplate(name="Stool", size=(1, 1), tags=["seat"]),
    "Chest": ObjectTemplate(name="Chest", size=(1, 1), tags=["storage"]),
    "Hearth": ObjectTemplate(name="Hearth", size=(2, 1), tags=["fire", "cook"]),
    "Banquet Table": ObjectTemplate(name="Banquet Table", size=(3, 3), tags=["table", "eat"]),
    "Tapestry": ObjectTemplate(name="Tapestry", size=(1, 1), tags=["decor"]),
}


def cottage_plan():
    """A cottage whose Main Room furniture never fit the old fixed sizes."""
    return {
        "name": "Sized Cottage", "worldBackground": "A cottage.",
        "setting": {"era": "medieval", "technology": "wood",
                    "density": "normal", "climate": "temperate"},
        "mapSize": "small",
        "zones": [{"name": "Hamlet", "kind": "village", "sizeClass": "medium",
                   "description": "One cottage.", "ground": "grass",
                   "adjacentTo": [], "outdoor": [],
                   "buildings": [{"name": "Longmead Cottage", "kind": "cottage",
                                  "sizeClass": "small", "purpose": "a home",
                                  "yard": None}],
                   "dressing": {"paths": "dirt", "props": [], "filler": []}}],
        "roads": [],
        "templates": [
            {"name": n, "size": list(t.size), "walkability": 0.0,
             "tags": t.tags, "description": n, "physicalDescription": n,
             "rule": "anywhere free"}
            for n, t in TMPL.items()],
        "buildings": [{
            "name": "Longmead Cottage", "wall": "wood", "ground": "wood",
            "rooms": [{"name": "Main Room", "share": "medium", "purpose": "living"},
                      {"name": "Bedroom", "share": "small", "purpose": "sleeping"}],
            "connections": [["Main Room", "Bedroom"]],
            "entrance": {"room": "Main Room", "side": "south"},
            "furniture": [
                {"template": "Hearth", "room": "Main Room", "count": 1, "hint": "wall:north"},
                {"template": "Oak Table", "room": "Main Room", "count": 1, "hint": "center"},
                {"template": "Stool", "room": "Main Room", "count": 3, "hint": "around:Oak Table"},
                {"template": "Chest", "room": "Main Room", "count": 1, "hint": "corner"},
                {"template": "Straw Bed", "room": "Bedroom", "count": 1, "hint": "wall:north"},
                {"template": "Chest", "room": "Bedroom", "count": 1, "hint": "beside:Straw Bed"},
            ],
            "yard": None}],
        "npcs": [{"name": "Tam Miller", "gender": "male", "role": "cottar",
                  "home": "Longmead Cottage", "work": "Hamlet",
                  "description": "A cottar.", "physicalDescription": "wiry"}],
        "player": {"name": "Wanderer", "gender": "male", "role": "traveller",
                   "home": "Longmead Cottage", "work": "Hamlet",
                   "description": "Passing.", "physicalDescription": "cloaked"},
    }


class TestRoomSizing(unittest.TestCase):
    def setUp(self):
        import random
        from worldgen.model import BuildingDesign, FurniturePlan, RoomSpec
        self.random = random.Random(1)
        self.RoomSpec = RoomSpec
        self.FurniturePlan = FurniturePlan
        self.BuildingDesign = BuildingDesign

    def design(self, rooms, furniture, size_class="small", entrance="south"):
        d = self.BuildingDesign(
            name="T", size_class=size_class,
            rooms=[self.RoomSpec(name=n, share=s) for (n, s) in rooms],
            connections=[[rooms[i][0], rooms[i + 1][0]] for i in range(len(rooms) - 1)],
            entrance_room=rooms[0][0], entrance_side=entrance,
            furniture=furniture)
        return d

    def test_room_area_covers_its_furniture(self):
        furniture = [
            self.FurniturePlan(template="Oak Table", room="Main", count=1),
            self.FurniturePlan(template="Stool", room="Main", count=4),
            self.FurniturePlan(template="Straw Bed", room="Bed", count=1),
            self.FurniturePlan(template="Chest", room="Bed", count=1),
        ]
        d = self.design([("Main", "large"), ("Bed", "small")], furniture)
        w, h, _design, furn, dropped, needs = _resolve_plan(d, TMPL)
        b = layout_building(d, (0, 0), self.random, TMPL)
        self.assertEqual((b.rect.w, b.rect.h), (w, h))
        for room in b.rooms:
            area, min_side = needs[room.base_name]
            self.assertGreaterEqual(room.rect.w * room.rect.h, area,
                                    f"{room.base_name} smaller than its furniture")
            self.assertGreaterEqual(min(room.rect.w, room.rect.h), min_side)
        # the brief's formula: footprints x2.5 + walkway, 3x3 minimum, with
        # solid pieces counting 1.6x for their standing room
        from worldgen.layout_building import SOLID_FURN_SCALE
        solid = lambda cells: int(round(cells * SOLID_FURN_SCALE))
        self.assertEqual(needs["Main"][0],
                         int(round((solid(4) + solid(4)) * 2.5 + ROOM_WALKWAY)))
        self.assertEqual(needs["Bed"][0],
                         int(round((solid(2) + solid(1)) * 2.5 + ROOM_WALKWAY)))

    def test_empty_room_gets_the_minimum(self):
        d = self.design([("Hall", "medium")], [])
        _w, _h, _design, _furn, _dropped, needs = _resolve_plan(d, TMPL)
        self.assertGreaterEqual(needs["Hall"][0], MIN_ROOM_AREA)
        self.assertGreaterEqual(building_footprint(d, TMPL), (11, 8))  # small floor

    def test_sizeclass_is_a_floor(self):
        empty = self.design([("Hall", "medium")], [])
        packed = self.design([("Hall", "medium")],
                             [self.FurniturePlan(template="Stool", room="Hall", count=2)])
        self.assertEqual(building_footprint(empty, TMPL),
                         building_footprint(packed, TMPL))

    def test_cap_drops_decorative_before_functional(self):
        furniture = (
            [self.FurniturePlan(template="Banquet Table", room="Hall", count=20)]
            + [self.FurniturePlan(template="Tapestry", room="Hall", count=6)])
        d = self.design([("Hall", "large")], furniture, size_class="large")
        w, h, _design, furn, dropped, needs = _resolve_plan(d, TMPL)
        self.assertLessEqual((w, h), CAP)
        self.assertGreaterEqual((w, h), (16, 12))   # the large floor still applies
        names = [t for (t, _room) in dropped]
        # every tapestry goes before any table
        if "Banquet Table" in names:
            self.assertEqual(names.count("Tapestry"), 6)
        self.assertEqual(names, sorted(names, key=lambda n: 0 if n == "Tapestry" else 1))
        # what remains fits the cap
        kept = sum(f.count * t.size[0] * t.size[1]
                   for f in furn for t in [TMPL[f.template]])
        self.assertLessEqual(int(round(kept * 2.5 + ROOM_WALKWAY)), CAP[0] * CAP[1])

    def test_furnished_cottage_places_everything(self):
        world = worldgen.run(cottage_plan(), seed=1)
        unplaced = [u for u in world.metrics["objects"]["unplaced"]]
        self.assertEqual(unplaced, [],
                         f"the sized cottage should place every piece: {unplaced}")

    def test_cap_drops_are_recorded(self):
        plan = cottage_plan()
        plan["zones"][0]["sizeClass"] = "large"   # room for the 28x22 footprint
        design = plan["buildings"][0]
        design["furniture"] = [
            {"template": "Banquet Table", "room": "Main Room", "count": 60, "hint": ""},
            {"template": "Tapestry", "room": "Bedroom", "count": 6, "hint": ""}]
        world = worldgen.run(plan, seed=1)
        self.assertEqual([f for f in world.failures if "no space" in f[1]], [])
        drops = [(w, r) for (w, r) in world.failures if "28x22" in r]
        self.assertTrue(drops, "cap drops should be recorded as failures")
        cottage = next(b for b in world.buildings
                       if b.layout.design.name == "Longmead Cottage")
        self.assertLessEqual((cottage.layout.rect.w, cottage.layout.rect.h), CAP)

    def test_overflowing_room_splits_into_an_annex(self):
        """A room that cannot hold its furniture at the cap becomes two
        connected rooms — the room and its Annex — sharing a wall."""
        from worldgen.model import shared_wall_cells
        furniture = [self.FurniturePlan(template="Banquet Table", room="Dining Hall",
                                        count=26)]
        d = self.design([("Dining Hall", "large"), ("Pantry", "small")],
                        furniture, size_class="hall")
        b = layout_building(d, (0, 0), self.random, TMPL)
        names = {r.base_name for r in b.rooms}
        self.assertIn("Dining Hall Annex", names,
                      "the over-stuffed room should split into an annex")
        self.assertLessEqual((b.rect.w, b.rect.h), CAP)
        main = b.room_by_base("Dining Hall")
        annex = b.room_by_base("Dining Hall Annex")
        self.assertTrue(shared_wall_cells(main.rect, annex.rect),
                        "the annex must share a wall with its room")
        self.assertTrue(any(f.room in ("Dining Hall", "Dining Hall Annex")
                            for f in b.furniture),
                        "some of the room's furniture should survive the split")


if __name__ == "__main__":
    unittest.main()
