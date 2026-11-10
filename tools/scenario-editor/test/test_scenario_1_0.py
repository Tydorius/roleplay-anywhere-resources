"""scenario_checks on Anywhere RPG 1.0's scenario format: floors as planes beside the map, native portals, sided
openings, door objects and locks, natural shapes, liquids, NPC templates with homes, the renamed sprites, and the
world generator's fields a scenario can't use. The shapes come from the 1.0 bundle (see the README).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scenario_checks as sc  # noqa: E402


def region(rid, name, pos, size, wall="wood", openings=(), **kw):
    r = {"id": rid, "name": name, "position": list(pos), "size": list(size), "openings": [list(o) for o in openings]}
    if wall:
        r["wall"] = wall
    r.update(kw)
    return r


def obj(oid, name, tid, pos, **kw):
    e = {"id": oid, "type": "object", "name": name, "templateId": tid, "pos": list(pos), "inventory": [],
         "statusEffects": []}
    e.update(kw)
    return e


def person(pid, name, pos, kind="npc", **kw):
    e = {"id": pid, "type": kind, "name": name, "pos": list(pos), "gender": "female", "animationId": "casual-woman",
         "inventory": [], "statusEffects": [],
         "schedule": [{"start": "00:00", "end": "00:00", "location": kw.pop("home", "Yard"), "role": "leisure"}]}
    e.update(kw)
    return e


STAIR = {"id": "t_stair", "name": "Stair", "size": [1, 1], "walkability": 1}
DOOR = {"id": "t_door", "name": "Door", "size": [1, 0], "walkability": 1, "door": "door"}


def scenario(regions=(), entities=(), **kw):
    scn = {"name": "T", "gridSize": [30, 20], "playerId": "p", "stancesAuthored": True,
           "regions": [region("r_yard", "Yard", (0, 0), (30, 20), wall=None)] + list(regions),
           "objectTemplates": [STAIR, DOOR], "itemTemplates": [],
           "entities": [person("p", "Hero", (2, 2), "player")] + list(entities)}
    scn.update(kw)
    return scn


def found(scn, level=None):
    return [f["msg"] for f in sc.check(scn) if level is None or f["level"] == level]


def house_with_loft(two_way=True):
    """A house on the map with a stair up to a loft: the loft is a floor 24 cells east of the 30 x 20 map."""
    house = region("r_house", "House", (4, 4), (6, 6), openings=[(6, 4)])
    loft = region("r_loft", "Loft", (54, 0), (6, 6), pocket={"anchor": "r_house", "level": 1})
    up = obj("o_up", "Stair up", "t_stair", (6, 6), portal={"to": "o_down"})
    down = obj("o_down", "Stair down", "t_stair", (56, 2))
    if two_way:
        down["portal"] = {"to": "o_up"}
    return scenario([house, loft], [up, down, person("n1", "Maid", (57, 3), home="Loft")])


class Floors(unittest.TestCase):
    def test_a_floor_beside_the_map_is_legal_and_reached_by_its_stairs(self):
        out = found(house_with_loft())
        self.assertEqual([m for m in out if ("Loft" in m or "Maid" in m or "outside" in m) and "portrait" not in m],
                         [], out)

    def test_without_the_portal_the_loft_is_cut_off(self):
        scn = house_with_loft()
        for e in scn["entities"]:
            e.pop("portal", None)
        out = found(scn, "error")
        self.assertIn("Room 'Loft' can't be reached on foot from the player.", out)
        self.assertIn("'Maid' can't be reached on foot from the player.", out)

    def test_a_one_way_portal_is_a_note(self):
        notes = found(house_with_loft(two_way=False), "info")
        self.assertTrue(any("doesn't lead back" in m for m in notes), notes)

    def test_an_ordinary_region_off_the_map_is_still_an_error(self):
        scn = scenario([region("r_shed", "Shed", (40, 2), (4, 4), openings=[(41, 2)])])
        self.assertIn("Region 'Shed' reaches outside the 30x20 map.", found(scn, "error"))

    def test_a_room_inside_a_floor_is_on_the_map(self):
        scn = house_with_loft()
        scn["regions"].append(region("r_closet", "Closet", (58, 3), (2, 3), openings=[(58, 4)]))
        self.assertFalse([m for m in found(scn, "error") if "Closet" in m])

    def test_a_floor_on_the_map_and_floors_that_touch(self):
        scn = house_with_loft()
        scn["regions"].append(region("r_attic", "Attic", (20, 10), (4, 4), pocket={"anchor": "r_house", "level": 2}))
        scn["regions"].append(region("r_cellar", "Cellar", (60, 0), (4, 4), pocket={"anchor": "r_house", "level": -1}))
        out = found(scn, "warning")
        self.assertTrue(any("'Attic' is a floor but lies on the map" in m for m in out), out)
        self.assertIn("Floors 'Loft' and 'Cellar' touch; leave a gap so nobody steps straight between them.", out)

    def test_bad_pocket_fields(self):
        scn = house_with_loft()
        scn["regions"][2]["pocket"] = {"anchor": "r_nowhere", "level": 0}
        out = found(scn, "warning")
        self.assertTrue(any("a floor's level is a whole number other than 0" in m for m in out), out)
        self.assertIn("Region 'Loft': its anchor 'r_nowhere' isn't another region.", out)

    def test_hostile_buffer_ignores_other_planes(self):
        scn = house_with_loft()
        scn["regions"].append(region("r_den", "Den", (62, 0), (4, 4), wall=None, hostile=True,
                                     pocket={"anchor": "r_house", "level": -1}))
        self.assertFalse([m for m in found(scn) if "within 15 cells" in m])

    def test_level_and_anchor_without_pocket_are_flagged(self):
        scn = scenario([region("r_up", "Upstairs", (4, 4), (4, 4), openings=[(5, 4)], level=1, anchor="r_yard")])
        self.assertTrue(any("level and anchor aren't read from a scenario" in m for m in found(scn, "warning")))


class Portals(unittest.TestCase):
    def test_a_portal_to_nothing_is_an_error(self):
        scn = scenario(entities=[obj("o_a", "Trapdoor", "t_stair", (5, 5), portal={"to": "o_gone"})])
        self.assertIn("Portal 'Trapdoor' leads to 'o_gone', which is no object in the scenario.", found(scn, "error"))

    def test_a_person_cant_be_a_portal(self):
        scn = scenario(entities=[person("n1", "Ghost", (5, 5), portal={"to": "p"})])
        self.assertIn("'Ghost' has a portal, but only objects lead anywhere.", found(scn, "warning"))


class Openings(unittest.TestCase):
    def test_a_sided_opening_only_opens_that_side(self):
        # a corner door of a room in the corner of a building: [4, 4, "s"] opens south only, so west stays shut
        room = region("r_room", "Room", (4, 4), (4, 4), openings=[(4, 4, "w")])
        scn = scenario([room])
        self.assertFalse([m for m in found(scn, "error") if "Room" in m])
        room["openings"] = [[4, 4, "n"]]
        self.assertTrue(any("isn't on that side" in m for m in found(scn, "warning")))

    def test_an_opening_off_the_edge_is_dropped(self):
        scn = scenario([region("r_room", "Room", (4, 4), (4, 4), openings=[(5, 5)])])
        out = found(scn)
        self.assertIn("Region 'Room': door [5, 5] is not on its edge; the game drops it.", out)
        self.assertIn("Walled region 'Room' has no door, so it is sealed.", out)
        self.assertIn("Room 'Room' can't be reached on foot from the player.", out)

    def test_two_value_openings_still_work(self):
        scn = scenario([region("r_room", "Room", (4, 4), (4, 4), openings=[(4, 5)])])
        self.assertFalse([m for m in found(scn, "error") if "Room" in m])


class Doors(unittest.TestCase):
    def test_door_objects_are_zero_wide_and_never_off_the_map(self):
        room = region("r_room", "Room", (26, 4), (4, 4), openings=[(29, 5, "e")], door="gate")
        door = obj("o_door", "Door 1", "t_door", (30, 5), size=[0, 1])  # on the map's east edge
        out = found(scn := scenario([room], [door]))
        self.assertFalse([m for m in out if "Door 1" in m], out)
        self.assertFalse([m for m in found(scn, "error") if "outside" in m])

    def test_unknown_door_kind_and_colour(self):
        scn = scenario([region("r_room", "Room", (4, 4), (4, 4), openings=[(4, 5)], door="portcullis",
                               doorColor="brown")])
        out = found(scn, "warning")
        self.assertIn("Region 'Room': door 'portcullis' isn't door, bars, gate, curtain or none.", out)
        self.assertIn("Region 'Room': doorColor 'brown' isn't a colour like #8a5a2b.", out)

    def lockup(self, key_holder=None):
        cell = region("r_cell", "Cell", (4, 4), (4, 4), openings=[(4, 5, "w")])
        locked = {"id": "se1", "def": {"desc": "Locked", "type": "constant", "mechanics": [{"type": "locked"}]}}
        door = obj("o_door", "Cell door", "t_door", (4, 5), size=[0, 1], statusEffects=[locked])
        ents = [door]
        if key_holder:
            ents.append(person("n1", key_holder, (2, 6), inventory=[{"id": "i1", "templateId": "k1", "count": 1}]))
        return scenario([cell], ents, itemTemplates=[{"id": "k1", "name": "Cell key", "type": "misc",
                                                       "quality": "common", "opens": "r_cell"}])

    def test_a_locked_door_needs_someone_with_its_key(self):
        self.assertIn("'Cell door' on 'Cell' is locked and nobody carries its key.", found(self.lockup(), "warning"))
        self.assertFalse([m for m in found(self.lockup("Jailer")) if "locked" in m])

    def test_key_holders_are_a_generator_field(self):
        scn = scenario([region("r_vault", "Vault", (4, 4), (4, 4), openings=[(4, 5)], keyHolders=["Hero", "Nobody"])])
        out = [m for m in found(scn, "warning") if "keyHolders" in m]
        self.assertEqual(len(out), 1, out)
        self.assertIn("'Nobody' is no character here either.", out[0])

    def test_a_key_to_nothing(self):
        scn = scenario(itemTemplates=[{"id": "k1", "name": "Old key", "type": "misc", "quality": "common",
                                       "opens": "r_gone"}])
        self.assertIn("Item 'Old key' is a key to 'r_gone', which is no region.", found(scn, "warning"))


class NatureAndLiquids(unittest.TestCase):
    def test_natural_is_the_generators_word(self):
        scn = scenario([region("r_green", "Green", (4, 4), (8, 8), wall=None, shape="natural")])
        self.assertTrue(any("needs 'organic'" in m for m in found(scn, "warning")))
        scn["regions"][1]["shape"] = "organic"
        self.assertFalse([m for m in found(scn) if "Green" in m])

    def test_a_lake_nobody_can_wade_cuts_the_map(self):
        lake = region("r_lake", "Lake", (10, 0), (6, 20), wall=None, surface="deep water")
        scn = scenario([lake], [person("n1", "Fisher", (25, 5))])
        out = found(scn)
        self.assertIn("'Fisher' can't be reached on foot from the player.", out)
        self.assertTrue(any("adds it as one nobody can walk through" in m for m in out))
        scn["unbounded"] = {"seed": 1, "profile": {"media": [{"name": "deep water", "walk": "slow"}], "lowEdges": []},
                            "areas": []}
        self.assertNotIn("'Fisher' can't be reached on foot from the player.", found(scn))

    def test_a_bridge_crosses_the_lake(self):
        lake = region("r_lake", "Lake", (10, 0), (6, 20), wall=None, surface="deep water")
        bridge = region("r_bridge", "Bridge", (10, 9), (6, 2), wall=None)
        scn = scenario([lake, bridge], [person("n1", "Fisher", (25, 5))])
        self.assertNotIn("'Fisher' can't be reached on foot from the player.", found(scn))

    def test_liquid_on_a_walled_region_is_ignored(self):
        scn = scenario([region("r_bath", "Bath", (4, 4), (4, 4), openings=[(4, 5)], surface="water")])
        self.assertIn("Region 'Bath': walled regions and floors can't be a liquid; the game ignores surface here.",
                      found(scn, "warning"))


class Templates(unittest.TestCase):
    def test_npc_templates_with_homes_and_peaceful_stances(self):
        sheep = {"id": "ntpl_1", "name": "Sheep", "animationId": "sheep", "stance": "skittish",
                 "homes": [{"regionId": "r_yard", "count": 3}]}
        scn = scenario(npcTemplates=[sheep])
        self.assertFalse([m for m in found(scn) if "Sheep" in m])  # a flock in a peaceful field is fine
        sheep["homes"].append({"regionId": "r_gone", "count": 1})
        sheep["stance"] = "grazing"
        out = found(scn)
        self.assertIn("NPC type 'Sheep': its home region 'r_gone' doesn't exist.", out)
        self.assertIn("NPC type 'Sheep': stance 'grazing' isn't hostile, neutral, skittish.", out)

    def test_a_hostile_type_outside_hostile_ground(self):
        wolf = {"id": "htpl_1", "name": "Wolf", "animationId": "gray-wolf", "regionId": "r_yard", "count": 2}
        self.assertIn("Hostile type 'Wolf' lives in 'Yard', which isn't marked hostile.",
                      found(scenario(hostileNpcTemplates=[wolf]), "warning"))

    def test_both_template_lists(self):
        wolf = {"id": "htpl_1", "name": "Wolf", "animationId": "gray-wolf", "regionId": "r_yard", "count": 2}
        scn = scenario(hostileNpcTemplates=[wolf], npcTemplates=[],
                       entities=[person("w1", "Wolf 1", (8, 8), templateId="htpl_1")])
        out = found(scn)
        self.assertTrue(any("drops hostileNpcTemplates" in m for m in out))
        self.assertIn("NPC 'Wolf 1': its NPC type doesn't exist; the import refuses the file.", out)

    def test_old_sprite_names_are_aliases(self):
        rat = {"id": "htpl_1", "name": "Rat", "animationId": "giant-rat", "regionId": "r_yard", "count": 2}
        out = found(scenario(hostileNpcTemplates=[rat]))
        self.assertIn("Hostile type 'Rat': sprite 'giant-rat' was renamed 'rat' in 1.0; the import switches it.", out)
        self.assertFalse([m for m in out if "unknown sprite" in m])

    def test_skittish_and_new_sprites_on_characters(self):
        scn = scenario(entities=[person("n1", "Nurse", (5, 5), stance="skittish", animationId="nurse-woman")])
        self.assertFalse([m for m in found(scn) if "Nurse" in m and ("stance" in m or "sprite" in m)])

    def test_vehicle_fields(self):
        cart = {"id": "t_cart", "name": "Cart", "size": [2, 2], "walkability": 0, "vehicle": "fly", "sheet": "cart"}
        scn = scenario()
        scn["objectTemplates"].append(cart)
        out = found(scn, "warning")
        self.assertIn("Object type 'Cart': vehicle 'fly' isn't drive or ride.", out)
        self.assertTrue(any("sheet 'cart' isn't a built-in vehicle sheet" in m for m in out))


class Unbounded(unittest.TestCase):
    def test_presets_shape_passes_and_a_broken_one_is_caught(self):
        good = {"seed": 5, "profile": {"media": [{"name": "creek water", "walk": "slow", "color": "#4f7a6e"}],
                                       "lowEdges": []}, "areas": [{"record": {"id": "0,-1"}, "places": []}]}
        self.assertFalse([m for m in found(scenario(unbounded=good)) if "unbounded" in m])
        self.assertIn("unbounded must be an object {seed, profile, areas}.", found(scenario(unbounded=[]), "error"))


if __name__ == "__main__":
    unittest.main()
