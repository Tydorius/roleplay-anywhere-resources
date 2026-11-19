"""rl-14e: the farming item set (tools, tack, materials, produce and the
sci-fi growing consumables). Every new item loads from its file and checks,
reaches the item menu in each of its bands, and sits in loot pools named
after the room purposes a farm's rooms use, so containers there draw them
(``pool_for_purpose`` binds a room to the pool named after its purpose);
tack never reaches the modern or sci-fi menus."""
import unittest

from worldgen import item_library as IL
from worldgen import library_items as LIT
from worldgen import library_plan

# id -> (file, bands): the farming set of plan rl-13r section 2.5
NEW_ITEMS = {
    "tool.sickle": ("tools.json", ("medieval", "industrial")),
    "tool.pitchfork": ("tools.json", ("medieval", "industrial")),
    "tool.hoe": ("tools.json", ("medieval", "industrial", "modern")),
    "tool.shears": ("tools.json", ("medieval", "industrial")),
    "tool.flail": ("tools.json", ("medieval", "industrial")),
    "tool.winnowing_basket": ("tools.json", ("medieval", "industrial")),
    "tool.bee_smoker": ("tools.json", ("industrial", "modern")),
    "tool.branding_iron": ("tools.json", ("industrial", "modern")),
    "tool.halter": ("tools.json", ("medieval", "industrial")),
    "tool.bridle": ("tools.json", ("medieval", "industrial")),
    "tool.saddle": ("tools.json", ("medieval", "industrial")),
    "tool.harness_set": ("tools.json", ("medieval", "industrial")),
    "tool.yoke": ("tools.json", ("medieval", "industrial")),
    "material.seed_sack": ("materials.json", ("medieval", "industrial")),
    "material.feed_sack": ("materials.json", ("medieval", "industrial")),
    "material.tallow": ("materials.json", ("medieval", "industrial")),
    "material.beeswax": ("materials.json", ("medieval", "industrial")),
    "material.fertiliser_bag": ("materials.json", ("modern",)),
    "material.straw_bale": ("materials.json", ("medieval", "industrial", "modern")),
    "food.honeycomb": ("food_drink.json", ("medieval", "industrial")),
    "food.mutton": ("food_drink.json", ("medieval", "industrial")),
    "food.fresh_cheese": ("food_drink.json", ("medieval", "industrial")),
    "medicine.vet_kit": ("medicine.json", ("modern",)),
    "tech.nutrient_cartridge": ("tech.json", ("scifi",)),
    "tech.seed_vial": ("tech.json", ("scifi",)),
    "tech.soil_probe": ("tech.json", ("scifi",)),
}

TACK = ("tool.halter", "tool.bridle", "tool.saddle", "tool.harness_set",
        "tool.yoke")

# the loot pools a farm's rooms draw from, as the p2-items call writes them
# (one per room purpose, filled from that band's menu). dairy and granary
# pools are written ahead of their room-library purposes, which land with
# the farming vocabulary; pool_for_purpose binds them by name either way.
POOLS = {
    "medieval": {
        "Stable": TACK,
        "Barn": ("tool.sickle", "tool.flail", "tool.winnowing_basket",
                 "tool.pitchfork", "material.straw_bale", "material.tallow"),
        "Farmyard": ("tool.hoe", "tool.shears", "material.feed_sack",
                     "material.straw_bale", "material.beeswax",
                     "food.honeycomb", "food.mutton"),
        "Dairy": ("food.fresh_cheese",),
        "Granary": ("material.seed_sack", "material.grain_sack"),
    },
    "industrial": {
        "Stable": TACK,
        "Barn": ("tool.sickle", "tool.flail", "tool.winnowing_basket",
                 "tool.pitchfork", "material.straw_bale", "material.tallow",
                 "tool.branding_iron"),
        "Farmyard": ("tool.hoe", "tool.shears", "material.feed_sack",
                     "material.straw_bale", "material.beeswax",
                     "tool.bee_smoker", "food.honeycomb", "food.mutton"),
        "Dairy": ("food.fresh_cheese",),
        "Granary": ("material.seed_sack", "material.grain_sack"),
    },
    "modern": {
        "Barn": ("material.straw_bale", "tool.branding_iron"),
        "Farmyard": ("tool.hoe", "tool.bee_smoker", "material.fertiliser_bag",
                     "material.straw_bale", "medicine.vet_kit"),
        "Greenhouse": ("material.fertiliser_bag",),
    },
    "scifi": {
        "Hydroponics bay": ("tech.nutrient_cartridge", "tech.seed_vial",
                            "tech.soil_probe"),
        "Greenhouse": ("tech.nutrient_cartridge", "tech.seed_vial"),
    },
}

# room purpose -> the pool named after it. The purposes the room library
# ships today; dairy and granary arrive with the farming vocabulary.
PURPOSE_FOR_POOL = {"Stable": "stable", "Barn": "barn", "Farmyard": "farmyard",
                    "Dairy": "dairy", "Granary": "granary",
                    "Greenhouse": "greenhouse", "Hydroponics bay": "hydroponics_bay"}
LIVE_PURPOSES = ("stable", "barn", "farmyard", "greenhouse", "hydroponics_bay")


def real_items():
    items = IL.load()
    if not items:
        raise unittest.SkipTest("library/items/ is empty or missing")
    return items


def menu_name(items, iid, band):
    name = IL.name_for(items[iid], band)
    return name[:1].upper() + name[1:]


class TestTheFarmingSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = real_items()

    def test_every_new_item_loads_from_its_file(self):
        for iid, (fname, _bands) in NEW_ITEMS.items():
            self.assertIn(iid, self.items, iid)
            self.assertEqual(self.items[iid]["_file"], fname, iid)

    def test_every_new_item_checks(self):
        self.assertEqual(IL.check(self.items), [])
        for iid in NEW_ITEMS:
            self.assertEqual(IL.check({iid: self.items[iid]}), [], iid)

    def test_bands_and_sources_as_authored(self):
        for iid, (_fname, bands) in NEW_ITEMS.items():
            it = self.items[iid]
            self.assertEqual(IL.expand_bands(it.get("bands")), list(bands), iid)
            self.assertEqual(it.get("sources"), ["authored"], iid)

    def test_tack_is_absent_from_modern_and_scifi(self):
        for band in ("modern", "scifi"):
            on_menu = {e["item"]["id"] for e in LIT.menu(self.items, band, "")}
            for iid in TACK:
                self.assertNotIn(iid, on_menu, (band, iid))
                self.assertIsNone(IL.looks_for_band(self.items[iid], band),
                                  (band, iid))

    def test_looks_per_band_only_where_the_shape_changes(self):
        # one look where the shape holds across bands...
        for iid in ("tool.sickle", "tool.pitchfork", "tool.hoe", "tool.halter",
                    "tool.saddle", "tech.nutrient_cartridge"):
            looks = self.items[iid]["looks"]
            self.assertEqual([l["key"] for l in looks],
                             [looks[0]["key"]], iid)
            self.assertEqual(IL.look_bands(self.items[iid], looks[0]),
                             list(NEW_ITEMS[iid][1]), iid)
        # ...and two where it does not: a hand-tied bundle, then a bale
        bale = self.items["material.straw_bale"]
        self.assertEqual([(l["key"], l["bands"]) for l in bale["looks"]],
                         [("bundle", ["medieval"]),
                          ("bale", ["industrial", "modern"])])

    def test_each_reaches_the_menu_in_each_of_its_bands(self):
        menus = {b: LIT.menu(self.items, b, "") for b in IL.BANDS}
        for iid, (_fname, bands) in NEW_ITEMS.items():
            for band in bands:
                entry = next((e for e in menus[band]
                              if e["item"]["id"] == iid), None)
                self.assertIsNotNone(entry, (band, iid))
                self.assertEqual(entry["name"], menu_name(self.items, iid, band))
                self.assertIn(band, IL.look_bands(self.items[iid], entry["look"]),
                              (band, iid))


class TestTheFarmPools(unittest.TestCase):
    """The pools named after the farm room purposes, expanded the way the
    p2-items reply is: every new item resolves to a template with a library
    link and stays in a pool its purpose binds to."""

    @classmethod
    def setUpClass(cls):
        cls.items = real_items()
        cls.by_band = {}
        for band, table in POOLS.items():
            entries = LIT.menu(cls.items, band, "")
            reply = {"lootPools": {
                pool: {"items": [menu_name(cls.items, iid, band) for iid in iids]}
                for pool, iids in table.items()}}
            log = []
            templates, pools = LIT.expand(reply, entries, band, "farm-items", log)
            cls.by_band[band] = (templates, pools, log)

    def test_nothing_was_dropped_from_the_reply(self):
        for band, (_templates, _pools, log) in self.by_band.items():
            self.assertEqual(log, [], band)

    def test_every_new_item_sits_in_a_farm_purpose_pool(self):
        for band, (templates, pools, _log) in self.by_band.items():
            templated = {t["library"]["item"] for t in templates
                         if t.get("library")}
            pooled = set()
            for iids in POOLS[band].values():
                pooled |= {menu_name(self.items, iid, band) for iid in iids
                           if iid in NEW_ITEMS}
            for iid, (_fname, bands) in NEW_ITEMS.items():
                if band not in bands:
                    continue
                self.assertIn(iid, templated, (band, iid))
                name = menu_name(self.items, iid, band)
                self.assertTrue(any(name in p["items"] for p in pools.values()),
                                (band, iid))

    def test_each_pool_is_bound_by_its_room_purpose(self):
        for band, (_templates, pools, _log) in self.by_band.items():
            names = set(pools)
            for pool, purpose in PURPOSE_FOR_POOL.items():
                if pool in names:
                    self.assertEqual(library_plan.pool_for_purpose(purpose, names),
                                     pool, (band, pool))

    def test_the_purposes_are_the_room_librarys(self):
        lib = library_plan.load()
        for purpose in LIVE_PURPOSES:
            self.assertIn(purpose, lib.vocab["purposes"], purpose)


if __name__ == "__main__":
    unittest.main()
