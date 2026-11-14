"""The rebuild endpoints of the Scenario Editor, over HTTP with the model
mocked at the wire (the fake Client is the generator's real one with only the
HTTP POST replaced): one model call edits a building's design in the saved
plan, then the generator's own relayout — a real build, no model — re-places
the world. The workspace is untouched until the stage is applied; applying it
backs the old scenario and media up and carries images onto the new ids by
name.

The workspace under test is built once, for real, in setUpClass: the village
fixture's plan written as plan.json beside a scenario a relayout produced.
"""
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent          # tools/scenario-editor
sys.path.insert(0, str(HERE))

import worldgen_editor as wg                           # noqa: E402  (gallery + generator on sys.path)
import image_gallery as ig                             # noqa: E402
from worldgen import api as wgapi                      # noqa: E402
from worldgen import llm as wgllm                      # noqa: E402
from worldgen import phases as wgphases                # noqa: E402
import scenario_editor as se                           # noqa: E402
import rebuild_editor as rb                            # noqa: E402

FIXTURE = HERE.parent / "world-generator" / "fixtures" / "village.json"
FULL_KEY = "sk-rebuild-1234567890abcd"                 # must never reach the browser
TARGET = "The Green Dragon Inn"
INSTRUCTION = "turn the common room into a proper taproom"
SEED = 42                                              # the workspace's own seed
ZONE = "Village Green"                                 # the target building's zone
REDRESS_INSTRUCTION = "a proper market: stalls and carts around the cross"
POPULATE_INSTRUCTION = "two farmhands for the harvest, billeted at the cottage"
EMPTY_ZONE = "King's Wood"                             # dressed by P4, no buildings

STATE = {"replies": [], "sleep": 0.0}   # what the mocked wire serves
INSTALLED = []                          # every fake client the rebuild built


class FakeClient(wgllm.Client):
    """The generator's real Client with the network cut out: _post serves the
    queued raw replies (sleeping first when a test needs a slow model);
    everything else — the contract loop, the counters, the call logs — is the
    real code. No providers.json is read."""

    def __init__(self, provider, providers_path=wgllm.PROVIDERS_PATH, log_dir=None):
        self.provider = provider
        self.model = "mock-model"
        self.base_url = "http://127.0.0.1:1/v1"
        self._api_key = FULL_KEY
        self.max_tokens = 4000
        self.timeout = 30
        self.rate_limit_wait = 0
        self.max_output = None
        self.extra_body = {}
        self.vision = False
        self.on_wait = None
        self.log_dir = log_dir
        self.calls = 0
        self.retries = 0
        self.last_error = None
        self.last_cut = False
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.seconds = 0.0
        self.attempts = []              # the messages of every wire attempt
        INSTALLED.append(self)

    def _post(self, messages, max_tokens=None):
        self.attempts.append([dict(m) for m in messages])
        raw = STATE["replies"].pop(0)
        if STATE["sleep"]:
            time.sleep(STATE["sleep"])
        return raw, {"prompt": 10, "completion": 5, "total": 15, "finish": "stop"}


def renamed_design(old="Common Room", new="Taproom"):
    """The fixture's own design for the target building with one room renamed
    everywhere it is referenced — a valid p3 reply that changes the world."""
    plan = json.loads(FIXTURE.read_text("utf-8"))
    d = json.loads(json.dumps(next(b for b in plan["buildings"] if b["name"] == TARGET)))
    for r in d["rooms"]:
        if r["name"] == old:
            r["name"] = new
    d["connections"] = [[new if x == old else x for x in c] for c in d["connections"]]
    if d["entrance"]["room"] == old:
        d["entrance"]["room"] = new
    for f in d["furniture"]:
        if f["room"] == old:
            f["room"] = new
    return d


def named_design(name):
    """The fixture's design under a wrong name — a reply check_p3 rejects."""
    d = renamed_design()
    d["name"] = name
    return d


def redressed_dressing():
    """The fixture's own dressing for ZONE with one prop swapped — a valid p4
    reply that changes the outdoors."""
    plan = json.loads(FIXTURE.read_text("utf-8"))
    z = next(z for z in plan["zones"] if z["name"] == ZONE)
    d = json.loads(json.dumps(z["dressing"]))
    for p in d["props"]:
        if p["template"] == "Market cross":
            p.update(template="Hay bale", count=2, hint="scatter")
    return d


def unknown_template_dressing():
    """The redressed reply naming a template the catalogue does not carry."""
    d = redressed_dressing()
    d["props"][0]["template"] = "Golden Fountain"
    return d


def added_people():
    """Two fresh villagers for ZONE — homes in its bedded buildings, works
    among the plan's real buildings and zones — a valid p5 reply."""
    def person(name, gender, work):
        return {"name": name, "gender": gender, "role": "farmhand",
                "home": "Oak Cottage", "work": work,
                "description": f"{name.split()[0]} came for the harvest and "
                               "stays for the wages.",
                "physicalDescription": "Sun-browned, rope belt, patched sleeves."}
    return {"npcs": [person("Nell Ashby", "female", "Millfield"),
                     person("Tam Ashby", "male", "Tithe Barn")]}


class TestRebuildEndpoints(unittest.TestCase):
    srv = None
    base = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="rebuild-editor-test-")
        t = Path(cls.tmp.name)
        cls.addClassCleanup(cls.tmp.cleanup)
        wg.PROVIDERS_JSON = t / "providers.json"
        old_work, old_backups, old_out = ig.WORK, ig.BACKUPS, wg.OUT_ROOT
        ig.WORK, ig.BACKUPS, wg.OUT_ROOT = t / "work", t / "backups", t / "out"
        cls.addClassCleanup(setattr, ig, "WORK", old_work)
        cls.addClassCleanup(setattr, ig, "BACKUPS", old_backups)
        cls.addClassCleanup(setattr, wg, "OUT_ROOT", old_out)
        wg.save_provider("mockp", "http://127.0.0.1:1/v1", FULL_KEY, "mock-model", 16000)

        # the workspace: one real build from the fixture's plan (no model),
        # imported as a workspace with that plan saved beside it
        init_out = t / "out-init"
        summary = wgapi.relayout(str(FIXTURE), seed=SEED, out_dir=str(init_out))
        cls.sid = wg._to_workspace(init_out, summary, FIXTURE)
        cls.ws = Path(ig.WORK) / cls.sid[len("work/"):]

        se.Handler.store = t / "store"
        se.Handler.store.mkdir()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), se.Handler)
        cls.addClassCleanup(cls.srv.shutdown)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    def setUp(self):
        rb._job = None                 # no rebuild of an earlier test is running
        rb._staged = None              # and no stage is left over
        INSTALLED.clear()
        STATE["replies"] = []
        STATE["sleep"] = 0.0
        p = patch.object(wgllm, "Client", FakeClient)
        p.start()
        self.addCleanup(p.stop)

    # ------------------------------------------------------------ http helpers
    @classmethod
    def request(cls, method, path, body=None):
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        req = urllib.request.Request(cls.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    @classmethod
    def get(cls, path):
        code, raw = cls.request("GET", path)
        assert code == 200, f"GET {path}: {code} {raw}"
        return json.loads(raw)

    def rebuild_body(self, **over):
        body = {"source": self.sid, "provider": "mockp", "kind": "building",
                "target": TARGET, "instruction": INSTRUCTION, "seed": SEED}
        body.update(over)
        return body

    def rebuild(self, **over):
        """One POST /api/assistant/rebuild with a small valid body; ``over``
        replaces fields. Returns the running job."""
        code, raw = self.request("POST", "/api/assistant/rebuild", self.rebuild_body(**over))
        assert code == 200, f"POST /api/assistant/rebuild: {code} {raw}"
        return json.loads(raw)["job"]

    def redress(self, **over):
        """A redress_zone rebuild of ZONE; ``over`` replaces fields."""
        return self.rebuild(kind="redress_zone", target=ZONE,
                            instruction=REDRESS_INSTRUCTION, **over)

    def populate(self, **over):
        """A populate_zone rebuild of ZONE; ``over`` replaces fields."""
        return self.rebuild(kind="populate_zone", target=ZONE,
                            instruction=POPULATE_INSTRUCTION, **over)

    def wait_done(self, job_id, timeout=90):
        deadline = time.time() + timeout
        while time.time() < deadline:
            j = self.get("/api/assistant/rebuild")["job"]
            if j and j["id"] == job_id and j["state"] != "running":
                return j
            time.sleep(0.1)
        raise AssertionError(f"rebuild job {job_id} did not finish in {timeout}s")

    def finish(self, job):
        done = self.wait_done(job["id"])
        self.assertEqual(done["state"], "done", done["error"])
        return done

    def snapshot(self):
        """The workspace's whole current state, to prove it untouched."""
        files = {str(p.relative_to(self.ws)): p.read_bytes()
                 for p in sorted(self.ws.rglob("*")) if p.is_file()}
        return files

    def restore_workspace(self, files):
        """Put the workspace's files back exactly as they were: a test that
        applies a stage must not leave its plan and media for the tests after
        it (the class workspace is built once)."""
        shutil.rmtree(self.ws)
        for rel, data in files.items():
            dst = self.ws / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)

    @staticmethod
    def npc_id(scn, name):
        return next(e["id"] for e in scn["entities"]
                    if e.get("type") == "npc" and e.get("name") == name)

    # ------------------------------------------------------------ a happy rebuild
    def test_a_happy_rebuild_stages_a_preview_and_touches_nothing(self):
        before = self.snapshot()
        STATE["replies"] = [json.dumps(renamed_design())]
        done = self.finish(self.rebuild())
        self.assertEqual(done["target"], TARGET)
        self.assertEqual(done["seed"], SEED)
        self.assertEqual(done["provider"], "mockp")
        self.assertEqual(done["model"], "mock-model")
        self.assertEqual(done["calls"], 1)
        staged = self.get("/api/assistant/rebuild")["staged"]
        self.assertEqual(staged["building"], TARGET)
        self.assertEqual(staged["seed"], SEED)
        self.assertIn(f"{TARGET} Taproom", staged["preview"]["regions"]["added"])
        self.assertIn(f"{TARGET} Common Room", staged["preview"]["regions"]["removed"])
        counts = staged["preview"]["counts"]
        self.assertEqual(counts["npcs"][0], counts["npcs"][1])
        self.assertEqual(counts["doors"][0], counts["doors"][1])
        self.assertIn("reachability", staged["preview"]["metrics"])
        self.assertLess(len(json.dumps(staged["preview"])), 4096)
        self.assertTrue(Path(staged["out_dir"]).is_dir())
        self.assertTrue(Path(staged["plan_path"]).is_file())
        # ...and the workspace has not changed one byte
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(INSTALLED[-1].attempts), 1)   # accepted on the first try

    def test_the_prompt_mirrors_the_original_p3_lines_plus_the_instruction(self):
        STATE["replies"] = [json.dumps(renamed_design())]
        self.finish(self.rebuild())
        sent = INSTALLED[-1].attempts[0]
        self.assertEqual(sent[0], {"role": "system", "content":
                                   "You generate scenario data for a map RPG. "
                                   "You reply with one JSON object and nothing else."})
        user = sent[1]["content"]
        self.assertIn(f"The user wants this building redesigned as follows — obey it: "
                      f"{INSTRUCTION}", user)
        plan = json.loads(FIXTURE.read_text("utf-8"))
        zone = next(z for z in plan["zones"]
                    if any(b["name"] == TARGET for b in z["buildings"]))
        b = next(x for x in zone["buildings"] if x["name"] == TARGET)
        self.assertIn(wgphases._setting_line(plan, plan.get("frame")), user)
        self.assertIn(wgphases._zone_line(zone), user)
        self.assertIn(wgphases._building_line(b), user)
        self.assertIn(wgphases._compound_line(plan.get("compounds") or [], zone, b), user)
        self.assertIn(wgphases._units_line(b), user)
        self.assertIn("- Straw bed | 1x2 | note: along the wall of a sleeping room, "
                      "never blocking a door", user)

    def test_an_invalid_design_is_retried_with_the_errors_fed_back(self):
        STATE["replies"] = [json.dumps(named_design("The Wrong Inn")),
                            json.dumps(renamed_design())]
        done = self.finish(self.rebuild())
        self.assertEqual(done["calls"], 1)             # one call, two attempts
        fake = INSTALLED[-1]
        self.assertEqual(len(fake.attempts), 2)        # exactly one retry
        first, again = fake.attempts
        self.assertEqual(again[:2], first)             # system + prompt unchanged
        self.assertEqual(again[2]["role"], "assistant")  # the bad reply quoted back
        self.assertIn("The Wrong Inn", again[2]["content"])
        self.assertEqual(again[3]["role"], "user")     # ...and the error fed back
        self.assertIn(f"reply name must be exactly {TARGET!r}", again[3]["content"])

    # ------------------------------------------------------------ refused and busy
    def test_bad_requests_are_refused_before_any_job_starts(self):
        code, raw = self.request("GET", "/api/assistant/rebuild")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw), {"job": None, "staged": None})
        for over, needle in (
                ({"target": "The Blue Dragon Inn"}, "no building named"),
                ({"target": "the green dragon inn"}, "no building named"),
                ({"instruction": ""}, "instruction"),
                ({"instruction": "x" * 1001}, "1-1000"),
                ({"source": "staging"}, "workspace"),
                ({"source": "work/nope"}, "workspace"),
                ({"kind": "zone"}, "kind"),
                ({"seed": "later"}, "seed")):
            code, raw = self.request("POST", "/api/assistant/rebuild",
                                     {"source": self.sid, "provider": "mockp",
                                      "kind": "building", "target": TARGET,
                                      "instruction": INSTRUCTION, "seed": SEED, **over})
            self.assertEqual(code, 400, over)
            self.assertIn(needle, raw)
        self.assertFalse(INSTALLED)                    # the model was never asked

    def test_a_second_rebuild_while_one_runs_is_busy(self):
        STATE["sleep"] = 2.0
        STATE["replies"] = [json.dumps(renamed_design())]
        first = self.rebuild()
        code, raw = self.request("POST", "/api/assistant/rebuild", self.rebuild_body())
        self.assertEqual(code, 409)
        self.assertTrue(json.loads(raw)["busy"])
        done = self.finish(first)                      # the first still completes
        self.assertEqual(done["state"], "done")

    # ------------------------------------------------------------ applying a stage
    def test_apply_replaces_the_workspace_and_carries_images_by_name(self):
        STATE["replies"] = [json.dumps(renamed_design())]
        self.finish(self.rebuild())
        staged = self.get("/api/assistant/rebuild")["staged"]
        # a portrait exists for the old innkeeper's id, under the old id's folder
        old_scn = json.loads((self.ws / "scenario.json").read_text("utf-8"))
        old_id = self.npc_id(old_scn, "Maribel Dabney")
        portrait = self.ws / "media" / old_id / f"{old_id}-portrait.webp"
        portrait.parent.mkdir(parents=True)
        portrait.write_bytes(b"planted-portrait-bytes")

        code, raw = self.request("POST", "/api/assistant/rebuild/apply")
        self.assertEqual(code, 200, raw)
        out = json.loads(raw)
        self.assertTrue(out["applied"])
        self.assertEqual(out["carried"], 1)

        # the previous scenario and the whole media tree live under the backup
        backup = Path(out["backup"])
        self.assertIn("-rebuild", backup.name)
        self.assertEqual(json.loads((backup / "scenario.json").read_text("utf-8")),
                         old_scn)
        self.assertEqual((backup / "media" / old_id / f"{old_id}-portrait.webp")
                         .read_bytes(), b"planted-portrait-bytes")

        # the workspace now holds the new build, and the plan is the edited one
        new_scn = json.loads((self.ws / "scenario.json").read_text("utf-8"))
        built = json.loads((Path(staged["built_dir"]) / "scenario.json")
                           .read_text("utf-8"))
        self.assertEqual(new_scn, built)
        self.assertEqual(json.loads((self.ws / "plan.json").read_text("utf-8")),
                         json.loads((Path(staged["plan_path"])).read_text("utf-8")))
        inn = next(b for b in json.loads((self.ws / "plan.json").read_text("utf-8"))
                   ["buildings"] if b["name"] == TARGET)
        self.assertIn("Taproom", [r["name"] for r in inn["rooms"]])

        # the carried portrait: same npc by name, brand-new id
        new_id = self.npc_id(new_scn, "Maribel Dabney")
        self.assertNotEqual(new_id, old_id)
        carried = self.ws / "media" / new_id / f"{new_id}-portrait.webp"
        self.assertTrue(carried.is_file(), f"no portrait carried to {new_id}")
        self.assertEqual(carried.read_bytes(), b"planted-portrait-bytes")
        self.assertFalse((self.ws / "media" / old_id).exists())

        # the stage is gone, and the key never left the server
        self.assertIsNone(self.get("/api/assistant/rebuild")["staged"])
        self.assertNotIn(FULL_KEY, raw)
        self.assertNotIn(FULL_KEY,
                         self.request("GET", "/api/assistant/rebuild")[1])

    def test_apply_without_a_stage_is_refused(self):
        code, raw = self.request("POST", "/api/assistant/rebuild/apply")
        self.assertEqual(code, 400)
        self.assertIn("staged", raw)

    def test_discard_leaves_the_workspace_untouched(self):
        before = self.snapshot()
        STATE["replies"] = [json.dumps(renamed_design())]
        self.finish(self.rebuild())
        self.assertIsNotNone(self.get("/api/assistant/rebuild")["staged"])
        code, raw = self.request("POST", "/api/assistant/rebuild/discard")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(raw)["ok"])
        self.assertIsNone(self.get("/api/assistant/rebuild")["staged"])
        self.assertEqual(self.snapshot(), before)
        code, raw = self.request("POST", "/api/assistant/rebuild/discard")
        self.assertEqual(code, 400)                    # nothing left to discard

    # ------------------------------------------------------------ redress_zone
    def test_a_redress_replaces_only_that_zones_dressing(self):
        before = self.snapshot()
        STATE["replies"] = [json.dumps(redressed_dressing())]
        done = self.finish(self.redress())
        self.assertEqual(done["target"], ZONE)
        self.assertEqual(done["calls"], 1)
        staged = self.get("/api/assistant/rebuild")["staged"]
        self.assertEqual(staged["zone"], ZONE)
        self.assertEqual(staged["preview"]["dressingProps"],
                         {"Hay bale": [0, 2], "Market cross": [1, 0],
                          "Village well": [1, 1]})
        self.assertIn("metrics", staged["preview"])    # the shared pipeline
        self.assertIn("regions", staged["preview"])
        plan = json.loads(Path(staged["plan_path"]).read_text("utf-8"))
        fixture = json.loads(FIXTURE.read_text("utf-8"))
        green = next(z for z in plan["zones"] if z["name"] == ZONE)
        self.assertEqual([(p["template"], p["count"]) for p in green["dressing"]["props"]],
                         [("Village well", 1), ("Hay bale", 2)])
        self.assertEqual(green["dressing"]["paths"], "dirt")
        fz = next(z for z in fixture["zones"] if z["name"] == ZONE)
        self.assertEqual(green["dressing"]["filler"], fz["dressing"]["filler"])
        # every other zone's dressing is untouched, and so is the workspace
        for other in fixture["zones"]:
            if other["name"] != ZONE:
                mine = next(z for z in plan["zones"] if z["name"] == other["name"])
                self.assertEqual(mine["dressing"], other["dressing"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(INSTALLED[-1].attempts), 1)   # accepted on the first try

    def test_the_redress_prompt_mirrors_the_p4_lines_plus_the_instruction(self):
        STATE["replies"] = [json.dumps(redressed_dressing())]
        self.finish(self.redress())
        sent = INSTALLED[-1].attempts[0]
        self.assertEqual(sent[0]["role"], "system")
        user = sent[1]["content"]
        self.assertIn(f"The user wants this zone's outdoor dressing redone as "
                      f"follows — obey it: {REDRESS_INSTRUCTION}", user)
        plan = json.loads(FIXTURE.read_text("utf-8"))
        zone = next(z for z in plan["zones"] if z["name"] == ZONE)
        self.assertIn(wgphases._setting_line(plan, plan.get("frame")), user)
        self.assertIn(wgphases._zone_line(zone), user)
        for b in zone["buildings"]:
            self.assertIn(wgphases._building_line(b), user)
        self.assertIn(wgphases._catalogue_lines(plan["templates"]), user)
        # only this zone's buildings: Millfield's barn is nowhere in it
        barn = next(b for z in plan["zones"] if z["name"] == "Millfield"
                    for b in z["buildings"])
        self.assertNotIn(wgphases._building_line(barn), user)

    def test_a_redress_naming_an_unknown_template_is_retried(self):
        STATE["replies"] = [json.dumps(unknown_template_dressing()),
                            json.dumps(redressed_dressing())]
        done = self.finish(self.redress())
        self.assertEqual(done["calls"], 1)             # one call, two attempts
        fake = INSTALLED[-1]
        self.assertEqual(len(fake.attempts), 2)        # exactly one retry
        first, again = fake.attempts
        self.assertEqual(again[:2], first)             # system + prompt unchanged
        self.assertIn("Golden Fountain", again[2]["content"])
        self.assertIn("not in the catalogue", again[3]["content"])

    # ------------------------------------------------------------ populate_zone
    def test_a_populate_appends_new_people_after_the_existing_ones(self):
        before = self.snapshot()
        STATE["replies"] = [json.dumps(added_people())]
        done = self.finish(self.populate())
        self.assertEqual(done["target"], ZONE)
        staged = self.get("/api/assistant/rebuild")["staged"]
        self.assertEqual(staged["zone"], ZONE)
        self.assertEqual(staged["preview"]["npcs"],
                         {"added": ["Nell Ashby", "Tam Ashby"], "removed": []})
        self.assertEqual(sorted(staged["preview"]["npcNames"]["added"]),
                         ["Nell Ashby", "Tam Ashby"])
        self.assertEqual(staged["preview"]["npcNames"]["removed"], [])
        plan = json.loads(Path(staged["plan_path"]).read_text("utf-8"))
        fixture = json.loads(FIXTURE.read_text("utf-8"))
        self.assertEqual(plan["npcs"][:len(fixture["npcs"])], fixture["npcs"])
        self.assertEqual([p["name"] for p in plan["npcs"][len(fixture["npcs"]):]],
                         ["Nell Ashby", "Tam Ashby"])
        # ...and the workspace has not changed one byte
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(INSTALLED[-1].attempts), 1)

    def test_the_populate_prompt_mirrors_the_p5_zone_batch_lines(self):
        STATE["replies"] = [json.dumps(added_people())]
        self.finish(self.populate())
        user = INSTALLED[-1].attempts[0][1]["content"]
        plan = json.loads(FIXTURE.read_text("utf-8"))
        zone = next(z for z in plan["zones"] if z["name"] == ZONE)
        self.assertIn(f"The user wants people added to this zone as follows — "
                      f"obey it: add to the people made so far, never remove "
                      f"or rename them: {POPULATE_INSTRUCTION}", user)
        self.assertIn(wgphases._setting_line(plan, plan.get("frame")), user)
        self.assertIn(wgphases._zone_line(zone), user)
        self.assertIn("Village Green, Millfield, King's Wood", user)
        # the inn's bed note: 3 beds, 1 of them its keeper's home, 2 spare
        self.assertIn("sleeps 1 (0 spots free), plus 2 spare bed(s) for "
                      "guests or patients, nobody's home", user)
        self.assertIn("- Maribel Dabney, innkeeper, sleeps at The Green Dragon Inn", user)
        self.assertIn("this zone's buildings hold 6 bed(s) (1 home bed(s) "
                      "free), 3 people live here now", user)

    def test_a_populate_reusing_a_name_or_homing_outside_the_zone_is_retried(self):
        bad_name = added_people()
        bad_name["npcs"][0]["name"] = "Maribel Dabney"    # a name the plan has
        bad_home = added_people()
        bad_home["npcs"][0]["home"] = "Tithe Barn"        # a building, another zone
        STATE["replies"] = [json.dumps(bad_name), json.dumps(bad_home),
                            json.dumps(added_people())]
        done = self.finish(self.populate())
        self.assertEqual(done["calls"], 1)             # one call, three attempts
        fake = INSTALLED[-1]
        self.assertEqual(len(fake.attempts), 3)
        self.assertIn("already on the roster", fake.attempts[1][-1]["content"])
        self.assertIn("must be a building of Village Green",
                      fake.attempts[2][-1]["content"])
        staged = self.get("/api/assistant/rebuild")["staged"]
        self.assertEqual(staged["preview"]["npcs"]["added"],
                         ["Nell Ashby", "Tam Ashby"])

    def test_the_zone_kinds_refuse_a_bad_target_before_any_job_starts(self):
        for kind, target, needle in (
                ("redress_zone", "Nowhere", "no zone named"),
                ("redress_zone", ZONE.lower(), "no zone named"),
                ("populate_zone", "Nowhere", "no zone named"),
                ("populate_zone", EMPTY_ZONE, "no buildings"),
                ("populate_zone", "Millfield", "has a bed")):
            code, raw = self.request("POST", "/api/assistant/rebuild",
                                     {"source": self.sid, "provider": "mockp",
                                      "kind": kind, "target": target,
                                      "instruction": "more life", "seed": SEED})
            self.assertEqual(code, 400, (kind, target))
            self.assertIn(needle, raw)
        self.assertFalse(INSTALLED)                    # the model was never asked

    def test_zone_rebuilds_and_building_rebuilds_are_one_at_a_time(self):
        STATE["sleep"] = 2.0
        STATE["replies"] = [json.dumps(redressed_dressing())]
        first = self.redress()
        for body in (self.rebuild_body(kind="populate_zone", target=ZONE,
                                       instruction=POPULATE_INSTRUCTION),
                     self.rebuild_body()):              # the building kind too
            code, raw = self.request("POST", "/api/assistant/rebuild", body)
            self.assertEqual(code, 409)
            self.assertTrue(json.loads(raw)["busy"])
        done = self.finish(first)                      # the first still completes
        self.assertEqual(done["state"], "done")

    def test_apply_after_populate_carries_a_portrait_by_name(self):
        before = self.snapshot()      # restored afterwards: the tests after
        self.addCleanup(self.restore_workspace, before)   # this one stay pristine
        STATE["replies"] = [json.dumps(added_people())]
        self.finish(self.populate())
        # a portrait exists for the old innkeeper's id, under the old id's folder
        old_scn = json.loads((self.ws / "scenario.json").read_text("utf-8"))
        old_id = self.npc_id(old_scn, "Maribel Dabney")
        portrait = self.ws / "media" / old_id / f"{old_id}-portrait.webp"
        portrait.parent.mkdir(parents=True)
        portrait.write_bytes(b"planted-portrait-bytes")

        code, raw = self.request("POST", "/api/assistant/rebuild/apply")
        self.assertEqual(code, 200, raw)
        out = json.loads(raw)
        self.assertTrue(out["applied"])
        self.assertEqual(out["carried"], 1)

        # the added people are in the applied build, and the plan is the populated one
        new_scn = json.loads((self.ws / "scenario.json").read_text("utf-8"))
        self.npc_id(new_scn, "Nell Ashby")
        self.npc_id(new_scn, "Tam Ashby")
        self.assertEqual([p["name"] for p in json.loads(
            (self.ws / "plan.json").read_text("utf-8"))["npcs"]][-2:],
            ["Nell Ashby", "Tam Ashby"])

        # the carried portrait: the same npc by name, brand-new id
        new_id = self.npc_id(new_scn, "Maribel Dabney")
        self.assertNotEqual(new_id, old_id)
        carried = self.ws / "media" / new_id / f"{new_id}-portrait.webp"
        self.assertTrue(carried.is_file(), f"no portrait carried to {new_id}")
        self.assertEqual(carried.read_bytes(), b"planted-portrait-bytes")
        self.assertIsNone(self.get("/api/assistant/rebuild")["staged"])


if __name__ == "__main__":
    unittest.main()
