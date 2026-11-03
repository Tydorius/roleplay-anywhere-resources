"""The P1 compound contract (raw plan validation, the 16-building cap when
compounds are used, sanitizing) and P3's one line per part on its slot and
its neighbours."""
import json
import os
import unittest

from worldgen import phases


def world(n_castle=6, n_village=4, compounds=None, arrangement=""):
    """A raw P1 reply: one zone per 6-name pool plus optional compounds."""
    def zone(name, kinds, start, count):
        return {"name": name, "kind": kinds, "sizeClass": "medium",
                "description": "d", "ground": "grass",
                "buildings": [{"name": f"{name} Building {i + 1}", "kind": "house",
                               "sizeClass": "small", "purpose": "p"}
                              for i in range(start, start + count)]}
    d = {"name": "W", "worldBackground": "b",
         "setting": {"era": "e", "technology": "t", "density": "sparse", "climate": "c"},
         "mapSize": "small",
         "zones": [zone("Castle Rise", "hamlet", 0, n_castle),
                   zone("Netherford", "village", 0, n_village)],
         "roads": []}
    if arrangement:
        d["zones"][0]["arrangement"] = arrangement
    if compounds is not None:
        d["compounds"] = compounds
    return d


def castle_compound(zone="Castle Rise"):
    return {"name": "The Ward", "zone": zone, "shape": "enclosure",
            "courtyard": "medium", "walls": "walkable",
            "parts": [
                {"building": "Castle Rise Building 1", "at": "corner:nw"},
                {"building": "Castle Rise Building 2", "at": "corner:ne"},
                {"building": "Castle Rise Building 3", "at": "corner:se"},
                {"building": "Castle Rise Building 4", "at": "corner:sw"},
                {"building": "Castle Rise Building 5", "at": "edge:south:center",
                 "gate": True},
                {"building": "Castle Rise Building 6", "at": "inside:north"}]}


class TestCompoundLine(unittest.TestCase):
    def line(self, building, compound=None):
        comp = castle_compound() if compound is None else compound
        d = world(compounds=[comp])
        zone = next(z for z in d["zones"] if z["name"] == comp["zone"])
        b = next(x for x in zone["buildings"] if x["name"] == building)
        return phases._compound_line(d["compounds"], zone, b)

    def test_not_a_part(self):
        d = world(compounds=[castle_compound()])
        zone = next(z for z in d["zones"] if z["name"] == "Netherford")
        line = phases._compound_line(d["compounds"], zone, zone["buildings"][0])
        self.assertIn("stands on its own", line)

    def test_corner_names_its_two_walls_and_wall_neighbours(self):
        line = self.line("Castle Rise Building 1")   # corner:nw
        self.assertIn("part of The Ward", line)
        self.assertIn("corner slot NW", line)
        self.assertIn("walls join it on the west and the north", line)
        # the walk order round the enclosure: sw-then-north side before nw,
        # and the north side (nw -> ne) after it
        self.assertIn("Building 4", line)
        self.assertIn("Building 2", line)

    def test_edge_gate_part(self):
        line = self.line("Castle Rise Building 5")   # edge:south:center, gate
        self.assertIn("set in the south wall (center)", line)
        self.assertIn("walls join it on the west and the east", line)
        self.assertIn("GATE, walked through on both faces", line)

    def test_inside_part_has_no_walls(self):
        line = self.line("Castle Rise Building 6")   # inside:north
        self.assertIn("standing in the courtyard towards the north", line)
        self.assertIn("no walls touch it", line)

    def test_attached_part_names_its_host(self):
        comp = castle_compound()
        comp["parts"].append({"building": "Castle Rise Building 7", "at": "attached:Castle Rise Building 6:east"})
        d = world(n_castle=7, compounds=[comp])
        zone = d["zones"][0]
        b = next(x for x in zone["buildings"] if x["name"] == "Castle Rise Building 7")
        line = phases._compound_line(d["compounds"], zone, b)
        self.assertIn("attached to Castle Rise Building 6 on its east side", line)

    def test_walkable_walls_say_so(self):
        self.assertIn("walls are walkable", self.line("Castle Rise Building 1"))
        comp = castle_compound()
        comp["walls"] = "solid"
        self.assertNotIn("walkable", self.line("Castle Rise Building 1", comp))


class TestCompoundLineRowSpine(unittest.TestCase):
    """012f change 2: one line per part for the row and spine slots too."""

    def line(self, compound, building):
        d = world(compounds=[compound])
        zone = next(z for z in d["zones"] if z["name"] == compound["zone"])
        b = next(x for x in zone["buildings"] if x["name"] == building)
        return phases._compound_line(d["compounds"], zone, b)

    def test_row_part_names_position_frontage_and_front(self):
        comp = {"name": "Farrow Row", "zone": "Castle Rise", "shape": "row",
                "frontage": "north", "front": "parking",
                "parts": [{"building": f"Castle Rise Building {i + 1}",
                           "at": f"row:{i}"} for i in range(5)]}
        line = self.line(comp, "Castle Rise Building 3")
        self.assertIn("part of Farrow Row", line)
        self.assertIn("third of five in a row facing north", line)
        self.assertIn("parking strip in front", line)
        self.assertIn("one clear cell from Castle Rise Building 2", line)

    def test_row_linked_part_butts_its_neighbour(self):
        comp = {"name": "The Terrace", "zone": "Castle Rise", "shape": "row",
                "frontage": "south", "front": "street",
                "parts": [{"building": "Castle Rise Building 1", "at": "row:0"},
                          {"building": "Castle Rise Building 2", "at": "row:1",
                           "linked": True}]}
        line = self.line(comp, "Castle Rise Building 2")
        self.assertIn("butts Castle Rise Building 1 with a door between them", line)
        self.assertNotIn("one clear cell", line)

    def test_spine_part_names_its_side_and_the_hub(self):
        comp = {"name": "Ruan's Spine", "zone": "Castle Rise", "shape": "spine",
                "axis": "ns", "spineWidth": 3, "hub": "start",
                "parts": [{"building": "Castle Rise Building 1", "at": "spine:hub"},
                          {"building": "Castle Rise Building 2", "at": "spine:left:0"},
                          {"building": "Castle Rise Building 3", "at": "spine:left:1"},
                          {"building": "Castle Rise Building 4", "at": "spine:right:0"}]}
        line = self.line(comp, "Castle Rise Building 3")
        self.assertIn("second of two on the left of a 3-wide corridor", line)
        self.assertIn("running north-south", line)
        self.assertIn("the hub Castle Rise Building 1 gates the block", line)
        hub = self.line(comp, "Castle Rise Building 1")
        self.assertIn("the hub at the start of the corridor", hub)

    def test_cluster_hub_line(self):
        comp = {"name": "The Cluster", "zone": "Castle Rise", "shape": "cluster",
                "axis": "ns", "hub": "center",
                "parts": [{"building": "Castle Rise Building 1", "at": "spine:hub"},
                          {"building": "Castle Rise Building 2", "at": "spine:left:0"}]}
        line = self.line(comp, "Castle Rise Building 1")
        self.assertIn("the hub everything packs round", line)
        self.assertIn("gates the block", line)


class TestP3Units(unittest.TestCase):
    """012f change 2: a unit building's P3 reply carries ONE nested unit
    design; a stray unit on a plain building is an error."""

    TEMPLATES = {"Bed", "Table", "Cupboard"}

    def reply(self, unit=...):
        d = {"name": "Grendel Flats", "wall": "brick", "ground": "wood",
             "rooms": [{"name": "Lobby", "share": "medium", "purpose": "p"}],
             "connections": [], "entrance": {"room": "Lobby", "side": "south"},
             "furniture": []}
        if unit is not ...:
            d["unit"] = unit
        return d

    def unit(self, **over):
        u = {"rooms": [{"name": "Bedroom", "share": "small", "purpose": "p"}],
             "connections": [],
             "entrance": {"room": "Bedroom", "side": "south"},
             "furniture": [{"template": "Bed", "room": "Bedroom", "count": 2}]}
        u.update(over)
        return u

    def units_spec(self):
        return {"name": "Apartment", "count": 12, "perStorey": 4, "residents": 2}

    def test_unit_building_needs_one_unit_design(self):
        errs = phases.check_p3(self.reply(), "Grendel Flats", self.TEMPLATES,
                               False, units=self.units_spec())
        self.assertTrue(any(".unit: required" in e for e in errs))
        errs = phases.check_p3(self.reply(unit=self.unit()), "Grendel Flats",
                               self.TEMPLATES, False, units=self.units_spec())
        self.assertEqual(errs, [])

    def test_unit_design_errors(self):
        bad = self.unit(furniture=[{"template": "Nope", "room": "Bedroom"}],
                        entrance={"room": "Nowhere", "side": "up"})
        errs = phases.check_p3(self.reply(unit=bad), "Grendel Flats",
                               self.TEMPLATES, False, units=self.units_spec())
        self.assertTrue(any("not in the catalogue" in e for e in errs))
        self.assertTrue(any("entrance.room" in e for e in errs))
        self.assertTrue(any("side" in e for e in errs))

    def test_stray_unit_on_a_plain_building(self):
        errs = phases.check_p3(self.reply(unit=self.unit()), "Grendel Flats",
                               self.TEMPLATES, False)
        self.assertTrue(any("repeats no units" in e for e in errs))

    def test_sanitize_keeps_and_cleans_the_unit(self):
        log = []
        d = phases.sanitize_p3(self.reply(unit=self.unit(
            furniture=[{"template": "Nope", "room": "Bedroom"}])), "Grendel Flats",
            self.TEMPLATES, log, units=True)
        self.assertEqual(d["unit"]["furniture"], [])
        self.assertTrue(any("unit furniture" in r for (_w, r) in log))
        log = []
        d = phases.sanitize_p3(self.reply(), "Grendel Flats", self.TEMPLATES,
                               log, units=True)
        self.assertEqual(d["unit"]["rooms"][0]["name"], "Room")
        d = phases.sanitize_p3(self.reply(unit=self.unit()), "Grendel Flats",
                               self.TEMPLATES, log)
        self.assertNotIn("unit", d)

    def test_units_line_tells_p3_what_to_reply(self):
        line = phases._units_line({"units": self.units_spec()})
        self.assertIn("THIS BUILDING REPEATS UNITS", line)
        self.assertIn("12 copies of one 'Apartment'", line)
        self.assertIn("2 residents (one bed each) per copy", line)
        self.assertIn("never design the copies one by one", line)
        self.assertIn("none", phases._units_line({}))

    def test_p3_prompt_carries_units_and_compound_lines(self):
        t = phases._template("p3-building").substitute(
            rules="", setting_line="", zone_line="", building_line="",
            catalogue_lines="", compound_line="LINE", units_line="UNITS",
            pool_lines="", building_name="B")
        self.assertIn("COMPOUND: LINE", t)
        self.assertIn("UNITS: UNITS", t)
        self.assertIn("never list or design the copies one by one", t)

    def test_estimate_skips_same_as_parts(self):
        from worldgen import api
        with open(os.path.join(os.path.dirname(__file__),
                               "..", "fixtures", "shop-strip.plan.json"),
                  encoding="utf-8") as f:
            plan = json.load(f)
        e = api.estimate(plan)
        # five buildings, four of them sameAs copies: one P3 call
        self.assertIn("1 buildings (4 sameAs copies skipped)", e["basis"])


def errors(d):
    return phases.check_p1(d)


class TestCheckP1Compounds(unittest.TestCase):
    def test_valid_compound_and_arrangement_pass(self):
        self.assertEqual(
            [e for e in errors(world(compounds=[castle_compound()],
                                           arrangement="around_green"))
             if "compound" in e or "arrangement" in e], [])

    def test_bad_arrangement(self):
        errs = errors(world(arrangement="ring"))
        self.assertTrue(any("arrangement" in e for e in errs))

    def test_unknown_and_foreign_part_buildings(self):
        comp = castle_compound()
        comp["parts"][0]["building"] = "No Such Building"
        self.assertTrue(any("not in the plan" in e for e in errors(world(compounds=[comp])))
                        or any("is not a zone" in e for e in errors(world(compounds=[comp]))))
        comp = castle_compound()
        comp["parts"][0]["building"] = "Netherford Building 1"
        errs = errors(world(compounds=[comp]))
        self.assertTrue(any("belongs to zone" in e for e in errs))

    def test_slot_used_twice(self):
        comp = castle_compound()
        comp["parts"][1]["at"] = "corner:nw"
        self.assertTrue(any("used twice" in e for e in errors(world(compounds=[comp]))))

    def test_gate_rules(self):
        comp = castle_compound()
        comp["parts"][0]["gate"] = True     # a corner part cannot gate
        self.assertTrue(any("only an enclosure edge part can be the gate" in e
                            for e in errors(world(compounds=[comp]))))
        comp = castle_compound()
        comp["parts"][2]["gate"] = True
        comp["parts"][3]["gate"] = True
        self.assertTrue(any("at most two gates" in e
                            for e in errors(world(compounds=[comp]))))

    def test_bad_shape(self):
        comp = castle_compound()
        comp["shape"] = "ring"
        self.assertTrue(any("shape must be enclosure, row, spine or cluster" in e
                            for e in errors(world(compounds=[comp]))))

    def test_attached_host_rules(self):
        comp = castle_compound()
        comp["parts"].append({"building": "Castle Rise Building 7",
                              "at": "attached:Nope:east"})
        errs = errors(world(n_castle=7, compounds=[comp]))
        self.assertTrue(any("attached host" in e for e in errs))


class TestBuildingCap(unittest.TestCase):
    def test_thirteen_buildings_need_a_compound(self):
        errs = errors(world(n_castle=9, n_village=4))   # 13, no compounds
        self.assertTrue(any("at most 12" in e for e in errs))
        errs = errors(world(n_castle=9, n_village=4,
                                 compounds=[castle_compound()]))
        # the compound names only the first six: three sit outside it, but
        # the compound still raises the cap for the whole reply
        self.assertFalse(any("too many" in e for e in errs))

    def test_seventeen_is_over_even_with_compounds(self):
        errs = errors(world(n_castle=13, n_village=4,
                                 compounds=[castle_compound()]))
        self.assertTrue(any("at most 16" in e for e in errs))


class TestSanitizeP1Compounds(unittest.TestCase):
    def logged(self, d):
        out = []
        d = phases.sanitize_p1(d, out, floors=False)
        return d, out

    def test_bad_compound_and_arrangement_dropped(self):
        comp = castle_compound()
        comp["shape"] = "cluster"
        d = world(compounds=[comp, castle_compound()], arrangement="ring")
        d, log = self.logged(d)
        self.assertEqual([c["name"] for c in d["compounds"]], ["The Ward"])
        self.assertTrue(any("bad structure" in r for (_w, r) in log))
        self.assertNotIn("arrangement", d["zones"][0])
        self.assertTrue(any("arrangement" in r for (_w, r) in log))

    def test_cap_drops_loose_buildings_before_parts(self):
        # 17 buildings with the six-part compound: the five loose ones go,
        # every part stays, the compound survives
        d = world(n_castle=13, n_village=4, compounds=[castle_compound()])
        d, log = self.logged(d)
        self.assertEqual(sum(len(z["buildings"]) for z in d["zones"]), 16)
        names = {b["name"] for z in d["zones"] for b in z["buildings"]}
        for p in d["compounds"][0]["parts"]:
            self.assertIn(p["building"], names)
        self.assertTrue(any("over the 16-building cap" in r for (_w, r) in log))

    def test_compound_losing_its_part_is_dropped(self):
        # two all-parts compounds of nine buildings each: the 16 cap drops
        # two parts, and the compound they belonged to goes with them
        def nine(name, first):
            return {"name": name, "zone": "Castle Rise", "shape": "enclosure",
                    "courtyard": "small", "walls": "solid",
                    "parts": [{"building": f"Castle Rise Building {first + k}", "at": at}
                              for k, at in enumerate(
                                  ("corner:nw", "corner:ne", "corner:se", "corner:sw",
                                   "edge:south:center", "edge:north:center",
                                   "edge:west:center", "edge:east:center",
                                   "inside:center"))]}
        d = world(n_castle=18, n_village=0,
                  compounds=[nine("The Ward", 1), nine("The Bailey", 10)])
        d, log = self.logged(d)
        self.assertEqual(len(d["compounds"]), 1)
        self.assertTrue(any("did not survive" in r for (_w, r) in log))
        for p in d["compounds"][0]["parts"]:
            self.assertIn(p["building"],
                          {b["name"] for z in d["zones"] for b in z["buildings"]})


class TestPromptText(unittest.TestCase):
    def test_p1_prompt_teaches_the_vocabulary(self):
        t = phases._template("p1-world").substitute(rules="", idea="x")
        for bit in ("compounds", "arrangement", "around_green", "corner:nw",
                    "attached:", "gate", "4 more when", "monastery",
                    "Most buildings are not in a compound"):
            self.assertIn(bit, t)

    def test_p1_prompt_teaches_every_shape_and_units(self):
        t = phases._template("p1-world").substitute(rules="", idea="x")
        for bit in ("enclosure", "row", "spine", "cluster", "sameAs",
                    "units", "residents", "void", "frontage",
                    "spineWidth", "linked", "exterior",
                    "Never list or design the copies one by one",
                    "not templates. Combine shapes freely"):
            self.assertIn(bit, t)
        # four setting examples, none of them the only way to build
        for bit in ("castle", "strip mall", "hospital", "starship"):
            self.assertIn(bit, t)

    def test_floors_fragment_teaches_storeys_and_per_storey(self):
        path = os.path.join(os.path.dirname(phases.PROMPTS_DIR),
                            "prompts", "ext", "floors", "p1-world.txt")
        with open(path, "r", encoding="utf-8") as f:
            frag = f.read()
        for bit in ("storeys", "perStorey", "numbering", "up to 6"):
            self.assertIn(bit, frag)

    def test_p3_prompt_carries_the_compound_line(self):
        t = phases._template("p3-building").substitute(
            rules="", setting_line="", zone_line="", building_line="",
            catalogue_lines="", compound_line="LINE", units_line="none",
            pool_lines="", building_name="B")
        self.assertIn("COMPOUND: LINE", t)
        self.assertIn("UNITS: none", t)


class TestCheckP1UnitsAndShapes(unittest.TestCase):
    """012f change 1: the raw reply's units, storeys cap, void zones and the
    row/spine compound fields all validate, and sanitize fixes them."""

    def unit_building(self, **units):
        d = world()
        d["zones"][0]["buildings"][0]["units"] = \
            {"name": "Apartment", "count": 12, "perStorey": 4, "residents": 2}
        d["zones"][0]["buildings"][0]["units"].update(units)
        return d

    def test_good_units_pass_and_rise_to_six_storeys(self):
        d = self.unit_building()
        d["zones"][0]["buildings"][0]["storeys"] = 6
        self.assertEqual([e for e in errors(d) if "units" in e or "storeys" in e], [])

    def test_bad_units_fields(self):
        for bad in ({"count": 0}, {"count": "many"}, {"perStorey": 99},
                    {"residents": -1}, {"numbering": "roman"}, {"name": ""}):
            with self.subTest(bad=bad):
                self.assertTrue(any("units" in e for e in errors(self.unit_building(**bad))))

    def test_seven_storeys_needs_units_or_a_compound_part(self):
        d = self.unit_building()
        d["zones"][0]["buildings"][0]["storeys"] = 7
        self.assertTrue(any("1..6" in e for e in phases.check_p1(d, floors=True)))
        d = world()
        d["zones"][0]["buildings"][0]["storeys"] = 7
        self.assertTrue(any("1..3" in e for e in phases.check_p1(d, floors=True)))
        # a compound part rises to 6 too
        d = world(compounds=[castle_compound()])
        d["zones"][0]["buildings"][0]["storeys"] = 6
        self.assertFalse(any("storeys" in e for e in phases.check_p1(d, floors=True)))

    def test_sanitize_fixes_units_and_bad_exterior(self):
        d = self.unit_building(perStorey="all", residents=99, numbering="roman")
        d["zones"][0]["exterior"] = "space"
        out = []
        d = phases.sanitize_p1(d, out, floors=True)
        u = d["zones"][0]["buildings"][0]["units"]
        self.assertEqual((u["perStorey"], u["residents"], u["numbering"]),
                         (0, 0, "plain"))
        self.assertNotIn("exterior", d["zones"][0])
        self.assertTrue(any("exterior" in r for (_w, r) in out))

    def test_row_and_spine_fields_validate(self):
        comp = {"name": "The Row", "zone": "Castle Rise", "shape": "row",
                "frontage": "up", "front": "canal",
                "parts": [{"building": "Castle Rise Building 1", "at": "row:0"}]}
        errs = errors(world(compounds=[comp]))
        self.assertTrue(any("frontage" in e for e in errs))
        self.assertTrue(any("front must be" in e for e in errs))
        comp = {"name": "The Spine", "zone": "Castle Rise", "shape": "spine",
                "axis": "diagonal", "spineWidth": 9,
                "parts": [{"building": "Castle Rise Building 1", "at": "spine:hub"}]}
        errs = errors(world(compounds=[comp]))
        self.assertTrue(any("axis" in e for e in errs))
        self.assertTrue(any("spineWidth" in e for e in errs))

    def test_same_as_rules(self):
        comp = castle_compound()
        comp["shape"] = "spine"
        comp["axis"] = "ns"
        comp["hub"] = "start"
        comp["parts"] = [
            {"building": "Castle Rise Building 1", "at": "spine:hub"},
            {"building": "Castle Rise Building 2", "at": "spine:left:0",
             "sameAs": "Castle Rise Building 1"},
            {"building": "Castle Rise Building 3", "at": "spine:right:0",
             "sameAs": "Castle Rise Building 2"}]
        errs = errors(world(n_castle=3, compounds=[comp]))
        self.assertTrue(any("itself uses sameAs" in e for e in errs))
        comp["parts"][2]["sameAs"] = "Nope"
        errs = errors(world(n_castle=3, compounds=[comp]))
        self.assertTrue(any("sameAs target" in e for e in errs))

    def test_cluster_needs_a_hub_and_spine_takes_no_gate(self):
        comp = {"name": "The Cluster", "zone": "Castle Rise", "shape": "cluster",
                "axis": "ns", "hub": "center",
                "parts": [{"building": "Castle Rise Building 1", "at": "spine:left:0"},
                          {"building": "Castle Rise Building 2", "at": "spine:right:0"}]}
        self.assertTrue(any("needs one part at spine:hub" in e
                            for e in errors(world(compounds=[comp]))))
        comp["parts"].append({"building": "Castle Rise Building 3", "at": "spine:hub"})
        self.assertEqual([e for e in errors(world(n_castle=3, compounds=[comp]))], [])
        comp["shape"] = "spine"
        comp["spineWidth"] = 3
        comp["parts"][2]["gate"] = True
        errs = errors(world(n_castle=3, compounds=[comp]))
        self.assertTrue(any("takes no gate parts" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
