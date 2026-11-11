"""The 1.0 liquids and natural shapes, as the game's own code reads them: the blob mask matches the golden
fixture produced from the game (Hhe), surfaces resolve against unbounded.profile.media or the built-in
waters with the game's appends and its 8-entry limit, long thin liquids are rivers, and the wet cells of an
organic pond are exactly its blob. See also test_scenario_1_0.py for the older 1.0 checks.
"""
import json
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


def scenario(regions=(), entities=(), **kw):
    scn = {"name": "T", "gridSize": [30, 20], "playerId": "p", "stancesAuthored": True,
           "regions": [region("r_yard", "Yard", (0, 0), (30, 20), wall=None)] + list(regions),
           "objectTemplates": [], "itemTemplates": [],
           "entities": [{"id": "p", "type": "player", "name": "Hero", "pos": [2, 2], "gender": "female",
                         "animationId": "casual-woman", "inventory": [], "statusEffects": [],
                         "schedule": [{"start": "00:00", "end": "00:00", "location": "Yard", "role": "leisure"}]}]
           + list(entities)}
    scn.update(kw)
    return scn


def found(scn, level=None):
    return [f["msg"] for f in sc.check(scn) if level is None or f["level"] == level]


def media(names, walk="no"):
    return [{"name": n, "walk": walk, "color": "#24506e"} for n in names]


class BlobMask(unittest.TestCase):
    def test_matches_the_1_0_golden_fixture(self):
        fx = json.loads((Path(__file__).resolve().parent / "organic-blobs-1.0.json").read_text("utf-8"))
        for c in fx["cases"]:
            m = sc.blob_mask(c["id"], c["w"], c["h"])
            self.assertEqual(len(m), c["w"] * c["h"])
            for y, row in enumerate(c["rows"]):
                self.assertEqual("".join(str(m[y * c["w"] + x]) for x in range(c["w"])), row,
                                 f"{c['id']} {c['w']}x{c['h']} row {y}")


class Shapes(unittest.TestCase):
    def test_natural_reads_as_organic(self):
        scn = scenario([region("r_green", "Green", (4, 4), (8, 8), wall=None, shape="Natural")])
        self.assertIn("Region 'Green': the game reads 'natural' as 'organic'.", found(scn, "info"))
        self.assertFalse([m for m in found(scn, "warning") if "Green" in m])
        scn["regions"][1]["shape"] = "organic"
        self.assertFalse([m for m in found(scn) if "Green" in m])

    def test_any_case_is_organic_and_meta_offers_only_organic(self):
        scn = scenario([region("r_wood", "Wood", (4, 4), (8, 8), wall=None, shape=" ORGANIC ")])
        self.assertFalse([m for m in found(scn) if "Wood" in m])
        self.assertEqual(sc.meta()["shapes"], ["organic"])

    def test_other_shapes_still_warn(self):
        scn = scenario([region("r_hill", "Hill", (4, 4), (8, 8), wall=None, shape="blob")])
        self.assertIn("Region 'Hill': shape 'blob' isn't 'organic'; the game draws a rectangle.", found(scn, "warning"))


class Surfaces(unittest.TestCase):
    def test_the_game_trims_and_lowercases_the_surface(self):
        scn = scenario([region("r_pond", "Pond", (4, 4), (6, 6), wall=None, surface="  Deep Water ")])
        self.assertIn("Region 'Pond': the game reads surface '  Deep Water ' as 'deep water'.", found(scn, "info"))
        self.assertFalse([m for m in found(scn) if "adds it as a new deep liquid" in m])  # the defaults match it

    def test_an_unknown_surface_is_added_as_a_new_deep_liquid(self):
        scn = scenario([region("r_pond", "Pond", (4, 4), (6, 6), wall=None, surface="ink")])
        self.assertIn("Region 'Pond': liquid 'ink' isn't in the media list, so the game adds it as a new deep "
                      "liquid nobody can walk through.", found(scn, "info"))

    def test_a_later_region_finds_what_the_game_added(self):
        scn = scenario([region("r_a", "A", (4, 4), (6, 6), wall=None, surface="ink"),
                        region("r_b", "B", (12, 4), (6, 6), wall=None, surface="ink")],
                       unbounded={"seed": 1, "profile": {"media": media(["creek"]), "lowEdges": []}, "areas": []})
        self.assertEqual(len([m for m in found(scn, "info") if "adds it as a new deep liquid" in m]), 1)

    def test_a_full_media_list_leaves_the_surface_ignored(self):
        scn = scenario([region("r_pond", "Pond", (4, 4), (6, 6), wall=None, surface="ink")],
                       unbounded={"seed": 1, "profile": {"media": media([f"m{n}" for n in range(8)]),
                                                         "lowEdges": []}, "areas": []})
        self.assertIn("Region 'Pond': surface 'ink' is ignored; unbounded.profile.media already has 8 entries "
                      "and the game adds no more.", found(scn, "warning"))

    def test_a_substring_names_the_medium_it_resolves_to(self):
        scn = scenario([region("r_pond", "Pond", (4, 4), (6, 6), wall=None, surface="water")],
                       unbounded={"seed": 1, "profile": {"media": [
                           {"name": "shallow water", "walk": "slow", "color": "#3f7f90"},
                           {"name": "deep water", "walk": "no", "color": "#24506e"}], "lowEdges": []}, "areas": []})
        self.assertIn("Region 'Pond': the game reads liquid 'water' as 'deep water' (walk: no).", found(scn, "info"))

    def test_a_long_thin_liquid_is_a_river(self):
        scn = scenario([region("r_rill", "Rill", (4, 4), (3, 9), wall=None, surface="deep water")])
        self.assertIn("Region 'Rill' is long and thin, so the game draws it as a river 3 cells wide, not a pool.",
                      found(scn, "info"))
        scn["regions"][1] = region("r_rill", "Rill", (4, 4), (3, 8), wall=None, surface="deep water")
        self.assertFalse([m for m in found(scn, "info") if "river" in m])   # one cell short of 3 x 3
        scn = scenario([region("r_lake", "Lake", (4, 4), (13, 40), wall=None, surface="deep water")],
                       gridSize=[60, 60])
        self.assertFalse([m for m in found(scn, "info") if "river" in m])   # too wide, however long


class Unbounded(unittest.TestCase):
    def test_a_broken_media_list_with_a_surface_is_an_error(self):
        pond = region("r_pond", "Pond", (4, 4), (6, 6), wall=None, surface="ink")
        scn = scenario([pond], unbounded={"seed": 1, "profile": {}, "areas": []})
        self.assertIn("unbounded.profile.media is not a list; the game fails to load the scenario as soon as a "
                      "region has a surface.", found(scn, "error"))
        self.assertFalse([m for m in found(scenario(unbounded={"seed": 1, "profile": {}, "areas": []}), "error")
                          if "unbounded" in m])  # without a surface it only matters later

    def test_each_media_entry_is_checked(self):
        scn = scenario(unbounded={"seed": 1, "profile": {"media": [
            {"name": "Creek", "walk": "wade", "color": "blue", "flows": "yes"},
            {"name": "creek", "walk": "slow", "color": "#4f7a6e", "flows": True, "glow": False},
            {"name": "l" * 41, "walk": "yes"}], "lowEdges": []}, "areas": []})
        out = found(scn, "warning")
        self.assertIn("unbounded.profile.media entry 'Creek': name must be a lowercase string of 1-40 characters.", out)
        self.assertIn("unbounded.profile.media: two entries named 'creek'; the game's own names are unique.", out)
        self.assertIn("unbounded.profile.media entry 'Creek': walk 'wade' isn't yes, slow or no.", out)
        self.assertIn("unbounded.profile.media entry 'Creek': color 'blue' isn't a colour like #24506e.", out)
        self.assertIn("unbounded.profile.media entry 'Creek': flows must be true or false.", out)
        self.assertIn(f"unbounded.profile.media entry '{'l' * 41}': name must be a lowercase string of 1-40 "
                      "characters.", out)
        self.assertIn(f"unbounded.profile.media entry '{'l' * 41}': color None isn't a colour like #24506e.", out)

    def test_more_than_eight_entries_and_a_missing_seed(self):
        scn = scenario(unbounded={"profile": {"media": media([f"m{n}" for n in range(9)]), "lowEdges": []},
                                  "areas": []})
        self.assertIn("unbounded.profile.media has 9 entries; the game's own lists have at most 8, and it adds "
                      "no more.", found(scn, "info"))
        self.assertIn("unbounded.seed should be a number.", found(scn, "warning"))


class LiquidCells(unittest.TestCase):
    def test_an_organic_deep_pond_wets_exactly_its_blob(self):
        pond = region("region_pond", "Pond", (10, 10), (5, 5), wall=None, surface="deep water", shape="organic")
        scn = scenario([pond])
        wet = sc.liquid_cells(scn, scn["regions"])
        mask = sc.blob_mask("region_pond", 5, 5)
        blob = {(10 + x, 10 + y) for y in range(5) for x in range(5) if mask[y * 5 + x]}
        self.assertEqual(wet, blob)
        self.assertEqual(len(wet), 19)

    def test_a_slow_liquid_and_an_ignored_one_wet_nothing(self):
        scn = scenario([region("r_creek", "Creek", (4, 4), (6, 6), wall=None, surface="creek")],
                       unbounded={"seed": 1, "profile": {"media": [{"name": "creek", "walk": "slow",
                                                                   "color": "#4f7a6e"}], "lowEdges": []},
                                  "areas": []})
        self.assertEqual(sc.liquid_cells(scn, scn["regions"]), set())
        scn = scenario([region("r_pond", "Pond", (4, 4), (6, 6), wall=None, surface="ink")],
                       unbounded={"seed": 1, "profile": {"media": media([f"m{n}" for n in range(8)]),
                                                         "lowEdges": []}, "areas": []})
        self.assertEqual(sc.liquid_cells(scn, scn["regions"]), set())


if __name__ == "__main__":
    unittest.main()
