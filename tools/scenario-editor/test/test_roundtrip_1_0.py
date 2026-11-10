"""Round trip of Anywhere RPG 1.0 scenarios through the editor's own open -> save -> download code (the Image
Gallery's zip import and export and scenario_editor.save_scenario): every key comes back untouched, and the media
folders under htpl_ ids come back too. Uses the three presets that ship with 1.0, with every 1.0 key the presets
lack added on top, so it skips when the 1.0 build snapshot isn't on this machine.

The vendored copy of scenario_checks.py in the world generator must match this one exactly; that is checked here
as well as in the generator's own tests.
"""
import copy
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scenario_editor  # noqa: E402
import scenario_checks  # noqa: E402

ig = scenario_editor.ig
PRESETS = Path(r"E:\Misc Projects\Anywhere RPG builds\1.0-build26557354\resources\presets")
NAMES = ["thornbury", "college-of-wizardry", "uc-berkeley"]
VENDORED = HERE.parent.parent / "world-generator" / "worldgen" / "vendor" / "scenario_checks.py"


def with_every_1_0_key(scn, as_export=True):
    """The preset plus the 1.0 keys it doesn't use: a floor with portal stairs, sided openings, door kinds and a
    lock, a liquid, a natural shape, a vehicle, npcTemplates with homes, and an NPC's home region."""
    scn = copy.deepcopy(scn)
    gw, gh = scn["gridSize"]
    building = next(r for r in scn["regions"] if r.get("wall") and r.get("openings"))
    o = building["openings"][0]
    building["openings"][0] = [o[0], o[1], scenario_checks.opening_sides(building, o)[0]]
    building.update(door="gate", doorColor="#8a5a2b", takingIsTheft=True)
    scn["regions"].append({"id": "rgn_rt_loft", "name": "Round-trip Loft", "wall": building["wall"], "openings": [],
                           "position": [gw + 24, 0], "size": [10, 8], "pocket": {"anchor": building["id"], "level": 1}})
    scn["regions"].append({"id": "rgn_rt_pond", "name": "Round-trip Pond", "openings": [], "position": [gw + 25, 1],
                           "size": [5, 5], "shape": "organic", "surface": "deep water"})
    tpl = {"id": "otpl_rt_stair", "name": "Round-trip stair", "size": [1, 1], "walkability": 1}
    cart = {"id": "otpl_rt_cart", "name": "Round-trip cart", "size": [2, 2], "walkability": 0, "vehicle": "drive",
            "sheet": "dune-buggy", "takingIsTheft": True}
    door = {"id": "otpl_rt_door", "name": "Gate", "size": [1, 0], "walkability": 1, "door": "gate", "heightM": 2.1}
    scn["objectTemplates"] += [tpl, cart, door]
    lock = {"id": "se_rt", "def": {"desc": "Locked", "type": "constant", "mechanics": [{"type": "locked"}]}}
    scn["entities"] += [
        {"id": "obj_rt_up", "type": "object", "name": "Stair up", "templateId": tpl["id"], "pos": [o[0], o[1]],
         "size": [1, 1], "hp": 50, "maxHp": 50, "inventory": [], "statusEffects": [], "portal": {"to": "obj_rt_down"}},
        {"id": "obj_rt_down", "type": "object", "name": "Stair down", "templateId": tpl["id"], "pos": [gw + 32, 6],
         "size": [1, 1], "hp": 50, "maxHp": 50, "inventory": [], "statusEffects": [], "portal": {"to": "obj_rt_up"}},
        {"id": "obj_rt_gate", "type": "object", "name": "Gate 1", "templateId": door["id"], "pos": [o[0], o[1]],
         "size": [1, 0], "rot": None, "hp": 50, "maxHp": 50, "inventory": [], "statusEffects": [lock]},
    ]
    scn["itemTemplates"].append({"id": "itpl_rt_key", "name": "Gate key", "type": "misc", "quality": "common",
                                 "opens": building["id"]})
    if as_export:  # what a 1.0 export writes: npcTemplates with homes instead of hostileNpcTemplates
        scn["npcTemplates"] = [dict({k: v for k, v in t.items() if k not in ("regionId", "count")}, stance="hostile",
                                    homes=[{"regionId": t["regionId"], "count": t.get("count", 0)}])
                               for t in scn.pop("hostileNpcTemplates", [])]
        scn["npcTemplates"].append({"id": "ntpl_rt_sheep", "name": "Sheep", "animationId": "sheep",
                                    "stance": "skittish", "homes": [{"regionId": building["id"], "count": 3}]})
    npc = next(e for e in scn["entities"] if e["type"] == "npc")
    npc["npcHome"] = building["id"]
    npc["stance"] = "skittish"
    for t in scn.get("hostileNpcTemplates", []):
        t.setdefault("physicalDescription", "round trip")
    return scn


def zip_of(folder, scn):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("scenario.json", json.dumps(scn, ensure_ascii=False))
        for f in sorted((folder / "media").rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(folder).as_posix())
    return buf.getvalue()


@unittest.skipUnless(PRESETS.is_dir(), "the Anywhere RPG 1.0 build snapshot isn't on this machine")
class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = ig.WORK, ig.BACKUPS
        ig.WORK, ig.BACKUPS = Path(self.tmp.name) / "work", Path(self.tmp.name) / "backups"

    def tearDown(self):
        ig.WORK, ig.BACKUPS = self.saved
        self.tmp.cleanup()

    def test_open_save_download_keeps_every_key_and_image(self):
        for name in NAMES:
            with self.subTest(name):
                folder = PRESETS / name
                scn = with_every_1_0_key(json.loads((folder / "scenario.json").read_text("utf-8")), name != "thornbury")
                sid = ig.import_zip(zip_of(folder, scn))
                src = {"id": sid, "dir": ig.WORK / sid.split("/", 1)[1]}
                src["data"] = src["dir"] / "scenario.json"
                opened = json.loads(src["data"].read_text("utf-8"))
                scenario_editor.save_scenario(src, json.dumps(opened).encode("utf-8"))   # what the page posts
                out = zipfile.ZipFile(io.BytesIO(ig.export_zip(src)))
                self.assertEqual(json.loads(out.read("scenario.json")), scn)
                want = {f.relative_to(folder).as_posix() for f in (folder / "media").rglob("*") if f.is_file()}
                got = {n for n in out.namelist() if n.startswith("media/")}
                self.assertEqual(got, want)
                self.assertTrue(any(n.startswith("media/htpl_") for n in got))
                problems = scenario_checks.check(scn, got)
                self.assertEqual([p["msg"] for p in problems if p["level"] == "error"], [])
                self.assertFalse([p for p in problems if "Round-trip" in p["msg"] and p["level"] != "info"],
                                 [p["msg"] for p in problems if "Round-trip" in p["msg"]])


class Vendored(unittest.TestCase):
    def test_the_world_generators_copy_matches(self):
        if not VENDORED.is_file():
            self.skipTest("no world generator beside the editor")
        read = lambda p: p.read_text("utf-8").replace("\r\n", "\n")  # noqa: E731
        self.assertEqual(read(VENDORED), read(HERE.parent / "scenario_checks.py"),
                         "copy tools/scenario-editor/scenario_checks.py to worldgen/vendor/ (see its README)")


if __name__ == "__main__":
    unittest.main()
