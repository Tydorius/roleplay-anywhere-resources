"""The mechanical equipment (library/objects/mechanical.json): the file loads
through the library and the checker stays clean, every object carries a name
and fillable text for each of its bands, and the two containers and the one
two-cell piece are the ones the list says they are."""
import random
import unittest

from worldgen import library as L

IDS = ("utility.coal_furnace", "utility.steam_boiler", "appliance.water_heater",
       "utility.gas_furnace", "bin.coal", "workbench.canning", "shelf.preserving")


def parts_for(obj, band):
    """The object's parts for a band, the way the loader assembles them."""
    parts = dict(obj.get("parts") or {})
    parts.update((obj.get("partsByBand") or {}).get(band) or {})
    return parts


class TestMechanicalEquipment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = L.load(L.LIB_DIR)
        cls.errors, cls.warnings, cls.infos = L.check(cls.lib)

    def bands_of(self, obj):
        return self.lib.bands if obj["bands"] == ["*"] else obj["bands"]

    def test_the_file_loads_and_the_checker_is_clean(self):
        for oid in IDS:
            with self.subTest(object=oid):
                self.assertIn(oid, self.lib.objects)
                self.assertTrue(self.lib.object_files[oid].endswith("mechanical.json"))
        self.assertEqual(self.errors, [], "\n".join(self.errors[:40]))
        self.assertFalse(any(any(oid in w for oid in IDS) for w in self.warnings),
                         self.warnings)

    def test_every_object_is_tagged_mechanical_and_dark(self):
        for oid in IDS:
            with self.subTest(object=oid):
                o = self.lib.objects[oid]
                self.assertIn("mechanical", o["tags"])
                self.assertEqual(o["walkability"], 0)
                self.assertEqual(o["light"], 0)

    def test_every_band_has_a_name(self):
        for oid in IDS:
            o = self.lib.objects[oid]
            for band in self.bands_of(o):
                with self.subTest(object=oid, band=band):
                    noun = (o.get("names") or {}).get(band) or (o.get("names") or {}).get("*")
                    self.assertTrue(noun)

    def test_text_fills_for_every_band_and_tier(self):
        for oid in IDS:
            o = self.lib.objects[oid]
            for band in self.bands_of(o):
                for tier in o["wealth"]:
                    for cond in self.lib.vocab["conditions"]:
                        t = L.fill_text(self.lib, o, band, tier, cond, random.Random(7))
                        for key in ("description", "physical"):
                            with self.subTest(object=oid, band=band, tier=tier,
                                              cond=cond, key=key):
                                self.assertTrue(t[key])
                                self.assertNotIn("{", t[key])
                                self.assertNotIn("}", t[key])
                                self.assertNotIn("  ", t[key])

    def test_the_physical_names_every_part(self):
        for oid in IDS:
            o = self.lib.objects[oid]
            for band in self.bands_of(o):
                t = L.fill_text(self.lib, o, band, "modest", "worn", random.Random(7))
                for part in parts_for(o, band):
                    with self.subTest(object=oid, band=band, part=part):
                        # the material the fill picked for the part is in the brief
                        self.assertIn(t["materials"][part], t["physical"])

    def test_the_coal_bin_and_preserving_shelf_are_the_containers(self):
        for oid in IDS:
            with self.subTest(object=oid):
                o = self.lib.objects[oid]
                self.assertEqual(o["container"], oid in ("bin.coal", "shelf.preserving"))

    def test_the_canning_bench_is_the_only_two_cell(self):
        for oid in IDS:
            with self.subTest(object=oid):
                o = self.lib.objects[oid]
                self.assertIn(o["size"], ([1, 1], [2, 1]))
                self.assertEqual(o["size"] == [2, 1], oid == "workbench.canning")


if __name__ == "__main__":
    unittest.main()
