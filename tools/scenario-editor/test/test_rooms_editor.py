"""The Rooms tab's endpoints: present() against the shipped library and a
temp copy without rooms, the meta listing of the three families, one family's
rooms with their checker errors (a hand-broken room in a temp library reports
its error against its own id and none on the others), the turned room going
through fixed_rooms.rotate, the look's per-piece objects in the modern band
(each null or an object id with a shipped sprite file), the sprite endpoint
over HTTP (webp bytes, 400 for ../, slashes and unknown ids) and that no GET
changes any file under the library. The hand-work endpoints (rl-04b): a valid
edit writes and reloads clean, a broken room is refused with the file
untouched, a stale file hash is refused, an unchanged save writes identical
bytes, the previous file lands in .backup, regenerate-one returns
checker-passing candidates equal to no shipped room, and a family
regeneration writes nothing until it is applied.
"""
import json
import shutil
import sys
import tempfile
import threading
import time
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
        shutil.copytree(SHIPPED / "layouts", self.dir / "layouts")
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


class TestSave(LibraryTestCase):
    """POST /api/rooms/save against a temp copy of the library: the checker
    gates every write, the stale-file guard refuses a file that changed under
    the page, an unchanged save is byte-identical and the previous file is
    backed up."""

    def path(self, family="bedroom"):
        return self.dir / "rooms" / f"{family}.json"

    def test_a_valid_edit_writes_and_reloads_clean(self):
        self.copy_library()
        d = rmed.family("bedroom")
        d["rooms"][0]["description"] = "Described by hand."
        d["rooms"][0]["edited"] = ["description"]
        out = rmed.save({"family": "bedroom", "rooms": d["rooms"],
                         "hash": d["hash"]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["rooms"], len(d["rooms"]))
        again = rmed.family("bedroom")
        self.assertEqual(again["errors"], [])
        for r in again["rooms"]:
            self.assertEqual([], r["errors"])
        self.assertEqual(again["hash"], out["hash"])
        by_id = {r["id"]: r for r in again["rooms"]}
        self.assertEqual(by_id[d["rooms"][0]["id"]]["description"],
                         "Described by hand.")
        self.assertEqual(by_id[d["rooms"][0]["id"]]["edited"],
                         ["description"])

    def test_a_broken_room_is_refused_and_the_file_stands(self):
        self.copy_library()
        d = rmed.family("bedroom")
        d["rooms"][0]["pieces"].append(dict(d["rooms"][0]["pieces"][0],
                                            role="storage"))   # two on one cell
        before = self.path().read_bytes()
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.save({"family": "bedroom", "rooms": d["rooms"],
                       "hash": d["hash"]})
        self.assertTrue(caught.exception.errors, "the refusal says why")
        self.assertEqual(before, self.path().read_bytes())
        self.assertFalse((self.dir / "rooms" / ".backup").exists(),
                         "a refused save backs nothing up")

    def test_a_stale_file_hash_is_refused(self):
        self.copy_library()
        d = rmed.family("bedroom")
        on_disk = json.loads(self.path().read_text("utf-8"))
        on_disk["rooms"][0]["description"] = "changed on disk"
        self.path().write_text(json.dumps(on_disk), "utf-8")
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.save({"family": "bedroom", "rooms": d["rooms"],
                       "hash": d["hash"]})
        self.assertTrue(any("changed on disk" in e
                            for e in caught.exception.errors))

    def test_an_unchanged_save_writes_identical_bytes(self):
        self.copy_library()
        d = rmed.family("bedroom")
        before = self.path().read_bytes()
        out = rmed.save({"family": "bedroom", "rooms": d["rooms"],
                         "hash": d["hash"]})
        self.assertTrue(out["ok"])
        self.assertEqual(before, self.path().read_bytes())

    def test_the_previous_file_lands_in_the_backup(self):
        self.copy_library()
        d = rmed.family("bedroom")
        before = self.path().read_bytes()
        d["rooms"][0]["description"] = "Described by hand."
        rmed.save({"family": "bedroom", "rooms": d["rooms"], "hash": d["hash"]})
        backup = self.dir / "rooms" / ".backup" / "bedroom.json"
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_bytes(), before)


class TestRegenerateOne(LibraryTestCase):

    def test_candidates_check_clean_and_duplicate_nothing(self):
        self.copy_library()
        room = rmed.family("bedroom")["rooms"][0]
        out = rmed.regenerate(room["id"])
        self.assertEqual(out["room"], room["id"])
        self.assertTrue(out["candidates"], "at least one candidate")
        self.assertEqual([], rmed.check_rooms({"rooms": out["candidates"]})["errors"])
        gen = rmed._generate_rooms_mod()
        existing = {gen.canonical(r) for r in fixed_rooms.load(rmed._rooms_dir())
                    if r.get("family") == "bedroom"}
        seen = set()
        for cand in out["candidates"]:
            with self.subTest(candidate=cand["id"]):
                self.assertEqual(cand["sizeBand"], room["sizeBand"])
                key = gen.canonical(cand)
                self.assertNotIn(key, existing, "equals a shipped room")
                self.assertNotIn(key, seen, "another candidate's equal")
                seen.add(key)


class TestRegenerateFamily(LibraryTestCase):

    def test_nothing_is_written_until_the_job_is_applied(self):
        self.copy_library()
        before = self.path().read_bytes()
        j = rmed.start_regen_family("bedroom")
        self.assertEqual(j["status"], "running")
        for _ in range(600):                      # the page polls; so does the test
            j = rmed.job()
            if j["status"] != "running":
                break
            time.sleep(0.5)
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(j["family"], "bedroom")
        self.assertEqual(before, self.path().read_bytes(),
                         "the finished job wrote nothing by itself")
        out = rmed.apply_regen()
        self.assertTrue(out["ok"])
        self.assertEqual(out["rooms"],
                         len(json.loads(self.path().read_text("utf-8"))["rooms"]))
        self.assertEqual(before, self.path().read_bytes(),
                         "an unmodified family regenerates to the same bytes")
        self.assertIsNone(rmed.job(), "applying clears the job")

    def path(self, family="bedroom"):
        return self.dir / "rooms" / f"{family}.json"


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


def _room_group(family="bedroom"):
    """A group id one of the family's stored rooms is composed of."""
    for r in rmed.family(family)["rooms"]:
        for p in r["pieces"]:
            if p.get("group"):
                return p["group"], r["id"]
    raise AssertionError(f"no room of {family!r} names a group")


class TestGroupsListing(LibraryTestCase):
    """The add-group dialog's data: every pool group is in groups() (the
    rl-04a bug — pool entries had no group), and allgroups() lists the whole
    library, each group with the file it lives in."""

    def test_groups_returns_every_pool_group(self):
        rmed.LIBRARY_DIR = SHIPPED
        for family in FAMILIES:
            with self.subTest(family=family):
                d = rmed.groups(family)
                for e in d["pool"]:
                    self.assertIn(e["group"], d["groups"])

    def test_allgroups_lists_every_group_with_its_file(self):
        rmed.LIBRARY_DIR = SHIPPED
        d = rmed.allgroups()
        listed = {g["id"] for g in d["groups"]}
        loaded = rmed.room_groups.load(str(SHIPPED / "groups"))["groups"]
        self.assertEqual(sorted(g for g in loaded
                                if "_load_error" not in loaded[g]),
                         sorted(listed))
        for g in d["groups"]:
            with self.subTest(gid=g["id"]):
                self.assertTrue(g["file"].endswith(".json"))
                self.assertTrue((SHIPPED / "groups" / g["file"]).is_file())


class TestGroupSave(LibraryTestCase):
    """The group editor's endpoint: a valid edit writes only its own file
    (the previous copy in .backup) and reports the stored rooms using the
    group without touching them; a stale hash, a broken group and another
    file's id are all refused with the file untouched; a new group lands
    in the file the request names, pool entries and all."""

    def path(self, file):
        return self.dir / "groups" / file

    def snapshot(self):
        return {p.name: p.read_bytes()
                for p in (self.dir / "groups").glob("*.json")}

    def test_a_valid_edit_writes_only_that_file_and_backs_it_up(self):
        self.copy_library()
        gid, room_id = _room_group()
        g = rmed.group(gid)
        before = self.snapshot()
        rooms_before = {p.name: p.read_bytes()
                        for p in (self.dir / "rooms").glob("*.json")}
        g["pieces"][0] = dict(g["pieces"][0], optional=not g["pieces"][0].get("optional"))
        out = rmed.save_group({"group": g, "hash": g["hash"]})
        self.assertTrue(out["ok"], out)
        self.assertEqual(g["file"], out["file"])
        after = self.snapshot()
        self.assertEqual(sorted(k for k in after if after[k] != before[k]),
                         [g["file"]], "only the group's own file changed")
        backup = self.dir / "groups" / ".backup" / g["file"]
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_bytes(), before[g["file"]])
        self.assertIn(room_id, {r["id"] for r in out["roomsUsing"]})
        self.assertEqual(rooms_before,
                         {p.name: p.read_bytes()
                          for p in (self.dir / "rooms").glob("*.json")},
                         "a group save never edits a room file")
        again = rmed.group(gid)
        self.assertEqual(g["pieces"][0].get("optional"),
                         again["pieces"][0].get("optional"))
        self.assertEqual(again["hash"], out["hash"])
        self.assertEqual(again.get("source"), "hand",
                         "a changed group carries the hand marker")

    def test_an_unchanged_save_adds_no_hand_marker(self):
        self.copy_library()
        gid, _ = _room_group()
        g = rmed.group(gid)
        had = g.get("source")
        out = rmed.save_group({"group": g, "hash": g["hash"]})
        self.assertTrue(out["ok"], out)
        self.assertEqual(rmed.group(gid).get("source"), had)

    def test_a_stale_hash_is_refused(self):
        self.copy_library()
        gid, _ = _room_group()
        g = rmed.group(gid)
        before = self.snapshot()
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.save_group({"group": g, "hash": "0" * 64})
        self.assertTrue(any("changed on disk" in e
                            for e in caught.exception.errors))
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.dir / "groups" / ".backup").exists())

    def test_a_broken_group_is_refused(self):
        self.copy_library()
        gid, _ = _room_group()
        g = rmed.group(gid)
        g["pieces"][0] = dict(g["pieces"][0], role="nope.nope")
        before = self.snapshot()
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.save_group({"group": g, "hash": g["hash"]})
        self.assertTrue(any(gid in e for e in caught.exception.errors))
        self.assertEqual(before, self.snapshot())

    def test_check_group_reports_the_same_errors_without_writing(self):
        self.copy_library()
        gid, _ = _room_group()
        g = rmed.group(gid)
        g["pieces"][0] = dict(g["pieces"][0], role="nope.nope")
        before = self.snapshot()
        out = rmed.check_group({"group": g})
        self.assertTrue(any(gid in e for e in out["errors"]))
        self.assertEqual(before, self.snapshot())

    def test_a_new_group_lands_where_the_request_says_with_its_pool_entry(self):
        self.copy_library()
        g = {"id": "lux.test.seating", "family": "bedroom",
             "wall": "back", "use": ["north"],
             "pieces": [{"role": "seat.long", "size": [2, 1],
                         "at": [0, 0], "back": "north",
                         "minWealth": "wealthy"}], "kind": "seating"}
        out = rmed.save_group({"group": g, "file": "luxury.json",
                               "hash": rmed._group_file_hashes()["luxury.json"],
                               "pool": {"family": "washroom",
                                        "bands": ["large"]}})
        self.assertTrue(out["ok"], out)
        self.assertEqual("luxury.json", out["file"])
        pools = rmed.room_groups.load(str(self.dir / "groups"))["pools"]
        self.assertIn({"group": "lux.test.seating", "bands": ["large"]},
                      [{"group": e["group"], "bands": e.get("bands")}
                       for e in pools["washroom"]])
        d = rmed.groups("washroom")
        self.assertIn("lux.test.seating", d["groups"], "the pool group is there")
        self.assertIn("lux.test.seating", [e["group"] for e in d["pool"]])

    def test_a_new_group_cannot_take_another_files_id(self):
        self.copy_library()
        gid, _ = _room_group()
        g = rmed.group(gid)
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.save_group({"group": g, "file": "washroom.json",
                             "hash": rmed._group_file_hashes()[g["file"]]})
        self.assertTrue(any("already lives in" in e
                            for e in caught.exception.errors))

    def test_delete_is_refused_while_anything_uses_the_group(self):
        self.copy_library()
        gid, _room = _room_group()
        g = rmed.group(gid)
        before = self.snapshot()
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.delete_group({"id": gid, "hash": g["hash"]})
        self.assertTrue(any("is used by" in e and gid in e
                            for e in caught.exception.errors))
        self.assertEqual(before, self.snapshot())

    def test_an_unused_group_deletes(self):
        self.copy_library()
        g = {"id": "lux.test.seating", "family": "bedroom",
             "wall": "back", "use": ["north"],
             "pieces": [{"role": "seat.long", "size": [2, 1],
                         "at": [0, 0], "back": "north",
                         "minWealth": "wealthy"}], "kind": "seating"}
        rmed.save_group({"group": g, "file": "luxury.json",
                         "hash": rmed._group_file_hashes()["luxury.json"]})
        out = rmed.delete_group({"id": "lux.test.seating",
                                 "hash": rmed._group_file_hashes()["luxury.json"]})
        self.assertTrue(out["ok"])
        self.assertNotIn("lux.test.seating",
                         {x["id"] for x in rmed.allgroups()["groups"]})


class TestRecipeSave(LibraryTestCase):
    """The recipe endpoint: an entry added by hand (source: "hand") is
    written into the recipe's own file and survives a reload; a broken
    recipe is refused with the file untouched."""

    def _recipe(self, family="bedroom"):
        d = rmed.groups(family)
        return d["recipes"][0], d["hashes"]

    def test_an_added_entry_is_written(self):
        self.copy_library()
        r, hashes = self._recipe()
        entry = {"group": "decor.floor.single", "kind": "optional",
                 "count": 1, "source": "hand"}
        r["groups"] = r["groups"] + [entry]
        out = rmed.save_recipe({"recipe": r, "hash": hashes[r["file"]]})
        self.assertTrue(out["ok"], out)
        again = rmed.groups(r["family"])["recipes"]
        mine = next(x for x in again if x["layout"] == r["layout"])
        self.assertEqual(entry, mine["groups"][-1])

    def test_a_broken_recipe_is_refused(self):
        self.copy_library()
        r, hashes = self._recipe()
        r["groups"][0] = dict(r["groups"][0], group="nope.nope")
        before = {p.name: p.read_bytes()
                  for p in (self.dir / "groups").glob("*.json")}
        with self.assertRaises(rmed.SaveError) as caught:
            rmed.save_recipe({"recipe": r, "hash": hashes[r["file"]]})
        self.assertTrue(any("nope.nope" in e for e in caught.exception.errors))
        self.assertEqual(before, {p.name: p.read_bytes()
                                  for p in (self.dir / "groups").glob("*.json")})


if __name__ == "__main__":
    unittest.main()
