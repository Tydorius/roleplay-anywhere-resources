"""Upper storeys as Anywhere RPG 1.0 native floors: a generated multi-storey
world builds into the unmodded game — every storey a pocket region outside
gridSize, its stairs a pair of objects pointing at each other, no
arpgMods.floors/portals, no boundary strip or slab, and the vendored 1.0
scenario checker reporting nothing against it."""
import json
import os
import shutil
import tempfile
import unittest

from worldgen import api
from worldgen.vendor import scenario_checks

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
BOUNDARY = "The Edge of the World"   # the retired boundary region
SLAB = "The World's Edge"            # the retired slab object


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


class TestFloorsNative(unittest.TestCase):
    """fixtures/floors-plan.json built with the floors extension: a
    two-storey inn and a three-storey apartment block, shipped as 1.0
    floors."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-floors-native-")
        cls.data = load("floors-plan.json")
        cls.summary = api._layout_and_build(cls.data, seed=1, out_dir=cls.tmp,
                                            extra_exts=("floors",))
        path = os.path.join(cls.summary["out"],
                            cls.summary["zip"][:-len(".zip")], "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.scn = json.load(f)
        cls.path = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _floors(self):
        return [r for r in self.scn["regions"] if r.get("pocket")]

    def test_the_build_is_ok(self):
        self.assertTrue(self.summary["ok"], self.summary)
        self.assertEqual(self.summary["validator_errors"], 0, self.summary)

    def test_every_storey_is_a_pocket_off_its_building(self):
        by_name = {r["name"]: r for r in self.scn["regions"]}
        storeys = {"The Sickle & Sheaf (upper floor)": ("The Sickle & Sheaf", 1),
                   "Weaver's Rows (upper floor)": ("Weaver's Rows", 1),
                   "Weaver's Rows (top floor)": ("Weaver's Rows", 2)}
        self.assertEqual({r["name"] for r in self._floors()}, set(storeys))
        for name, (anchor, level) in storeys.items():
            r = by_name[name]
            self.assertEqual(r["pocket"], {"anchor": by_name[anchor]["id"],
                                           "level": level}, name)

    def test_the_stairs_point_at_each_other(self):
        ents = {e["name"]: e for e in self.scn["entities"] if e["type"] == "object"}
        linked = [e for e in ents.values() if e.get("portal")]
        self.assertTrue(linked)
        for e in linked:
            other = ents.get(next(
                n for n, o in ents.items()
                if o.get("id") == e["portal"]["to"]))
            self.assertEqual(other["portal"], {"to": e["id"]},
                             f"{e['name']} is not linked back")

    def test_no_game_mod_floors_or_portals(self):
        mods = self.scn.get("arpgMods")
        if mods is None:
            return   # nothing but the native floors: the plain 1.0 game plays it
        self.assertNotIn("floors", mods)
        self.assertNotIn("portals", mods)

    def test_no_boundary_region_or_slab_object(self):
        for r in self.scn["regions"]:
            self.assertNotEqual(r["name"], BOUNDARY, r["name"])
        for t in self.scn["objectTemplates"]:
            self.assertNotEqual(t["name"], SLAB, t["name"])
        for e in self.scn["entities"]:
            self.assertFalse(e["name"].startswith(SLAB), e["name"])

    def test_the_floors_sit_outside_gridsize(self):
        gw, gh = self.scn["gridSize"]
        # gridSize is the play area the generator laid out, ungrown
        self.assertEqual([gw, gh], [int(n) for n in self.summary["grid"].split("x")])
        rects = []
        for r in self._floors():
            x, y = r["position"]
            w, h = r["size"]
            self.assertGreaterEqual(x, gw, f"{r['name']} lies on the map")
            self.assertGreaterEqual(y, 0)
            rects.append((x, x + w - 1))
        rects.sort()
        for (ax0, ax1), (bx0, _bx1) in zip(rects, rects[1:]):
            self.assertGreaterEqual(bx0 - ax1 - 1, 24,
                                    "two floors are under 24 cells apart")

    def test_the_vendored_checker_reports_no_errors(self):
        scn, media = scenario_checks.load(self.path)
        found = scenario_checks.check(scn, media)
        errors = [f["msg"] for f in found if f["level"] == "error"]
        self.assertEqual(errors, [], errors)


if __name__ == "__main__":
    unittest.main()
