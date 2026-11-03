"""The lights extension: the catalogue's ``lightKind`` / ``lightColor`` reach
the built scenario as ``arpgMods.lights`` (keyed by template name) only when
the extension is on; a kind with no strength gets its kind's usual one; bad
values are dropped, never retried. ``light`` itself is plain game data and
ships with or without the extension."""
import json
import os
import shutil
import tempfile
import unittest

from worldgen import api, phases
from worldgen.extensions import lights
from worldgen.model import ObjectTemplate

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def with_kinds(data):
    """The fixture as the catalogue phase would write it with lights on."""
    for t in data["templates"]:
        if t["name"] == "Clay hearth":
            t["lightKind"] = "fire"
        elif t["name"] == "Stone forge":
            t.update(lightKind="fire", lightColor="#FF5522")
        elif t["name"] == "Oil lamp":
            t["lightKind"] = "lantern"      # no "light": gets the lantern's 0.5
    return data


class FakeWorld:
    def __init__(self, templates):
        self.templates = {t.name: t for t in templates}


class TestLightsUnit(unittest.TestCase):
    def test_light_for_keeps_the_catalogue_value_or_uses_the_kind(self):
        self.assertEqual(lights.light_for(ObjectTemplate("A", extras={"light": 0.9, "lightKind": "candle"})), 0.9)
        self.assertEqual(lights.light_for(ObjectTemplate("B", extras={"lightKind": "candle"})), 0.2)
        self.assertEqual(lights.light_for(ObjectTemplate("C", extras={"light": 0, "lightKind": "fire"})), 0.8)
        self.assertIsNone(lights.light_for(ObjectTemplate("D")))

    def test_every_kind_has_a_strength(self):
        self.assertEqual(set(lights.KINDS), set(lights.KIND_LIGHT))

    def test_arpg_mods_lists_kinds_and_colours_by_name(self):
        world = FakeWorld([
            ObjectTemplate("Hearth", extras={"light": 0.8, "lightKind": "fire"}),
            ObjectTemplate("Witch lamp", extras={"lightKind": "lantern", "lightColor": "#33FF66"}),
            ObjectTemplate("Table"),
            ObjectTemplate("Torch", extras={"light": 0.6}),   # no kind: the mod classifies it
        ])
        self.assertEqual(lights.arpg_mods(world), {"lights": {"templates": {
            "Hearth": "fire", "Witch lamp": {"kind": "lantern", "color": "#33ff66"}}}})
        self.assertEqual(lights.arpg_mods(FakeWorld([ObjectTemplate("Table")])), {})

    def test_sanitize_drops_bad_light_fields(self):
        log = []
        d = {"templates": [
            {"name": "A", "size": [1, 1], "walkability": 0, "light": 3, "lightKind": " Fire "},
            {"name": "B", "size": [1, 1], "walkability": 0, "light": "bright", "lightKind": "laser",
             "lightColor": "green"},
            {"name": "C", "size": [1, 1], "walkability": 0, "light": 0.4, "lightColor": "#00ff00"},
        ]}
        a, b, c = phases.sanitize_p2(d, log)["templates"]
        self.assertEqual((a["light"], a["lightKind"]), (1, "fire"))
        for k in ("light", "lightKind", "lightColor"):
            self.assertNotIn(k, b)
        self.assertEqual((c["light"], c["lightColor"]), (0.4, "#00ff00"))
        self.assertEqual(len(log), 4)


class TestLightsBuilds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-lights-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, name, exts):
        data = with_kinds(load(name))
        data.pop("extensions", None)
        out = os.path.join(self.tmp, f"{os.path.splitext(name)[0]}-{'-'.join(exts) or 'none'}")
        summary = api._layout_and_build(data, seed=1, out_dir=out, extra_exts=exts)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["validator_errors"], 0, summary)
        self.assertEqual(summary["reachability"], 1.0, summary)
        path = os.path.join(summary["out"], summary["zip"][:-len(".zip")], "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            return summary, json.load(f)

    def test_lights_writes_arpg_mods_and_lights_every_kind(self):
        summary, scn = self.build("village.json", ("lights",))
        self.assertEqual(summary["extensions"], ["lights"])
        self.assertEqual(scn["arpgMods"], {"lights": {"templates": {
            "Clay hearth": "fire", "Stone forge": {"kind": "fire", "color": "#ff5522"}}}})
        light = {t["name"]: t.get("light") for t in scn["objectTemplates"]}
        self.assertEqual((light["Clay hearth"], light["Stone forge"]), (0.6, 0.5))

    def test_without_the_extension_kinds_are_ignored_but_light_ships(self):
        _summary, scn = self.build("village.json", ())
        self.assertNotIn("arpgMods", scn)
        light = {t["name"]: t.get("light") for t in scn["objectTemplates"]}
        self.assertEqual((light["Clay hearth"], light["Stone forge"]), (0.6, 0.5))
        for t in scn["objectTemplates"]:
            self.assertNotIn("lightKind", t)
            self.assertNotIn("lightColor", t)

    def test_lights_sits_beside_floors(self):
        _summary, scn = self.build("floors-plan.json", ("floors", "lights"))
        mods = scn["arpgMods"]
        self.assertTrue(mods["floors"] and mods["portals"])
        self.assertEqual(mods["lights"], {"templates": {"Clay hearth": "fire", "Oil lamp": "lantern"}})
        lamp = next(t for t in scn["objectTemplates"] if t["name"] == "Oil lamp")
        self.assertEqual(lamp["light"], 0.5)


if __name__ == "__main__":
    unittest.main()
