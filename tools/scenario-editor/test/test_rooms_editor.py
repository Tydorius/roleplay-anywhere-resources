"""The Rooms tab's read-only endpoints (rl-04a): present() against the shipped
library and a temp copy without rooms, the meta listing of the three families,
one family's rooms with their checker errors (a hand-broken room in a temp
library reports its error against its own id and none on the others), the
turned room going through fixed_rooms.rotate, the look's per-piece objects in
the modern band (each null or an object id with a shipped sprite file), the
sprite endpoint over HTTP (webp bytes, 400 for ../, slashes and unknown ids)
and that no GET changes any file under the library.
"""
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # tools/scenario-editor
sys.path.insert(0, str(HERE))

import rooms_editor as rmed                            # noqa: E402  (puts the generator on sys.path)
import scenario_editor as se                           # noqa: E402
from worldgen import fixed_rooms                       # noqa: E402

SHIPPED = Path(rmed.LIBRARY_DIR)                       # the real library, before any test swaps it
FAMILIES = ("bedroom", "bedroom.master", "washroom")


def room_ids(family):
    """The room ids a family's file holds, straight from disk."""
    src = SHIPPED / "rooms" / f"{family}.json"
    return [r["id"] for r in json.loads(src.read_text("utf-8"))["rooms"]]


class LibraryTestCase(unittest.TestCase):
    """A temp library (library.json, groups and rooms, never sprites) pointed
    at rooms_editor.LIBRARY_DIR, restored on teardown."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.addCleanup(setattr, rmed, "LIBRARY_DIR", rmed.LIBRARY_DIR)

    def copy_library(self, with_rooms=True):
        shutil.copyfile(SHIPPED / "library.json", self.dir / "library.json")
        shutil.copytree(SHIPPED / "groups", self.dir / "groups")
        if with_rooms:
            shutil.copytree(SHIPPED / "rooms", self.dir / "rooms")
        rmed.LIBRARY_DIR = self.dir
        return self.dir


class TestPresent(LibraryTestCase):

    def test_shipped_library_is_present(self):
        rmed.LIBRARY_DIR = SHIPPED
        self.assertTrue(rmed.present())

    def test_temp_library_without_rooms_is_not_present(self):
        self.copy_library(with_rooms=False)
        self.assertFalse(rmed.present())


class TestMeta(LibraryTestCase):

    def test_three_families_with_counts_and_no_errors(self):
        rmed.LIBRARY_DIR = SHIPPED
        m = rmed.meta()
        self.assertTrue(m["present"])
        self.assertEqual([{"family": f, "rooms": len(room_ids(f)), "errors": 0}
                          for f in FAMILIES],
                         [{"family": f["family"], "rooms": f["rooms"], "errors": f["errors"]}
                          for f in m["families"]])
        self.assertIn("*", m["roles"])                 # the default role colour
        self.assertIn("modern", m["bands"])            # art bands, not size bands
        self.assertTrue(m["clearances"] and m["styles"] and m["tiers"])


class TestFamily(LibraryTestCase):

    def test_every_bedroom_room_comes_back_clean(self):
        rmed.LIBRARY_DIR = SHIPPED
        d = rmed.family("bedroom")
        self.assertEqual(room_ids("bedroom"), [r["id"] for r in d["rooms"]])
        self.assertEqual(d["errors"], [])
        for r in d["rooms"]:
            self.assertEqual([], r["errors"])

    def test_broken_room_carries_its_own_error(self):
        self.copy_library()
        # two pieces on one cell: an overlap the checker names by room id
        src = self.dir / "rooms" / "bedroom.json"
        data = json.loads(src.read_text("utf-8"))
        broken = data["rooms"][0]
        broken["pieces"].append(dict(broken["pieces"][0], role="storage"))
        src.write_text(json.dumps(data), "utf-8")
        d = rmed.family("bedroom")
        by_id = {r["id"]: r for r in d["rooms"]}
        self.assertTrue(by_id[broken["id"]]["errors"], "the broken room reports its error")
        for msg in by_id[broken["id"]]["errors"]:
            self.assertIn(repr(broken["id"]), msg)
        for rid, r in by_id.items():
            if rid != broken["id"]:
                self.assertEqual([], r["errors"])


class TestRoom(LibraryTestCase):

    def test_turn_one_is_fixed_rooms_rotate(self):
        rmed.LIBRARY_DIR = SHIPPED
        stored = json.loads((SHIPPED / "rooms" / "bedroom.json").read_text("utf-8"))["rooms"][0]
        self.assertEqual(fixed_rooms.rotate(stored, 1), rmed.room(stored["id"], 1))


class TestLook(LibraryTestCase):

    def test_modern_look_entry_per_piece_with_sprites(self):
        rmed.LIBRARY_DIR = SHIPPED
        seen_object = False
        for family in FAMILIES:
            room = rmed.family(family)["rooms"][0]
            lk = rmed.look(room["id"], "modern")
            self.assertEqual(len(room["pieces"]), len(lk["look"]))
            self.assertEqual("modern", lk["band"])
            for i, entry in enumerate(lk["look"]):
                if entry is None:
                    continue
                self.assertIsInstance(entry["object"], str)
                self.assertIn(entry["rot"], (0, 1, 2, 3))
                sprite = SHIPPED / "sprites" / "modern" / f"{entry['object']}.webp"
                self.assertTrue(sprite.is_file(), f"piece {i}: no sprite file {sprite}")
                seen_object = True
        self.assertTrue(seen_object, "at least one piece found a modern sprite")


class TestSpriteOverHTTP(unittest.TestCase):
    """The sprite endpoint over the editor's own handler: webp bytes for a
    shipped object, 400 for traversal, slashes and unknown ids, and no GET
    anywhere touching a file under the library."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        store = Path(cls.tmp.name) / "store"
        store.mkdir()
        se.Handler.store = store
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), se.Handler)
        cls.addClassCleanup(cls.srv.shutdown)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        room = rmed.family("bedroom")["rooms"][0]
        cls.room_id = room["id"]
        cls.object_id = next(e["object"] for e in rmed.look(room["id"], "modern")["look"] if e)

    @classmethod
    def get(cls, path):
        try:
            with urllib.request.urlopen(cls.base + path, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    @staticmethod
    def query(**kw):
        return urllib.parse.urlencode(kw)

    def test_sprite_webp_and_bad_ids(self):
        code, body = self.get("/api/rooms/sprite?" + self.query(band="modern", object=self.object_id))
        self.assertEqual(200, code)
        self.assertEqual(b"WEBP", body[8:12])
        for bad in ("../x", "a/b", "nope.nope"):
            code, body = self.get("/api/rooms/sprite?" + self.query(band="modern", object=bad))
            self.assertEqual(400, code, bad)

    def test_no_get_writes_anything_under_the_library(self):
        before = {str(p): p.stat().st_mtime_ns
                  for p in SHIPPED.rglob("*") if p.is_file()}

        def hit(path):
            code, _ = self.get(path)
            self.assertEqual(200, code, path)

        hit("/api/rooms/meta")
        for family in FAMILIES:
            hit("/api/rooms/family?" + self.query(family=family))
            hit("/api/rooms/groups?" + self.query(family=family))
            room = rmed.family(family)["rooms"][0]
            for turn in range(4):
                for mirror in (0, 1):
                    hit("/api/rooms/room?" + self.query(id=room["id"], turn=turn, mirror=mirror))
                    hit("/api/rooms/look?" + self.query(id=room["id"], band="modern",
                                                        turn=turn, mirror=mirror))
        hit("/api/rooms/sprite?" + self.query(band="modern", object=self.object_id))
        after = {str(p): p.stat().st_mtime_ns
                 for p in SHIPPED.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
