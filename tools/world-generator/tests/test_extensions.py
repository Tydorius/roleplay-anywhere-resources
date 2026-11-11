"""Extensions: prompt fragments are appended only when the extension is
enabled, and a run without any extension produces exactly the base prompts —
byte for byte, for every phase. ``floors`` needs no game mod and no other
extension."""
import os
import unittest

from worldgen import phases
from worldgen.extensions import expand

PHASES = ("p1-world", "p2-catalogue", "p3-building", "p4-zone", "p5-people")

KW = {
    "p1-world": {"idea": "a mill village"},
    "p2-catalogue": {"setting_line": "SETTING", "zone_lines": "ZONES",
                     "pool_names_line": "POOLS"},
    "p3-building": {"setting_line": "SETTING", "zone_line": "ZONE",
                    "building_line": "BUILDING", "catalogue_lines": "CATALOGUE",
                    "compound_line": "none; this building stands on its own",
                    "units_line": "none; design this building's rooms as one list",
                    "pool_lines": "",
                    "building_name": "The Old Mill"},
    "p4-zone": {"setting_line": "SETTING", "zone_line": "ZONE",
                "building_lines": "BUILDINGS", "catalogue_lines": "CATALOGUE"},
    "p5-people": {"setting_line": "SETTING", "zone_line": "ZONE",
                  "zone_names_line": "ZONE NAMES", "building_lines": "BUILDINGS",
                  "roster_block": "", "quota_line": "the people it needs."},
}

EXT_DIR = os.path.join(os.path.dirname(os.path.abspath(phases.__file__)), "prompts", "ext")


def fragment_names(ext):
    d = os.path.join(EXT_DIR, ext)
    if not os.path.isdir(d):
        return set()
    return {fn[:-4] for fn in os.listdir(d) if fn.endswith(".txt")}


class TestExtensionExpansion(unittest.TestCase):
    def test_expand(self):
        self.assertEqual(expand(["floors"]), {"floors"})
        self.assertEqual(expand(["region-groups"]), {"region-groups"})
        self.assertEqual(expand([]), set())
        self.assertEqual(expand(None), set())
        self.assertEqual(expand(["floors", "floors"]), {"floors"})


class TestRegistry(unittest.TestCase):
    """The registry is what a UI lists as unchecked toggles: every extension
    declares id/title/mods/description and defaults to off, and floors
    needs no game mod."""

    def test_every_extension_defaults_off(self):
        from worldgen.extensions import registry
        exts = registry()
        self.assertTrue(exts)
        for e in exts:
            with self.subTest(e["id"]):
                for key in ("id", "title", "mods", "description",
                            "requires", "withoutMod", "default"):
                    self.assertIn(key, e)
                self.assertIs(e["default"], False)
                self.assertIsInstance(e["mods"], list)
                self.assertTrue(e["title"].strip())
                self.assertTrue(e["description"].strip())

    def test_lights_says_it_degrades_gracefully(self):
        from worldgen.extensions import BY_ID, registry
        self.assertEqual(BY_ID["lights"].mods, ("lights",))
        by_id = {e["id"]: e for e in registry()}
        self.assertIn("look plain", by_id["lights"]["withoutMod"])
        self.assertIn("no game mod needed", by_id["floors"]["withoutMod"])

    def test_floors_needs_no_mod_and_nothing_else(self):
        from worldgen.extensions import BY_ID, IDS
        self.assertIn("floors", IDS)
        self.assertEqual(BY_ID["floors"].requires, ())
        self.assertEqual(BY_ID["floors"].mods, ())
        self.assertEqual(expand(["floors"]), {"floors"})

    def test_expand_notes(self):
        from worldgen.extensions import expand_notes
        full, notes = expand_notes(["floors"])
        self.assertEqual(full, {"floors"})
        self.assertEqual(notes, [])


class TestPromptExtensions(unittest.TestCase):
    def test_no_extension_reproduces_the_base_prompts(self):
        for name in PHASES:
            with self.subTest(name):
                expected = phases._template(name).substitute(
                    rules=phases._rules(), **KW[name])
                self.assertEqual(phases.assemble_prompt(name, (), **KW[name]),
                                 expected)

    def test_known_extensions_do_not_touch_phases_they_do_not_extend(self):
        # every fragment that exists must be for a real phase template, and
        # the phases no enabled extension covers stay byte-identical
        for ext in ("floors", "region-groups", "lights"):
            frags = set()
            for implied in expand([ext]):
                frags |= fragment_names(implied)
            self.assertTrue(frags <= set(PHASES), f"{ext}: unknown phase {frags}")
            for name in PHASES:
                if name in frags:
                    continue
                with self.subTest(f"{ext}/{name}"):
                    expected = phases._template(name).substitute(
                        rules=phases._rules(), **KW[name])
                    self.assertEqual(
                        phases.assemble_prompt(name, (ext,), **KW[name]),
                        expected,
                        f"{ext} must not change the {name} prompt")

    def test_floors_appends_its_fragments(self):
        for name in ("p2-catalogue", "p3-building"):
            with self.subTest(name):
                prompt = phases.assemble_prompt(name, ("floors",), **KW[name])
                base = phases._template(name).substitute(
                    rules=phases._rules(), **KW[name])
                self.assertTrue(prompt.startswith(base))
                self.assertIn("floors extension", prompt)

    def test_the_stair_guidance_is_worded_for_10_floors(self):
        # the retired portals extension's guidance lives in the floors
        # fragments now: stairs are walkable templates the code places, and
        # 1.0 floors have no see-through openings
        for name in ("p2-catalogue", "p3-building"):
            prompt = phases.assemble_prompt(name, ("floors",), **KW[name])
            self.assertNotIn("portals extension", prompt, name)
            self.assertNotIn("portal pad", prompt, name)
            self.assertNotIn("opening", prompt, name)


if __name__ == "__main__":
    unittest.main()
