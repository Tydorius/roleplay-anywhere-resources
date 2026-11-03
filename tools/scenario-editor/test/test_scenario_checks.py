"""scenario_checks with code-mod data: portals carry the reachability walk (object, cell and region ends,
one-way and two-way), floor openings can't be walked into, a storey reached only by its stairs isn't
"sealed", and a 2x2 bed sleeps two. A scenario without arpgMods is checked exactly as before.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scenario_checks  # noqa: E402


def region(rid, name, pos, size, wall="wood", openings=()):
    return {"id": rid, "name": name, "position": list(pos), "size": list(size), "wall": wall,
            "openings": [list(o) for o in openings]}


def scenario(regions, entities=(), templates=(), mods=None):
    scn = {"name": "T", "gridSize": [40, 20], "regions": list(regions), "playerId": "p",
           "stancesAuthored": True, "objectTemplates": list(templates),
           "entities": [{"id": "p", "type": "player", "name": "Hero", "pos": [2, 2]}] + list(entities)}
    if mods is not None:
        scn["arpgMods"] = mods
    return scn


STAIR = {"id": "t_stair", "name": "Stair", "size": [1, 1], "walkability": 1}
BED = {"id": "t_bed", "name": "Bed", "size": [1, 2], "walkability": 0.3, "forSleep": True}
DOUBLE = {"id": "t_double", "name": "Double bed", "size": [2, 2], "walkability": 0.3, "forSleep": True}


def obj(oid, name, tid, pos):
    return {"id": oid, "type": "object", "name": name, "templateId": tid, "pos": list(pos)}


def msgs(scn, level=None):
    return [f["msg"] for f in scenario_checks.check(scn) if level is None or f["level"] == level]


class Portals(unittest.TestCase):
    def storey(self, two_way=True, mods_extra=None):
        """A sealed room off to the east (no doors), reached only by a stair pad pair."""
        regions = [region("r_up", "Loft", (30, 5), (6, 6))]
        ents = [obj("o_a", "Stair down", "t_stair", (5, 5)), obj("o_b", "Stair up", "t_stair", (32, 7))]
        portals = [{"name": "Stairs", "from": {"object": "Stair down"}, "to": {"object": "Stair up"},
                    "twoWay": two_way}]
        mods = {"portals": portals}
        mods.update(mods_extra or {})
        return scenario(regions, ents, [STAIR], mods)

    def test_without_mods_the_room_is_unreachable_and_sealed(self):
        scn = self.storey()
        del scn["arpgMods"]
        out = msgs(scn)
        self.assertIn("Room 'Loft' can't be reached on foot from the player.", out)
        self.assertIn("Walled region 'Loft' has no door, so it is sealed.", out)

    def test_a_portal_reaches_the_room_and_it_is_not_sealed(self):
        out = msgs(self.storey())
        self.assertFalse([m for m in out if "Loft" in m], out)
        self.assertIn("Uses code-mod data: portals. Those mods must be installed in the game.", out)

    def test_one_way_portal_still_leads_in(self):
        self.assertFalse([m for m in msgs(self.storey(two_way=False)) if "Loft" in m])

    def test_a_portal_out_of_a_room_the_player_cannot_reach_does_not_help(self):
        scn = self.storey(two_way=False)
        p = scn["arpgMods"]["portals"][0]
        p["from"], p["to"] = p["to"], p["from"]   # one way, from the loft down
        self.assertIn("Room 'Loft' can't be reached on foot or through a portal from the player.", msgs(scn, "error"))

    def test_cell_and_region_ends(self):
        regions = [region("r_a", "Vault", (30, 5), (6, 6)), region("r_b", "Cellar", (20, 12), (4, 4))]
        portals = [{"name": "Mirror", "from": {"cell": [6, 6]}, "to": {"region": "Vault"}},
                   {"name": "Chute", "from": {"region": "vault"}, "to": {"cell": [21, 13]}}]
        out = msgs(scenario(regions, mods={"portals": portals}))
        self.assertFalse([m for m in out if "Vault" in m or "Cellar" in m], out)

    def test_an_end_that_names_nothing_is_reported(self):
        scn = self.storey()
        scn["arpgMods"]["portals"][0]["to"] = {"object": "No such thing"}
        out = msgs(scn, "warning")
        self.assertIn("Portal 'Stairs': its to end names nothing on the map, so the portals mod drops it.", out)

    def test_arrival_stays_on_the_pads_side_of_a_wall(self):
        """A pad against the inside of a sealed room's wall must not let you out through the wall."""
        regions = [region("r_up", "Loft", (30, 5), (6, 6)), region("r_cell", "Cell", (36, 5), (3, 3))]
        ents = [obj("o_a", "Stair down", "t_stair", (5, 5)), obj("o_b", "Stair up", "t_stair", (35, 6))]
        portals = [{"name": "Stairs", "from": {"object": "Stair down"}, "to": {"object": "Stair up"}}]
        out = msgs(scenario(regions, ents, [STAIR], {"portals": portals}), "error")
        self.assertIn("Room 'Cell' can't be reached on foot or through a portal from the player.", out)
        self.assertNotIn("Room 'Loft' can't be reached on foot or through a portal from the player.", out)


class Floors(unittest.TestCase):
    def test_floors_without_portals_warns(self):
        scn = scenario([region("r_up", "Loft", (30, 5), (6, 6))],
                       mods={"floors": [{"name": "Loft floor", "area": "Loft", "above": "Loft", "openings": []}]})
        self.assertIn("arpgMods has floors but no portals: the storeys' stairs are portals, so nobody can reach them.",
                      msgs(scn, "warning"))

    def test_openings_block_their_cells_and_are_not_rooms(self):
        regions = [region("r_hall", "Hall", (1, 1), (10, 8), openings=[(10, 4)]),
                   region("r_well", "Gallery well", (4, 3), (3, 3), wall="wood")]
        ents = [{"id": "n", "type": "npc", "name": "Nan", "pos": [5, 4]}]
        mods = {"portals": [], "floors": [{"name": "F", "area": "Hall", "above": "Hall", "openings": ["Gallery well"]}]}
        out = msgs(scenario(regions, ents, mods=mods))
        self.assertFalse([m for m in out if "Gallery well" in m], out)
        # Nan stands inside the opening: a cell nobody can walk to, so she isn't on the walk either
        self.assertFalse([m for m in out if "Nan" in m and "reached" in m], out)

    def test_an_opening_that_names_no_region_is_reported(self):
        mods = {"portals": [], "floors": [{"name": "F", "area": "Hall", "above": "Hall", "openings": ["Nowhere"]}]}
        out = msgs(scenario([region("r_hall", "Hall", (1, 1), (10, 8), openings=[(10, 4)])], mods=mods), "warning")
        self.assertIn("Floor 'F': opening 'Nowhere' names no region.", out)


class Beds(unittest.TestCase):
    def home(self, beds):
        regions = [region("r_home", "Home", (1, 1), (8, 8), openings=[(8, 4)])]
        ents = [obj(f"o{i}", f"B{i}", tid, pos) for i, (tid, pos) in enumerate(beds)]
        for k in range(3):
            ents.append({"id": f"n{k}", "type": "npc", "name": f"N{k}", "pos": [7, 2 + k],
                         "schedule": [{"start": "22:00", "end": "06:00", "location": "Home", "role": "sleep"}]})
        return scenario(regions, ents, [BED, DOUBLE])

    def test_a_double_bed_sleeps_two(self):
        self.assertFalse([m for m in msgs(self.home([("t_double", (2, 2)), ("t_bed", (5, 2))])) if "sleep" in m])

    def test_two_single_beds_are_short_one(self):
        self.assertIn("3 sleep in 'Home', which has 2 places to sleep.",
                      msgs(self.home([("t_bed", (2, 2)), ("t_bed", (4, 2))])))

    def test_capacity(self):
        cap = scenario_checks.bed_capacity
        self.assertEqual([cap(scenario_checks.rect((0, 0), s)) for s in ([1, 1], [1, 2], [2, 1], [2, 2], [3, 2])],
                         [1, 1, 1, 2, 2])


if __name__ == "__main__":
    unittest.main()
