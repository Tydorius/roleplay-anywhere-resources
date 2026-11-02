"""Every fixture builds through the vendored builder and validator with
zero errors, with and without its extensions — and the no-mods guarantee:
built with no extensions, a scenario carries no arpgMods, no portals, no
storeys and no boundary slab, and the base prompts contain no mod-feature
wording (the plain path needs no game mods)."""
import json
import os
import shutil
import tempfile
import unittest

from worldgen import api

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
REAL_PLANS = ("cyberpunk-glm-plan.json", "medieval-deepseek-plan.json",
              "medieval-glm-plan.json", "modern-glm-plan.json")
# each fixture with its own extensions and with none stripped
BUILDS = {
    "cyberpunk-glm-floors-plan.json": (("floors", "region-groups"), ()),
    "medieval-glm-floors-plan.json": (("floors", "region-groups"), ()),
    "floors-plan.json": (("floors",), ()),
    "village.json": ((),),
    # the compound fixture: floors on and off, region-groups on and off
    "ashvale-compound.plan.json": ((), ("region-groups",), ("floors",),
                                   ("floors", "region-groups")),
}
for _name in REAL_PLANS:
    BUILDS[_name] = ((), ("region-groups",))

SLAB = "The World's Edge"             # the boundary slab object
BOUNDARY = "The Edge of the World"    # the region under it
MOD_WORDS = ("arpgmods", "storey", "stair", "portal", "region group",
             "regiongroup", "upper floor", "z-level", "mezzanine", "lightkind",
             "lightcolor", "lights extension")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


class VendoredBuilds(unittest.TestCase):
    """All builds share one temp folder; each (fixture, extensions) pair is
    laid out and built once and cached for the later assertions."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="worldgen-vendor-")
        cls.built = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _build(self, name, exts):
        key = (name, exts)
        if key not in self.built:
            data = load(name)
            if not exts:
                data.pop("extensions", None)   # a no-extension build ignores the plan's own
            out = os.path.join(self.tmp, f"{len(self.built):02d}-"
                                         f"{os.path.splitext(name)[0]}")
            self.built[key] = api._layout_and_build(data, seed=1, out_dir=out,
                                                    extra_exts=exts)
        return self.built[key]

    def _scenario(self, summary):
        self.assertTrue(summary["ok"], summary)
        self.assertTrue(summary["zip"], summary)
        path = os.path.join(summary["out"], summary["zip"][:-len(".zip")],
                            "scenario.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_every_fixture_builds_with_zero_errors(self):
        for name in sorted(BUILDS):
            for exts in BUILDS[name]:
                with self.subTest(f"{name} ext={','.join(exts) or 'none'}"):
                    summary = self._build(name, exts)
                    self.assertTrue(summary["ok"], summary)
                    self.assertEqual(summary["validator_errors"], 0, summary)
                    self.assertEqual(summary["reachability"], 1.0, summary)
                    if "floors" in exts:
                        from worldgen.extensions import expand
                        self.assertEqual(summary["extensions"],
                                         sorted(expand(exts)),
                                         "floors turns portals on")

    def test_no_extension_builds_carry_no_mod_output(self):
        for name in sorted(BUILDS):
            with self.subTest(name):
                summary = self._build(name, ())
                self.assertEqual(summary["extensions"], [], summary)
                scn = self._scenario(summary)
                self.assertNotIn("arpgMods", scn)
                for region in scn["regions"]:
                    self.assertNotIn("regionGroup", region, region["name"])
                    self.assertNotEqual(region["name"], BOUNDARY, region["name"])
                    self.assertFalse("(upper floor)" in region["name"]
                                     or "(top floor)" in region["name"],
                                     region["name"])
                for template in scn["objectTemplates"]:
                    self.assertNotEqual(template["name"], SLAB, template["name"])
                for entity in scn["entities"]:
                    self.assertFalse(entity["name"].startswith(SLAB),
                                     entity["name"])


class TestBasePromptsMentionNoModFeature(unittest.TestCase):
    def test_base_prompt_files_contain_no_mod_wording(self):
        prompts = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "worldgen", "prompts")
        names = sorted(fn for fn in os.listdir(prompts)
                       if fn.endswith(".txt"))
        self.assertTrue(names)
        for fn in names:
            with open(os.path.join(prompts, fn), "r", encoding="utf-8") as f:
                text = f.read().lower()
            with self.subTest(fn):
                for word in MOD_WORDS:
                    self.assertNotIn(word, text, f"{fn} mentions {word!r}")


if __name__ == "__main__":
    unittest.main()
