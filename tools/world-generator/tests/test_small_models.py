"""What the small-model baselines of November 2026 found. Free models and slow
local ones failed in ways that read as the model being too weak: a 429 ended a
run in half a second, one odd character lost 77 minutes, and most retries were
mistakes code can put right without asking again."""
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.test_model import (CANNED_COTTAGE, CANNED_P4_VILLAGE, CANNED_TEMPLATES,
                              ScriptedClient, _dump, canned_replies)
from worldgen import cast, llm, phases


def busy(code=429, retry_after=None):
    return llm.HTTPStatusError(f"HTTP {code}: busy upstream", code, retry_after)


class PostClient(llm.Client):
    """A Client whose single POST pops a script of replies and errors, so the
    waiting in _request is the real thing."""

    def __init__(self, script, limit=60, log_dir=None):
        self.provider, self.model, self.max_tokens = "stub", "stub-model", 100
        self.base_url, self._api_key, self.log_dir = "http://stub", "x", log_dir
        self.calls, self.retries, self.seconds = 0, 0, 0.0
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.rate_limit_wait = limit
        self.script = list(script)
        self.posts = 0

    def _post(self, messages, max_tokens=None):
        self.posts += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step, {"prompt": 1, "completion": 1, "total": 2}


class TestBusyProvider(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(llm.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def slept(self):
        return sum(c.args[0] for c in self.sleep.call_args_list)

    def test_a_429_is_waited_out_and_costs_no_retry(self):
        c = PostClient([busy(), busy(), '{"ok": 1}'])
        self.assertEqual(c.call("p1", "sys", "user"), {"ok": 1})
        self.assertEqual(c.retries, 0)
        self.assertEqual(self.slept(), 15, "5 then 10 seconds")

    def test_a_5xx_is_waited_out_too(self):
        c = PostClient([busy(503), '{"ok": 1}'])
        self.assertEqual(c.call("p1", "sys", "user"), {"ok": 1})

    def test_retry_after_wins_when_it_is_longer(self):
        c = PostClient([busy(retry_after=30), '{"ok": 1}'])
        c.call("p1", "sys", "user")
        self.assertEqual(self.slept(), 30)

    def test_retry_after_is_capped(self):
        c = PostClient([busy(retry_after=100000), '{"ok": 1}'])
        c.call("p1", "sys", "user")
        self.assertEqual(self.slept(), llm.BUSY_LONGEST_PAUSE)

    def test_the_header_is_read_as_seconds_or_not_at_all(self):
        self.assertEqual(llm._retry_after({"Retry-After": "7"}), 7)
        self.assertIsNone(llm._retry_after({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))
        self.assertIsNone(llm._retry_after(None))

    def test_giving_up_ends_the_run_and_blames_the_provider(self):
        c = PostClient([busy()], limit=10)
        with self.assertRaises(llm.ProviderBusy) as caught:
            c.call("p1", "sys", "user")
        self.assertIn("not the model", str(caught.exception))
        self.assertIn("stub-model", str(caught.exception))
        self.assertEqual(c.posts, 3, "one wait, not one per retry")

    def test_giving_up_still_writes_the_call_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = PostClient([busy()], limit=0, log_dir=tmp)
            with self.assertRaises(llm.ProviderBusy):
                c.call("p1", "sys", "user")
            with open(os.path.join(tmp, "01-p1.json"), encoding="utf-8") as f:
                record = json.load(f)
            self.assertIn("not the model", record["attempts"][0]["errors"][0])

    def test_other_errors_are_not_waited_for(self):
        c = PostClient([busy(401)])
        self.assertIsNone(c.call("p1", "sys", "user"))
        self.assertEqual(self.slept(), 0)

    def test_a_phase_with_no_reply_says_why(self):
        c = PostClient([busy(401)])
        c.call("p1", "sys", "user")
        self.assertIn("HTTP 401", phases._no_reply("P1", c))

    def test_a_phase_with_a_bad_reply_keeps_its_old_error(self):
        c = PostClient(["no json here"])
        c.call("p1", "sys", "user")
        self.assertEqual(phases._no_reply("P1", c), "P1 produced no JSON at all")

    def test_a_cancelled_run_stops_waiting(self):
        c = PostClient([busy()])

        def stop(_wait):
            raise phases.Cancelled("stop")
        c.on_wait = stop
        with self.assertRaises(phases.Cancelled):
            c.call("p1", "sys", "user")
        self.assertEqual(self.slept(), 0)

    def test_the_run_reports_the_wait_and_ends_on_the_provider_error(self):
        events = []
        with self.assertRaises(llm.ProviderBusy):
            phases.run_phases("a hamlet", PostClient([busy()], limit=5), progress=events.append)
        self.assertTrue(any("the provider is busy (HTTP 429)" in e["label"] for e in events),
                        events)


class TestTimeoutSetting(unittest.TestCase):
    def client(self, **entry):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "providers.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"p": dict({"base_url": "http://stub", "api_key": "none",
                                      "model": "m"}, **entry)}, f)
            return llm.Client("p", providers_path=path)

    def timeout_used(self, client):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()) as opened:
            with self.assertRaises(llm.LLMError):
                client._post([{"role": "user", "content": "x"}])
        return opened.call_args.kwargs["timeout"]

    def test_the_default_fits_a_slow_model_s_catalogue(self):
        self.assertEqual(self.timeout_used(self.client()), llm.REQUEST_TIMEOUT)
        self.assertGreaterEqual(llm.REQUEST_TIMEOUT, 1700, "32000 tokens at 19 a second")

    def test_a_provider_can_set_its_own(self):
        self.assertEqual(self.timeout_used(self.client(timeout=7200)), 7200)

    def test_a_timeout_says_what_to_change(self):
        c = self.client(timeout=5)
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(llm.LLMError) as caught:
                c._post([{"role": "user", "content": "x"}])
        self.assertIn('"timeout"', str(caught.exception))

    def test_a_bad_setting_is_refused(self):
        with self.assertRaises(llm.LLMError):
            self.client(timeout="soon")
        with self.assertRaises(llm.LLMError):
            self.client(rate_limit_wait=-1)


class TestLoneSurrogates(unittest.TestCase):
    REPLY = '{"name": "A\\ud86aB", "\\ud86akey": ["\\ud86a", "\\ud83d\\ude00"]}'

    def test_a_reply_with_one_parses_clean(self):
        got = PostClient([self.REPLY]).call("p6a", "sys", "user")
        self.assertEqual(got, {"name": "AB", "key": ["", "\U0001F600"]})

    def test_it_can_be_written_as_utf8(self):
        got = PostClient([self.REPLY]).call("p6a", "sys", "user")
        json.dumps(got, ensure_ascii=False).encode("utf-8")

    def test_the_call_log_survives_the_raw_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = PostClient(['{"a": 1}'], log_dir=tmp)
            real = c._post
            c._post = lambda m, t=None: ('{"a": "\ud86a"}', real(m, t)[1])
            c.call("p6a", "sys", "user")
            self.assertTrue(os.path.exists(os.path.join(tmp, "01-p6a.json")))


class TestRepairHint(unittest.TestCase):
    T = ("Stone hearth", "Table")

    def fix(self, hint, buildings=()):
        return phases.repair_hint(hint, self.T, buildings)

    def test_a_reference_in_the_wrong_case_is_corrected(self):
        self.assertEqual(self.fix("corner+beside:stone hearth"), "corner+beside:Stone hearth")

    def test_a_reference_to_nothing_goes(self):
        self.assertEqual(self.fix("corner+beside:Widow's Hut"), "corner")

    def test_a_copied_placeholder_goes(self):
        self.assertEqual(self.fix("beside:<building>"), "")

    def test_a_copied_rule_keeps_what_it_can(self):
        self.assertEqual(self.fix("flush against the back wall of the kitchen"), "")
        self.assertEqual(self.fix("along the north wall of every home"), "wall:north")

    def test_other_separators_and_spellings(self):
        self.assertEqual(self.fix("wall:north, wall:south"), "wall:north+wall:south")
        self.assertEqual(self.fix("along:north"), "wall:north")
        self.assertEqual(self.fix("Corner"), "corner")
        self.assertEqual(self.fix("in the centre"), "center")

    def test_buildings_count_outdoors(self):
        self.assertEqual(self.fix("behind:the mill", ("The Mill",)), "behind:The Mill")
        self.assertEqual(self.fix("behind:the mill"), "", "nothing to stand behind indoors")

    def test_what_comes_out_passes_the_check(self):
        for hint in ("corner+beside:stone hearth", "flush against it", "wall:north, corner"):
            self.assertEqual(phases.hint_errors(self.fix(hint), templates=set(self.T)), [])


class TestRepairs(unittest.TestCase):
    def setUp(self):
        self.tnames = {t["name"] for t in CANNED_TEMPLATES}
        self.log = []

    def cottage(self):
        return json.loads(json.dumps(CANNED_COTTAGE))

    def p3(self, d, has_yard=False):
        phases.repair_p3(d, "Miller's Cottage", self.tnames, has_yard, self.log)
        return phases.check_p3(d, "Miller's Cottage", self.tnames, has_yard)

    def test_an_unplanned_yard_costs_no_retry(self):
        d = self.cottage()
        d["yard"] = {"props": [{"template": "Oak barrel", "count": 1,
                                "hint": "beside:Miller's Cottage"}]}
        self.assertEqual(self.p3(d), [])
        self.assertIsNone(d["yard"])
        self.assertTrue(any("yard dropped" in why for _what, why in self.log), self.log)

    def test_a_planned_yard_stays_and_its_hints_are_repaired(self):
        d = self.cottage()
        d["yard"] = {"props": [{"template": "Oak barrel", "count": 1,
                                "hint": "beside:Miller's Cottage"}]}
        self.assertEqual(self.p3(d, has_yard=True), [])
        self.assertEqual(d["yard"]["props"][0]["hint"], "")

    def test_a_rule_copied_as_a_hint_costs_no_retry(self):
        d = self.cottage()
        d["furniture"][0]["hint"] = "flush against the back wall of the kitchen"
        self.assertEqual(self.p3(d), [])

    def test_a_good_hint_is_left_alone(self):
        d = self.cottage()
        d["furniture"][0]["hint"] = "wall:north+away_from_door"
        self.p3(d)
        self.assertEqual(d["furniture"][0]["hint"], "wall:north+away_from_door")
        self.assertEqual(self.log, [])

    def test_furniture_inside_the_rooms_is_lifted_out(self):
        d = self.cottage()
        count = len(d["furniture"])
        for r in d["rooms"]:
            r["furniture"] = [dict(f) for f in d["furniture"] if f["room"] == r["name"]]
            for f in r["furniture"]:
                del f["room"]
        d["furniture"] = []
        self.assertEqual(self.p3(d), [])
        self.assertEqual(len(d["furniture"]), count)

    def test_rooms_given_as_bare_names_are_shaped(self):
        d = {"rooms": ["Kitchen", "Bedroom"], "furniture": []}
        phases._repair_rooms(d)
        self.assertEqual([r["name"] for r in d["rooms"]], ["Kitchen", "Bedroom"])
        self.assertEqual(d["rooms"][0]["share"], "medium")

    def test_a_unit_design_is_repaired_as_well(self):
        d = self.cottage()
        d["unit"] = {"rooms": ["Room"], "furniture": [
            {"template": sorted(self.tnames)[0], "room": "Room", "hint": "somewhere nice"}]}
        phases.repair_p3(d, "Miller's Cottage", self.tnames, False, self.log)
        self.assertEqual(d["unit"]["rooms"][0]["name"], "Room")
        self.assertEqual(d["unit"]["furniture"][0]["hint"], "")

    def test_a_retried_reply_logs_a_repair_once(self):
        for _ in range(3):
            d = self.cottage()
            d["yard"] = {"props": []}
            d["yard"]["props"].append({"template": "Oak barrel"})
            self.p3(d)
        self.assertEqual(len(self.log), 1)

    def p1(self, **building):
        return {"zones": [{"name": "Z", "buildings": [dict({"name": "B"}, **building)]}]}

    def test_no_residents_on_a_workplace_means_none_at_all(self):
        d = self.p1(residents=0)
        phases.repair_p1(d, self.log)
        self.assertNotIn("residents", d["zones"][0]["buildings"][0])

    def test_a_unit_building_loses_its_own_residents(self):
        d = self.p1(residents=4, couples=1, units={"name": "Room", "count": 3, "residents": 1})
        phases.repair_p1(d, self.log)
        b = d["zones"][0]["buildings"][0]
        self.assertNotIn("residents", b)
        self.assertNotIn("couples", b)
        self.assertEqual(b["units"]["count"], 3)

    def test_one_copy_with_residents_is_an_ordinary_home(self):
        d = self.p1(residents=5, couples=1, units={"name": "House", "count": 1, "residents": 5})
        phases.repair_p1(d, self.log)
        b = d["zones"][0]["buildings"][0]
        self.assertIsNone(b["units"])
        self.assertEqual((b["residents"], b["couples"]), (5, 1))

    def test_a_single_guest_room_stays_a_unit(self):
        d = self.p1(units={"name": "Room", "count": 1, "residents": 1})
        phases.repair_p1(d, self.log)
        self.assertEqual(d["zones"][0]["buildings"][0]["units"]["count"], 1)

    def test_replies_of_the_wrong_shape_pass_through(self):
        for d in (None, [], "x", {"zones": "x"}, {"zones": [None, {"buildings": [None]}]}):
            phases.repair_p1(d, self.log)
        for d in (None, [], "x"):
            phases.repair_p3(d, "B", self.tnames, False, self.log)
            phases.repair_p4(d, "Z", self.tnames, (), self.log)
            phases.repair_player(d, self.log)

    def test_a_zone_hint_is_repaired(self):
        d = json.loads(json.dumps(CANNED_P4_VILLAGE))
        d["props"][0]["hint"] = "behind:the old mill+by the river"
        phases.repair_p4(d, "Millbrook", self.tnames, {"The Old Mill"}, self.log)
        self.assertEqual(d["props"][0]["hint"], "behind:The Old Mill")
        self.assertEqual(phases.check_p4(d, "Millbrook", self.tnames, {"The Old Mill"}), [])

    def test_a_player_keeps_five_items(self):
        d = {"player": {"inventory": [["A", 1], ["B", 1], ["C", 1], ["D", 1]],
                        "equipment": {"head": "E", "boots": "F"}}}
        phases.repair_player(d, self.log)
        self.assertEqual(len(d["player"]["inventory"]) + len(d["player"]["equipment"]), 5)
        self.assertEqual(d["player"]["equipment"], {"head": "E", "boots": "F"})

    def test_the_catalogue_marks_its_rule_as_a_note(self):
        line = phases._catalogue_lines([{"name": "Hearth", "size": [2, 1], "rule": "by a wall"}])
        self.assertEqual(line, "- Hearth | 2x1 | note: by a wall")


class TestPartners(unittest.TestCase):
    def batch(self):
        cast_data = {"households": [
            {"home": "Cottage", "couples": 1, "members": [
                {"kind": "adult", "role": "fisher", "work": "Docks"},
                {"kind": "adult", "role": "curer", "work": "Shed"},
                {"kind": "child"}]},
            {"home": "Hut", "couples": 0, "members": [
                {"kind": "adult", "role": "mender", "work": "Loft"}]}]}
        return cast.slots_of(cast_data)

    def reply(self):
        return {"npcs": [{"slot": n, "name": name} for n, name in
                         ((1, "Ann"), (2, "Ben"), (3, "Cal"), (4, "Dot"))]}

    def test_the_household_pairs_its_first_adults(self):
        d = self.reply()
        cast.pair_partners(d, self.batch())
        got = {p["name"]: p.get("partner") for p in d["npcs"]}
        self.assertEqual(got, {"Ann": "Ben", "Ben": "Ann", "Cal": None, "Dot": None})

    def test_what_the_model_wrote_is_replaced(self):
        d = self.reply()
        d["npcs"][0]["partner"], d["npcs"][3]["partner"] = "Dot", "Ann"
        d["npcs"][2]["partner"] = ""
        cast.pair_partners(d, self.batch())
        self.assertEqual(d["npcs"][0]["partner"], "Ben")
        self.assertNotIn("partner", d["npcs"][2])
        self.assertNotIn("partner", d["npcs"][3])

    def test_the_result_passes_the_partner_check(self):
        d = self.reply()
        batch = self.batch()
        cast.pair_partners(d, batch)
        self.assertEqual(cast.fill_slots(d, batch), [])
        self.assertEqual(phases._partner_errors(d["npcs"], cast.batch_couples(batch)), [])

    def test_a_missing_slot_leaves_the_pair_unwritten(self):
        d = self.reply()
        del d["npcs"][1]
        cast.pair_partners(d, self.batch())
        self.assertNotIn("partner", d["npcs"][0])

    def test_the_prompt_says_who_the_partners_are(self):
        self.assertIn("slots 1 and 2 are partners", cast.slot_lines(self.batch()))

    def test_replies_of_the_wrong_shape_pass_through(self):
        for d in (None, [], {"npcs": "x"}, {"npcs": [None, "x"]}):
            cast.pair_partners(d, self.batch())


ITEM = {"name": "Bread", "type": "consumable", "quality": "common", "value": 3,
        "description": "A loaf.", "physicalDescription": "A loaf, white background"}


class NoItemsClient(ScriptedClient):
    def call(self, phase, *args, **kw):
        return None if phase == "p2-items" else super().call(phase, *args, **kw)


class TwoCallClient(ScriptedClient):
    """The real call for every phase: the script holds both of P2's replies."""

    def call(self, *args, **kw):
        return llm.Client.call(self, *args, **kw)


def two_call_replies(items_reply):
    replies = canned_replies()
    return replies[:1] + [items_reply] + replies[2:]    # the items replace the bad reply


class TestCatalogueInTwoCalls(unittest.TestCase):
    def test_the_items_call_must_make_items(self):
        self.assertTrue(phases.check_p2_items_reply({"items": []}))
        self.assertTrue(phases.check_p2_items_reply({"templates": []}))
        self.assertTrue(phases.check_p2_items_reply(None))

    def test_a_good_items_reply_passes(self):
        self.assertEqual(phases.check_p2_items_reply(
            {"items": [ITEM], "lootPools": {"Shelf": {"items": ["Bread"]}}}), [])

    def test_both_calls_land_in_one_catalogue(self):
        stock = _dump({"items": [ITEM], "lootPools": {"Larder": {"items": ["Bread"]}}})
        plan, _stats = phases.run_phases("a mill village",
                                         TwoCallClient(two_call_replies(stock)))
        self.assertTrue(plan["templates"])
        self.assertEqual([i["name"] for i in plan["items"]], ["Bread"])
        self.assertEqual(list(plan["lootPools"]), ["Larder"])

    def test_the_catalogue_call_is_told_the_pools(self):
        stock = _dump({"items": [ITEM], "lootPools": {"Larder": {"items": ["Bread"]}}})
        client = TwoCallClient(two_call_replies(stock))
        phases.run_phases("a mill village", client)
        prompts = [m[1]["content"] for m in client.sent]
        self.assertIn("Larder", next(p for p in prompts if "object catalogue" in p))

    def test_a_world_survives_having_no_items(self):
        plan, stats = phases.run_phases("a mill village", NoItemsClient(canned_replies()))
        self.assertEqual(plan["items"], [])
        self.assertTrue(plan["templates"])
        self.assertTrue(any("containers stay empty" in why for _w, why in stats["dropped"]))

    def test_no_catalogue_still_ends_the_run(self):
        client = ScriptedClient(canned_replies()[:1] + ["no json"] * 3)
        with self.assertRaises(phases.PhaseError):
            phases.run_phases("a mill village", client)


if __name__ == "__main__":
    unittest.main()
