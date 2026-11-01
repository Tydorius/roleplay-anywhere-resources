"""Mod extensions: prompt fragments are appended only when the extension is
enabled, and a run without any extension produces exactly the base prompts —
byte for byte, for every phase. ``floors`` implies ``portals``."""
import os
import unittest

from worldgen import phases
from worldgen.extensions import expand

PHASES = ("p1-world", "p2-catalogue", "p3-building", "p4-zone", "p5-people")

KW = {
    "p1-world": {"idea": "a mill village"},
    "p2-catalogue": {"setting_line": "SETTING", "zone_lines": "ZONES"},
    "p3-building": {"setting_line": "SETTING", "zone_line": "ZONE",
                    "building_line": "BUILDING", "catalogue_lines": "CATALOGUE",
                    "building_name": "The Old Mill"},
    "p4-zone": {"setting_line": "SETTING", "zone_line": "ZONE",
                "building_lines": "BUILDINGS", "catalogue_lines": "CATALOGUE"},
    "p5-people": {"setting_line": "SETTING", "zone_lines": "ZONES",
                  "building_lines": "BUILDINGS"},
}

EXT_DIR = os.path.join(os.path.dirname(os.path.abspath(phases.__file__)), "prompts", "ext")


def fragment_names(ext):
    d = os.path.join(EXT_DIR, ext)
    if not os.path.isdir(d):
        return set()
    return {fn[:-4] for fn in os.listdir(d) if fn.endswith(".txt")}


class TestExtensionExpansion(unittest.TestCase):
    def test_floors_implies_portals(self):
        self.assertEqual(expand(["floors"]), {"floors", "portals"})
        self.assertEqual(expand(["portals"]), {"portals"})
        self.assertEqual(expand(["region-groups"]), {"region-groups"})
        self.assertEqual(expand([]), set())
        self.assertEqual(expand(None), set())
        self.assertEqual(expand(["floors", "portals", "floors"]),
                         {"floors", "portals"})


class TestRegistry(unittest.TestCase):
    """The registry is what a UI lists as unchecked toggles: every extension
    declares id/title/mods/description and defaults to off, and floors
    records that it needs portals."""

    def test_every_extension_defaults_off(self):
        from worldgen.extensions import registry
        exts = registry()
        self.assertTrue(exts)
        for e in exts:
            with self.subTest(e["id"]):
                for key in ("id", "title", "mods", "description",
                            "requires", "default"):
                    self.assertIn(key, e)
                self.assertIs(e["default"], False)
                self.assertTrue(e["mods"], "an extension needs at least one game mod")
                self.assertTrue(e["title"].strip())
                self.assertTrue(e["description"].strip())

    def test_floors_pulls_in_portals(self):
        from worldgen.extensions import BY_ID, IDS
        self.assertIn("floors", IDS)
        self.assertEqual(BY_ID["floors"].requires, ("portals",))
        self.assertEqual(sorted(BY_ID["floors"].mods), ["floors", "portals"])
        self.assertEqual(expand(["floors"]), {"floors", "portals"})

    def test_expand_notes_says_so(self):
        from worldgen.extensions import expand_notes
        full, notes = expand_notes(["floors"])
        self.assertEqual(full, {"floors", "portals"})
        self.assertEqual(len(notes), 1)
        self.assertIn("portals", notes[0])
        # naming both leaves nothing to say
        _full, notes = expand_notes(["floors", "portals"])
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
        for ext in ("portals", "floors", "region-groups"):
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

    def test_portals_appends_its_fragments(self):
        for name in ("p2-catalogue", "p3-building"):
            with self.subTest(name):
                prompt = phases.assemble_prompt(name, ("portals",), **KW[name])
                base = phases._template(name).substitute(
                    rules=phases._rules(), **KW[name])
                self.assertTrue(prompt.startswith(base))
                self.assertIn("portals extension", prompt)

    def test_floors_pulls_in_the_portals_fragments(self):
        floors_prompt = phases.assemble_prompt("p2-catalogue", ("floors",), **KW["p2-catalogue"])
        portals_prompt = phases.assemble_prompt("p2-catalogue", ("portals",), **KW["p2-catalogue"])
        self.assertEqual(floors_prompt, portals_prompt)


if __name__ == "__main__":
    unittest.main()
