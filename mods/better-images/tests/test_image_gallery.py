"""Image Gallery: which things of a 1.0 scenario get an image card.

    python -m unittest discover -s mods/better-images/tests
"""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import image_gallery as ig  # noqa: E402

SCENARIO = {
    "name": "Test",
    "imageSettings": {"promptFormat": "${prompt}, watercolor", "models": {}},
    "objectTemplates": [
        {"id": "otpl_bed", "name": "Bed", "physicalDescription": "A plain bed", "size": [1, 2]},
        {"id": "otpl_door", "name": "Oak door", "physicalDescription": "An oak door", "door": "wood"},
        {"id": "otpl_bike", "name": "Bicycle", "physicalDescription": "A red bicycle", "size": [1, 1],
         "vehicle": "ride", "sheet": "bicycle"},
    ],
    # 0.18 hostile templates (htpl_), migrated by the game, and 1.0 NPC templates (ntpl_)
    "hostileNpcTemplates": [
        {"id": "htpl_wolf", "name": "Dire wolf", "physicalDescription": "Gaunt grey wolf", "animationId": "wolf"},
    ],
    "npcTemplates": [
        {"id": "ntpl_guard", "name": "Guard", "gender": "male", "physicalDescription": "Mailed town guard"},
    ],
    "entities": [
        {"id": "npc_alys", "type": "npc", "name": "Alys", "gender": "female", "physicalDescription": "Innkeeper"},
        {"id": "npc_wolf1", "type": "npc", "name": "Dire wolf 1", "templateId": "htpl_wolf"},
        {"id": "npc_guard1", "type": "npc", "name": "Guard 1", "templateId": "ntpl_guard"},
        {"id": "obj_bed1", "type": "object", "name": "Bed", "templateId": "otpl_bed"},
    ],
}


class ListItems(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "scenario.json").write_text(json.dumps(SCENARIO), "utf-8")
        for iid, kind in [("htpl_wolf", "portrait"), ("otpl_bed", "sprite")]:
            (self.dir / "media" / iid).mkdir(parents=True)
            (self.dir / "media" / iid / f"{iid}-{kind}.webp").write_bytes(b"RIFF")

    def tearDown(self):
        self.tmp.cleanup()

    def items(self):
        r = ig.list_items({"id": "work/x", "dir": self.dir, "data": self.dir / "scenario.json"})
        return {i["id"]: i for i in r["items"]}, r["promptFormat"]

    def test_npc_templates_are_portraits_with_descriptions(self):
        items, _ = self.items()
        wolf, guard = items["htpl_wolf"], items["ntpl_guard"]
        self.assertEqual((wolf["kind"], wolf["name"], wolf["known"]), ("portrait", "Dire wolf", True))
        self.assertEqual(wolf["file"], "htpl_wolf-portrait.webp")
        self.assertEqual(wolf["desc"], "Gaunt grey wolf")       # a creature: no name or gender
        self.assertEqual(wolf["subject"], "creature")
        self.assertEqual(guard["desc"], "Guard (male): Mailed town guard")  # the game's own wording
        self.assertIsNone(guard["file"])

    def test_npcs_spawned_from_a_template_use_its_portrait(self):
        items, _ = self.items()
        self.assertIn("npc_alys", items)
        self.assertNotIn("npc_wolf1", items)
        self.assertNotIn("npc_guard1", items)

    def test_doors_have_no_sprite_and_sheet_vehicles_say_so(self):
        items, _ = self.items()
        self.assertNotIn("otpl_door", items)
        self.assertIsNone(items["otpl_bed"]["note"])
        self.assertIn("vehicle sheet", items["otpl_bike"]["note"])
        self.assertEqual(items["otpl_bed"]["aspect"], round(1.5 / 2.5, 4))

    def test_prompt_format_is_passed_on(self):
        _, fmt = self.items()
        self.assertEqual(fmt, "${prompt}, watercolor")


class PromptFormat(unittest.TestCase):
    """1.0 wraps the description that fills ${DESC} (function i0e in its bundle), for every type."""

    def test_placeholder_and_prefix(self):
        self.assertEqual(ig.format_desc("a bed", "${prompt}, watercolor"), "a bed, watercolor")
        self.assertEqual(ig.format_desc("a bed", "  pixel art "), "pixel art a bed")
        self.assertEqual(ig.format_desc("a bed", ""), "a bed")
        self.assertEqual(ig.format_desc("a bed", None), "a bed")


if __name__ == "__main__":
    unittest.main()
