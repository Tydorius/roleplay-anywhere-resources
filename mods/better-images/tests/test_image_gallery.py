"""Image Gallery: which things of a 1.0 scenario get an image card.

    python -m unittest discover -s mods/better-images/tests
"""
import json, sys, tempfile, threading, unittest, urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

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


# ---------------------------------------------------------------- variations: N images per job
def canned_history(pid, n, tag=None):
    """A finished history entry with n saved images (and a temp preview, to be ignored)."""
    imgs = [{"filename": f"anywhere-rpg-portrait_{k:05}_.png", "subfolder": "", "type": "output"} for k in range(n)]
    extra = {"client_id": ig.CLIENT_PREFIX + "test", "create_time": 4102444800000}
    if tag:
        extra["anywhere_rpg_gallery"] = tag
    return {pid: {"prompt": [0, pid, {}, extra, []],
                  "outputs": {"7": {"images": imgs},
                              "9": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]}},
                  "status": {"status_str": "success", "completed": True, "messages": [
                      ["execution_start", {"timestamp": 1000}], ["execution_success", {"timestamp": 5000}]]}}}


class FakeComfy:
    """Stands in for ig.comfy: canned history; /view returns the file name as the image bytes."""
    def __init__(self, hist):
        self.hist, self.calls = hist, []

    def __call__(self, url, path, body=None, timeout=60):
        self.calls.append(path)
        if path.startswith("/view?"):
            return parse_qs(path[len("/view?"):])["filename"][0].encode()
        if path.startswith("/history/"):
            pid = path.split("/")[2]
            return json.dumps({pid: self.hist[pid]} if pid in self.hist else {}).encode()
        if path.startswith("/history"):
            return json.dumps(self.hist).encode()
        raise AssertionError("unexpected ComfyUI call " + path)

    def views(self):
        return [c for c in self.calls if c.startswith("/view")]


def running_job(pid):
    return {"pid": pid, "url": "http://comfy", "source": "work/x", "id": "npc_alys", "kind": "portrait",
            "state": "running", "position": None, "submitted": 0, "started": 1, "finished": None, "error": None,
            "meta": {"seed": 7}, "imgs": [], "pngs": {}, "misses": 0}


class Variations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(ig, "STATE", root / "state.json"),
                        mock.patch.object(ig, "WORK", root / "work"),
                        mock.patch.dict(ig.JOBS, clear=True)]
        for p in self.patches:
            p.start()
        self.ws = root / "work" / "x"
        (self.ws / "media").mkdir(parents=True)
        (self.ws / "scenario.json").write_text(json.dumps(SCENARIO), "utf-8")
        self.src = {"id": "work/x", "dir": self.ws, "data": self.ws / "scenario.json"}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def finished(self, n):
        fake = FakeComfy(canned_history("P", n))
        j = running_job("P")
        with mock.patch.object(ig, "comfy", fake):
            ig.finish(j)
        return j, fake

    def test_four_outputs_give_four_candidates_fetched_lazily(self):
        j, fake = self.finished(4)
        self.assertEqual((j["state"], ig.public(j)["count"]), ("done", 4))
        self.assertEqual(fake.views(), [])  # nothing downloaded until the page asks

    def test_result_png_fetches_the_chosen_variation_once(self):
        j, fake = self.finished(4)
        with mock.patch.object(ig, "comfy", fake):
            self.assertEqual(ig.result_png(j, 2), b"anywhere-rpg-portrait_00002_.png")
            ig.result_png(j, 2)
            self.assertEqual(len(fake.views()), 1)
            with self.assertRaises(LookupError):
                ig.result_png(j, 4)

    def test_one_image_is_as_before(self):
        j, fake = self.finished(1)
        self.assertEqual(ig.public(j)["count"], 1)
        with mock.patch.object(ig, "comfy", fake):
            self.assertEqual(ig.result_png(j), b"anywhere-rpg-portrait_00000_.png")

    def test_adopt_keeps_every_variation_and_skips_reviewed(self):
        tag = {"source": "work/x", "id": "npc_alys", "kind": "portrait", "meta": {"seed": 7}}
        with mock.patch.object(ig, "comfy", FakeComfy(canned_history("A", 4, tag))):
            self.assertEqual(ig.adopt(self.src, "http://comfy"), 1)
        self.assertEqual(len(ig.JOBS["A"]["imgs"]), 4)
        self.assertEqual(ig.public(ig.JOBS["A"])["count"], 4)
        ig.mark_reviewed("A")
        ig.JOBS.clear()
        with mock.patch.object(ig, "comfy", FakeComfy(canned_history("A", 4, tag))):
            self.assertEqual(ig.adopt(self.src, "http://comfy"), 0)

    def test_keep_index_two_writes_that_image(self):
        j, fake = self.finished(4)
        ig.JOBS["P"] = j
        ig.Handler.store = Path(self.tmp.name) / "store"
        srv = ig.ThreadingHTTPServer(("127.0.0.1", 0), ig.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        post = lambda path, data=b"": urllib.request.urlopen(urllib.request.Request(base + path, data=data, method="POST")).read()
        try:
            with mock.patch.object(ig, "comfy", fake):
                picked = urllib.request.urlopen(base + "/api/result?pid=P&i=2").read()
                first = urllib.request.urlopen(base + "/api/result?pid=P").read()
            self.assertEqual(picked, b"anywhere-rpg-portrait_00002_.png")
            self.assertEqual(first, b"anywhere-rpg-portrait_00000_.png")
            webp = b"RIFF\x00\x00\x00\x00WEBP" + picked  # what the page makes of the picked PNG
            post("/api/save?source=work/x&id=npc_alys&kind=portrait", webp)
            post("/api/forget?pid=P")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual((self.ws / "media" / "npc_alys" / "npc_alys-portrait.webp").read_bytes(), webp)
        self.assertNotIn("P", ig.JOBS)
        self.assertEqual(ig.load_state(), {"P"})


class BatchSize(unittest.TestCase):
    def build(self, family, kind, **extra):
        req = {"kind": kind, "family": family, "desc": "An oak chest", "aspect": 1, **extra}
        files = {r: f"{r}.safetensors" for r in ig.sim.FAMILIES[family]["files"]}
        with mock.patch.object(ig, "object_info", return_value={}), \
                mock.patch.object(ig, "resolve_files", return_value=files), \
                mock.patch.object(ig.random, "randrange", return_value=42):
            return ig.build(req, {"remover": "rembg"}, "http://comfy")

    def test_batch_size_goes_on_the_empty_latent_only(self):
        for family, kind in (("sdxl", "portrait"), ("flux2-klein", "item")):
            wf, meta = self.build(family, kind, variations=4)
            sized = [n for n in wf.values() if "batch_size" in n["inputs"]]
            self.assertEqual([n["inputs"]["batch_size"] for n in sized], [4], family)
            self.assertIn("width=WIDTH", sized[0]["_meta"]["title"])
            self.assertEqual(meta["variations"], [{"seed": 42, "batch_index": k} for k in range(4)])
            self.assertEqual(meta["seed"], 42)
            if kind == "item":  # the background remover takes the whole batch
                self.assertEqual(wf["8"]["inputs"]["images"], ["6", 0])

    def test_one_variation_is_todays_workflow(self):
        for family, kind in (("sdxl", "portrait"), ("flux2-klein", "item")):
            wf, meta = self.build(family, kind)
            self.assertEqual(self.build(family, kind, variations=1), (wf, meta))
            self.assertEqual([n["inputs"]["batch_size"] for n in wf.values() if "batch_size" in n["inputs"]], [1])
            self.assertEqual(meta["variations"], [{"seed": 42, "batch_index": 0}])

    def test_variations_are_clamped(self):
        self.assertEqual([ig.variations(v) for v in (0, 3, 9, "x", None)], [1, 3, 8, 1, 1])


if __name__ == "__main__":
    unittest.main()
