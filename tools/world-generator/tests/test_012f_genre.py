"""Brief 012f change 4: the genre fixtures — a modern quarter (a six-storey
apartment block whose copied flats draw from a kitchen pool and a bathroom
pool, a parking strip whose clothing store and sporting goods store share one
Store shelf template over different pools, two sameAs kiosks), an all-void
starship with a three-deck crew block of cabins, and the hospital spine
carrying its item catalogue. Containers in copied units differ, each store's
shelves hold only their own pool's items, and every build passes the vendored
builder and validator. Renders live in out/012f-*.png."""
import json
import os
import shutil
import tempfile
import unittest

import worldgen
from worldgen import api
from tests import util


def placements_of(spec, template):
    t = next(t for t in spec["objectTemplates"] if t["name"] == template)
    return t.get("placements", [])


def inventories_in(placements, region_prefix=""):
    """{region name: [item names]} for the placements that drew a starting
    inventory; a placement inside a walled region names the room first."""
    out = {}
    for p in placements:
        if isinstance(p, dict):
            pos, inv = p["pos"], p.get("inventory") or []
        else:
            pos, inv = p, []
        if isinstance(pos[0], str):
            name = pos[0]
            if not (region_prefix and not name.startswith(region_prefix)):
                out.setdefault(name, set()).update(n for (n, _c) in inv)
    return out


class TestModernQuarter(unittest.TestCase):
    """The modern fixture: the flats' 24 copied apartments draw kitchen and
    bathroom inventories that differ per copy, and the two stores' shared
    Store shelf template never leaks one pool into the other store."""

    PLAN = "modern-quarter.plan.json"

    @classmethod
    def setUpClass(cls):
        cls.data = util.load_plan(cls.PLAN)

    def build(self, exts, seed=1):
        data = dict(self.data)
        if not exts:
            data.pop("extensions", None)   # a no-extension build ignores the plan's own
        return worldgen.run(data, seed=seed, extensions=exts)

    def test_builds_clean_plain_and_floors(self):
        for exts in ((), ("floors",)):
            with self.subTest(ext=",".join(exts) or "none"):
                w = self.build(exts)
                self.assertEqual(w.metrics["errors"]["dropped"], [])
                self.assertEqual(w.metrics["reachability"], 1.0)
                self.assertEqual(w.failures, [])

    def test_floors_stamp_the_full_block(self):
        w = self.build(("floors",))
        self.assertEqual(len(w.floors), 5)          # 5 upper storeys
        self.assertEqual(len(w.portals), 5)
        names = {r.name for r in w.regions if r.name}
        for i in (1, 12, 24):
            self.assertIn(f"Apartment {i}", names)
        comp = w.compounds[0]
        self.assertEqual(comp.front_kind, "parking")
        self.assertIsNotNone(comp.parking)
        self.assertTrue(comp.parking[2], "the parking strip carries vehicle slots")

    def test_copied_units_containers_differ(self):
        w = self.build(("floors",))
        spec = worldgen.build_spec(w, self.data)
        for template, pool in (("Bathroom cabinet", "Bathroom cabinet"),
                               ("Kitchen cupboard", "Kitchen cupboard")):
            with self.subTest(template=template):
                placements = placements_of(spec, template)
                self.assertEqual(len(placements), 24, template)
                invs = {tuple(map(tuple, p["inventory"]))
                        for p in placements if isinstance(p, dict)}
                self.assertGreater(len(invs), 1,
                                   f"{template} copies all drew the same stock")
                allowed = set(self.data["lootPools"][pool]["items"])
                for p in placements:
                    if isinstance(p, dict):
                        self.assertTrue({n for (n, _c) in p["inventory"]} <= allowed)

    def test_each_stores_shelves_hold_only_their_own_pool(self):
        w = self.build(())
        spec = worldgen.build_spec(w, self.data)
        by_store = inventories_in(placements_of(spec, "Store shelf"))
        self.assertTrue(any(k.startswith("Bolt & Bias") for k in by_store),
                        sorted(by_store))
        self.assertTrue(any(k.startswith("Fielder's Gear") for k in by_store),
                        sorted(by_store))
        pools = self.data["lootPools"]
        for region, items in by_store.items():
            with self.subTest(region=region):
                if region.startswith("Bolt & Bias"):
                    self.assertTrue(items <= set(pools["Clothing shelf"]["items"]),
                                    items)
                elif region.startswith("Fielder's Gear"):
                    self.assertTrue(items <= set(pools["Sporting shelf"]["items"]),
                                    items)

    def test_the_two_kiosks_share_one_design(self):
        w = self.build(())
        names = {r.name for r in w.regions if r.name}
        self.assertIn("Left Kiosk", names)
        self.assertIn("Right Kiosk", names)
        w2 = self.build(("floors",))
        spec = worldgen.build_spec(w2, self.data)
        by_kiosk = inventories_in(placements_of(spec, "Kiosk rack"))
        self.assertTrue(any(k.startswith("Left Kiosk") for k in by_kiosk),
                        sorted(by_kiosk))
        self.assertTrue(any(k.startswith("Right Kiosk") for k in by_kiosk),
                        sorted(by_kiosk))
        allowed = set(self.data["lootPools"]["Kiosk stock"]["items"])
        for items in by_kiosk.values():
            self.assertTrue(items <= allowed, items)

    def test_vendored_build_passes_both_modes(self):
        tmp = tempfile.mkdtemp(prefix="worldgen-012f-modern-")
        try:
            for exts in ((), ("floors",)):
                with self.subTest(ext=",".join(exts) or "none"):
                    data = dict(self.data)
                    if not exts:
                        data.pop("extensions", None)
                    summary = api._layout_and_build(
                        data, seed=1, out_dir=os.path.join(tmp, ",".join(exts) or "none"),
                        extra_exts=exts)
                    self.assertTrue(summary["ok"], summary)
                    self.assertEqual(summary["validator_errors"], 0, summary)
                    self.assertEqual(summary["reachability"], 1.0, summary)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestStarshipDecks(unittest.TestCase):
    """The sci-fi fixture: an all-void ship whose crew block carries 12 cabins
    over three decks (floors mode), each cabin's locker drawing from the crew
    pool; plain mode builds the ground deck clean."""

    PLAN = "starship-decks.plan.json"

    @classmethod
    def setUpClass(cls):
        cls.data = util.load_plan(cls.PLAN)

    def build(self, exts, seed=1):
        data = dict(self.data)
        if not exts:
            data.pop("extensions", None)
        return worldgen.run(data, seed=seed, extensions=exts)

    def test_builds_clean_plain_and_floors(self):
        for exts in ((), ("floors",)):
            with self.subTest(ext=",".join(exts) or "none"):
                w = self.build(exts)
                self.assertEqual(w.metrics["errors"]["dropped"], [])
                self.assertEqual(w.metrics["reachability"], 1.0)
                self.assertEqual(w.failures, [])

    def test_crew_block_stamps_three_decks_of_cabins(self):
        w = self.build(("floors",))
        self.assertEqual(len(w.floors), 2)          # 2 upper decks
        self.assertEqual(len(w.portals), 2)
        names = {r.name for r in w.regions if r.name}
        for i in (1, 7, 12):
            self.assertIn(f"Cabin {i}", names)
        spec = worldgen.build_spec(w, self.data)
        placements = placements_of(spec, "Wall locker")
        self.assertEqual(len(placements), 13, "12 cabins and the bridge locker")
        invs = {tuple(map(tuple, p["inventory"]))
                for p in placements if isinstance(p, dict)}
        self.assertGreater(len(invs), 1, "cabin lockers all drew the same stock")
        allowed = set(self.data["lootPools"]["Crew locker"]["items"])
        for p in placements:
            if isinstance(p, dict):
                self.assertTrue({n for (n, _c) in p["inventory"]} <= allowed)

    def test_plain_mode_stamps_the_ground_deck(self):
        w = self.build(())
        self.assertEqual(getattr(w, "floors", []) or [], [])
        names = {r.name for r in w.regions if r.name}
        self.assertIn("Cabin 1", names)
        self.assertNotIn("Cabin 12", names)

    def test_the_map_stays_sealed(self):
        w = self.build(())
        self.assertTrue(w.void_default)
        self.assertEqual(w.void_zones, {"Relay Dock", "The Calliope"})
        walled = {(x, y) for r in w.regions if r.wall
                  for (x, y) in r.rect.cells()}
        slabbed = {(x, y) for o in w.objects if "Void Slab" in o.template
                   for x in range(o.pos[0], o.pos[0] + w.templates[o.template].size[0])
                   for y in range(o.pos[1], o.pos[1] + w.templates[o.template].size[1])}
        every = {(x, y) for x in range(w.grid[0]) for y in range(w.grid[1])}
        self.assertEqual(every - walled - slabbed, set())

    def test_vendored_build_passes_both_modes(self):
        tmp = tempfile.mkdtemp(prefix="worldgen-012f-ship-")
        try:
            for exts in ((), ("floors",)):
                with self.subTest(ext=",".join(exts) or "none"):
                    data = dict(self.data)
                    if not exts:
                        data.pop("extensions", None)
                    summary = api._layout_and_build(
                        data, seed=1, out_dir=os.path.join(tmp, ",".join(exts) or "none"),
                        extra_exts=exts)
                    self.assertTrue(summary["ok"], summary)
                    self.assertEqual(summary["validator_errors"], 0, summary)
                    self.assertEqual(summary["reachability"], 1.0, summary)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestHospitalCatalogue(unittest.TestCase):
    """The hospital fixture's own item catalogue: every bedside locker in the
    two wards' twelve patient rooms draws from the ward pool (copies differ),
    the medicine cabinets from the medicine pool, and the scenario carries the
    itemTemplates through the vendored builder."""

    @classmethod
    def setUpClass(cls):
        cls.data = util.load_plan("hospital-spine.plan.json")

    def test_builds_clean(self):
        for seed in (1, 2):
            with self.subTest(seed=seed):
                w = worldgen.run(self.data, seed=seed)
                self.assertEqual(w.metrics["errors"]["dropped"], [])
                self.assertEqual(w.metrics["reachability"], 1.0)
                self.assertEqual(w.failures, [])

    def test_lockers_draw_the_ward_pool_and_differ(self):
        w = worldgen.run(self.data, seed=1)
        spec = worldgen.build_spec(w, self.data)
        placements = placements_of(spec, "Bedside locker")
        self.assertEqual(len(placements), 8,
                         "the north ward's six patient rooms and the two sluices")
        invs = {tuple(map(tuple, p["inventory"]))
                for p in placements if isinstance(p, dict)}
        self.assertGreater(len(invs), 1, "the ward lockers all drew the same stock")
        pools = self.data["lootPools"]
        allowed = set(pools["Bedside locker"]["items"])
        for p in placements:
            if isinstance(p, dict):
                self.assertTrue({n for (n, _c) in p["inventory"]} <= allowed)
        meds = inventories_in(placements_of(spec, "Medicine cabinet"))
        med_allowed = set(pools["Ward medicine"]["items"])
        for items in meds.values():
            self.assertTrue(items <= med_allowed, items)
        self.assertEqual(len(spec["itemTemplates"]), len(self.data["items"]))

    def test_vendored_build_passes(self):
        tmp = tempfile.mkdtemp(prefix="worldgen-012f-hosp-")
        try:
            summary = api._layout_and_build(self.data, seed=1, out_dir=tmp)
            self.assertTrue(summary["ok"], summary)
            self.assertEqual(summary["validator_errors"], 0, summary)
            self.assertEqual(summary["reachability"], 1.0, summary)
            path = os.path.join(summary["out"], summary["zip"][:-len(".zip")],
                                "scenario.json")
            with open(path, "r", encoding="utf-8") as f:
                scn = json.load(f)
            self.assertEqual(len(scn["itemTemplates"]), len(self.data["items"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
