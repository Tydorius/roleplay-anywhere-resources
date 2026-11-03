"""Brief 013 change 3: the population carried through the plan - P1's
resident target and building cap, P3 bedding what P1 promised, P5 batching
with a roster and the player in a call of their own. All mocked."""
import json
import unittest

from tests.test_model import (CANNED_COTTAGE, CANNED_MILL, CANNED_P1,
                              CANNED_P4_FIELDS, CANNED_P4_VILLAGE,
                              CANNED_P5_BATCH, CANNED_P5_PLAYER,
                              CANNED_TEMPLATES, ScriptedClient, canned_replies)
from tests.test_013_frame import a_frame
from worldgen import phases
from worldgen.phases import building_cap, check_p1, check_p3, check_p5


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


def populated_p1(residents=True):
    """The canned P1 with homes whose residents its designs can bed (the
    mill and the cottage each hold one Straw bed)."""
    d = json.loads(json.dumps(CANNED_P1))
    if residents:
        d["zones"][0]["buildings"][0]["residents"] = 1
        d["zones"][0]["buildings"][1]["residents"] = 1
    return d


def populated_replies(p1=None, batch=None, player=None):
    return [
        _dump(p1 or populated_p1()),
        _dump({"templates": CANNED_TEMPLATES}),
        _dump(CANNED_MILL),
        _dump(CANNED_COTTAGE),
        _dump(CANNED_P4_VILLAGE),
        _dump(CANNED_P4_FIELDS),
        _dump(batch if batch is not None else CANNED_P5_BATCH),
        _dump(player if player is not None else CANNED_P5_PLAYER),
    ]


class TestBuildingCap(unittest.TestCase):
    def test_no_population_keeps_yesterdays_caps(self):
        self.assertEqual(building_cap(None), 12)
        self.assertEqual(building_cap(None, compounds=True), 16)

    def test_the_cap_grows_with_the_resident_target(self):
        self.assertEqual(building_cap(20), 19)
        self.assertEqual(building_cap(30), 22)
        self.assertEqual(building_cap(200), 28, "the ceiling holds")
        self.assertEqual(building_cap(30, compounds=True), 26)

    def test_check_p1_names_the_new_cap(self):
        d = json.loads(json.dumps(CANNED_P1))
        for i in range(25):
            d["zones"][0]["buildings"].append(
                {"name": f"Hut {i}", "kind": "hut", "sizeClass": "hut",
                 "purpose": "x", "yard": None})
        errors = check_p1(d, residents=30)
        self.assertTrue(any("at most 22" in e for e in errors), errors)
        errors = check_p1(d)
        self.assertTrue(any("at most 12" in e for e in errors), errors)

    def test_residents_field_is_validated(self):
        d = populated_p1()
        d["zones"][0]["buildings"][0]["residents"] = "many"
        errors = check_p1(d)
        self.assertTrue(any("residents" in e for e in errors), errors)
        d["zones"][0]["buildings"][0]["residents"] = 2
        d["zones"][0]["buildings"][0]["units"] = {"name": "Room", "count": 4,
                                                  "residents": 1}
        errors = check_p1(d)
        self.assertTrue(any("residents not needed" in e for e in errors), errors)

    def test_couples_field_is_validated(self):
        d = populated_p1()                       # the mill and cottage: 1 resident each
        d["zones"][0]["buildings"][0]["residents"] = 4
        d["zones"][0]["buildings"][0]["couples"] = 1
        self.assertFalse(any("couples" in e for e in check_p1(d)))
        d["zones"][0]["buildings"][0]["couples"] = 3   # more than half the residents
        errors = check_p1(d)
        self.assertTrue(any("couple(s) need 6" in e for e in errors), errors)
        d["zones"][0]["buildings"][0]["couples"] = "two"
        errors = check_p1(d)
        self.assertTrue(any("couples must be a whole number" in e for e in errors),
                        errors)
        d["zones"][0]["buildings"][0].pop("residents")
        d["zones"][0]["buildings"][0]["couples"] = 1
        errors = check_p1(d)
        self.assertTrue(any("couples needs residents" in e for e in errors), errors)
        d["zones"][0]["buildings"][0]["residents"] = 4
        d["zones"][0]["buildings"][0]["units"] = {"name": "Room", "count": 4,
                                                  "residents": 1}
        errors = check_p1(d)
        self.assertTrue(any("couples not needed" in e for e in errors), errors)

    def test_bad_couples_dropped_with_a_log_line(self):
        from worldgen.phases import sanitize_p1
        d = populated_p1()
        mill = d["zones"][0]["buildings"][0]
        mill["residents"] = 4
        mill["couples"] = 1
        log = []
        sanitize_p1(d, log)
        self.assertEqual(log, [])          # a fitting couple survives
        mill["couples"] = 3                # only four residents
        log = []
        sanitize_p1(d, log)
        self.assertNotIn("couples", mill)
        self.assertTrue(any("couples" in w + r for (w, r) in log), log)


class TestP3Beds(unittest.TestCase):
    def setUp(self):
        from worldgen.model import bed_capacity
        self.tnames = {t["name"] for t in CANNED_TEMPLATES}
        self.beds = {t["name"]: bed_capacity(tuple(t["size"]))
                     for t in CANNED_TEMPLATES if "bed" in t["name"].lower()}

    def test_fewer_beds_than_residents_is_an_error(self):
        d = json.loads(json.dumps(CANNED_MILL))   # one Straw bed
        errors = check_p3(d, "The Old Mill", self.tnames, True,
                          beds=self.beds, residents=3)
        self.assertTrue(any("beds only 1" in e for e in errors), errors)
        errors = check_p3(d, "The Old Mill", self.tnames, True,
                          beds=self.beds, residents=1)
        self.assertEqual(errors, [])

    def test_design_beds_counts_a_double_as_two(self):
        from worldgen.phases import design_beds
        beds = {"Straw bed": 1, "Oak double bed": 2}
        design = {"furniture": [
            {"template": "Straw bed", "room": "R", "count": 2, "hint": "wall:north"},
            {"template": "Oak double bed", "room": "R", "count": 1, "hint": "wall:north"},
            {"template": "Trestle table", "room": "R", "count": 1, "hint": "center"}],
            "upper": [{"furniture": [
                {"template": "Oak double bed", "room": "U", "count": 1,
                 "hint": "wall:north"}]}]}
        # 2 singles + a double downstairs (4) and a double up (2)
        self.assertEqual(design_beds(design, beds), 6)

    def test_four_residents_pass_with_one_double_and_two_singles(self):
        d = json.loads(json.dumps(CANNED_COTTAGE))   # already one Straw bed
        tnames = self.tnames | {"Oak double bed"}
        beds = dict(self.beds)
        beds["Oak double bed"] = 2
        d["furniture"] += [
            {"template": "Straw bed", "room": "Sleeping Loft", "count": 1,
             "hint": "wall:west"},
            {"template": "Oak double bed", "room": "Sleeping Loft", "count": 1,
             "hint": "wall:north"}]
        errors = check_p3(d, "Miller's Cottage", tnames, False,
                          beds=beds, residents=4)
        self.assertEqual(errors, [])
        # the same design fails a couple: one double is there, two are not
        errors = check_p3(d, "Miller's Cottage", tnames, False,
                          beds=beds, residents=4, couples=2)
        self.assertTrue(any("holds only 1 double bed" in e for e in errors), errors)
        errors = check_p3(d, "Miller's Cottage", tnames, False,
                          beds=beds, residents=4, couples=1)
        self.assertEqual(errors, [])

    def test_the_building_line_and_prompt_carry_the_couples(self):
        p1 = populated_p1()
        cottage = p1["zones"][0]["buildings"][1]
        cottage["residents"] = 2
        cottage["couples"] = 1
        templates = CANNED_TEMPLATES + [
            {"name": "Double bed", "size": [2, 2], "walkability": 0.3,
             "forSleep": True, "tags": ["bed"], "description": "A double bed.",
             "physicalDescription": "wide wooden bed frame",
             "rule": "against the wall of a sleeping room"}]
        cottage_design = json.loads(json.dumps(CANNED_COTTAGE))
        cottage_design["furniture"].append(
            {"template": "Double bed", "room": "Sleeping Loft", "count": 1,
             "hint": "wall:north"})
        replies = populated_replies(p1=p1)
        replies[1] = _dump({"templates": templates})
        replies[3] = _dump(cottage_design)
        client = ScriptedClient(replies)
        plan, _stats = phases.run_phases("a mill village", client)
        cottage_prompt = client.sent[3][1]["content"]
        self.assertIn("1 couple(s) sharing a double bed", cottage_prompt)
        kept = next(b for z in plan["zones"] for b in z["buildings"]
                    if b["name"] == "Miller's Cottage")
        self.assertEqual(kept.get("couples"), 1)

    def test_run_phases_lowers_the_p1_residents_to_the_beds(self):
        # the mill promises 3 sleepers but its furniture beds one; the model
        # never fixes it (two garbage retries), so the last parsed design
        # stands and the P1 residents fall to its bed count
        p1 = populated_p1()
        p1["zones"][0]["buildings"][0]["residents"] = 3
        replies = populated_replies(p1=p1)
        replies[2:3] = [_dump(CANNED_MILL), "nope", "still nope"]
        client = ScriptedClient(replies)
        plan, stats = phases.run_phases("a mill village", client)
        mill = next(b for z in plan["zones"] for b in z["buildings"]
                    if b["name"] == "The Old Mill")
        self.assertEqual(mill["residents"], 1, "the mill's furniture beds one")
        dropped = [r for _w, r in stats["dropped"] if "residents 3 -> 1" in r]
        self.assertTrue(dropped, stats["dropped"])


class TestP5Batches(unittest.TestCase):
    def test_one_call_per_peopled_zone_then_the_player(self):
        client = ScriptedClient(canned_replies())
        plan, _stats = phases.run_phases("a mill village", client)
        self.assertEqual(client.calls, 11)
        self.assertEqual(len(plan["npcs"]), 5)
        self.assertEqual(plan["player"]["name"], "Wren Ash")
        # sent[1] is P2's first (bad) attempt: P1, P2, P2-retry, P3 x2, P4 x2,
        # then the batch and the player
        batch_prompt = client.sent[7][1]["content"]
        self.assertIn("one batch", batch_prompt)
        self.assertIn("spots free", batch_prompt)
        player_prompt = client.sent[8][1]["content"]
        self.assertIn("ROLE:", player_prompt)
        self.assertIn("outsider with a reason to stay", player_prompt,
                      "no frame: the default role wording")

    def test_a_stray_player_in_a_batch_is_an_error(self):
        d = json.loads(json.dumps(CANNED_P5_BATCH))
        d["player"] = CANNED_P5_PLAYER["player"]
        errors = check_p5(d, {"The Old Mill"}, {"Millbrook"}, need=("npcs",))
        self.assertTrue(any("player is made in its own call" in e for e in errors),
                        errors)

    def test_roster_names_may_not_repeat(self):
        d = json.loads(json.dumps(CANNED_P5_BATCH))
        errors = check_p5(d, {"The Old Mill", "Miller's Cottage"},
                          {"Millbrook"}, need=("npcs",),
                          roster={"Aldous Miller"})
        self.assertTrue(any("already on the roster" in e for e in errors), errors)

    def test_a_home_without_a_bed_is_an_error(self):
        # the bakery has no bed: nobody may sleep there
        d = json.loads(json.dumps(CANNED_P5_BATCH))
        d["npcs"][0]["home"] = "The Bakehouse"
        errors = check_p5(d, {"The Bakehouse", "The Old Mill", "Miller's Cottage"},
                          {"Millbrook"}, bedded={"The Old Mill", "Miller's Cottage"},
                          need=("npcs",))
        self.assertTrue(any("has no bed" in e for e in errors), errors)

    def test_batch_is_capped_at_ten(self):
        people = [dict(p, name=f"Person {i}") for i, p in enumerate(CANNED_P5_BATCH["npcs"] * 6)]
        client = ScriptedClient(populated_replies(batch={"npcs": people[:12]}))
        plan, stats = phases.run_phases("a mill village", client)
        self.assertEqual(len(plan["npcs"]), 10)
        self.assertTrue(any("capped at 10" in r for _w, r in stats["dropped"]),
                        stats["dropped"])

    def test_below_the_range_tops_up_rather_than_failing(self):
        more = {"npcs": [dict(p, name=p["name"] + " II") for p in CANNED_P5_BATCH["npcs"]]}
        # top-ups run after the zone batches and BEFORE the player's own call
        replies = [_dump(a_frame())] + populated_replies()
        replies.insert(-1, _dump(more))     # between the batch and the player
        client = ScriptedClient(replies)
        plan, stats = phases.run_phases(
            "a mill village", client,
            questionnaire={"mode": "short", "answers": {}, "population": [20, 40]})
        # P0 + P1..P4 + the batch + one top-up batch + the player (then the
        # queue runs dry on top-up 2: still short, logged, never fatal)
        self.assertGreaterEqual(client.calls, 10)
        self.assertEqual(len(plan["npcs"]), 10)
        self.assertEqual(plan["frame"]["genre"]["primary"], "Fantasy")
        self.assertTrue(any("below the asked-for" in r for _w, r in stats["dropped"]),
                        stats["dropped"])

    def test_the_player_carries_starting_items(self):
        items = [{"name": "Walking staff", "type": "wieldable", "quality": "common",
                  "value": 2, "description": "A staff.",
                  "physicalDescription": "A worn staff, white background"},
                 {"name": "Rain cloak", "type": "torso", "quality": "common",
                  "value": 3, "description": "A cloak.",
                  "physicalDescription": "Oiled cloak, white background"},
                 {"name": "Ledger", "type": "misc", "quality": "common",
                  "value": 4, "description": "A ledger.",
                  "physicalDescription": "A thick ledger, white background"}]
        replies = populated_replies()
        replies[1] = _dump({"templates": CANNED_TEMPLATES, "items": items})
        player = json.loads(json.dumps(CANNED_P5_PLAYER))
        player["player"]["inventory"] = [["Rain cloak", 1], ["Ledger", 1]]
        player["player"]["equipment"] = {"weapon": "Walking staff"}
        replies[7] = _dump(player)
        client = ScriptedClient(replies)
        plan, _stats = phases.run_phases("a mill village", client)
        self.assertEqual(plan["player"]["inventory"], [["Rain cloak", 1], ["Ledger", 1]])
        # "weapon" is no game slot: it maps to wieldable1 (see test_player_slots)
        self.assertEqual(plan["player"]["equipment"], {"wieldable1": "Walking staff"})

    def test_player_items_must_be_real_and_two_to_five(self):
        p = dict(CANNED_P5_PLAYER["player"], inventory=[["Ghost item", 1]])
        errors = check_p5({"player": p}, set(), set(), items={"Rain cloak"},
                          need=("player",))
        self.assertTrue(any("not an item of this catalogue" in e for e in errors),
                        errors)
        p2 = dict(CANNED_P5_PLAYER["player"], inventory=[["Rain cloak", 1]])
        errors = check_p5({"player": p2}, set(), set(), items={"Rain cloak"},
                          need=("player",))
        self.assertTrue(any("carry 2-5" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()


class TestP5Partners(unittest.TestCase):
    """P5 writes each couple as a mutual same-home partner pair; the plan
    keeps the links and the layout seats each pair together."""

    DOUBLE = {"name": "Double bed", "size": [2, 2], "walkability": 0.3,
              "forSleep": True, "tags": ["bed"], "description": "A double bed.",
              "physicalDescription": "wide wooden bed frame",
              "rule": "against the wall of a sleeping room"}

    def _pair_reply(self):
        d = json.loads(json.dumps(CANNED_P5_BATCH))
        berta = next(p for p in d["npcs"] if p["name"] == "Berta Miller")
        colin = next(p for p in d["npcs"] if p["name"] == "Colin Miller")
        return d, berta, colin

    def test_a_mutual_same_home_pair_passes(self):
        d, berta, colin = self._pair_reply()
        berta["partner"] = colin["name"]
        colin["partner"] = berta["name"]
        errors = check_p5(d, {"The Old Mill", "Miller's Cottage"},
                          {"Millbrook", "Wheatfields"},
                          need=("npcs",),
                          couples={"Miller's Cottage": 1})
        self.assertEqual(errors, [])

    def test_a_batch_owes_only_its_own_homes_couples(self):
        """P5 runs one batch per zone: a couple promised to a home in another
        zone is not this batch's to write."""
        d, berta, colin = self._pair_reply()
        berta["partner"] = colin["name"]
        colin["partner"] = berta["name"]
        errors = check_p5(d, {"The Old Mill", "Miller's Cottage"},
                          {"Millbrook", "Wheatfields"},
                          need=("npcs",),
                          couples={"Miller's Cottage": 1, "Fen House": 1})
        self.assertEqual(errors, [])

    def test_a_partner_in_another_home_is_caught(self):
        d, berta, colin = self._pair_reply()
        berta["home"] = "Miller's Cottage"
        colin["home"] = "The Old Mill"
        berta["partner"] = colin["name"]
        colin["partner"] = berta["name"]
        errors = check_p5(d, {"The Old Mill", "Miller's Cottage"},
                          {"Millbrook", "Wheatfields"},
                          need=("npcs",),
                          couples={"The Old Mill": 1, "Miller's Cottage": 1})
        self.assertTrue(any("lives in" in e for e in errors), errors)

    def test_a_one_sided_partner_is_caught(self):
        d, berta, colin = self._pair_reply()
        berta["partner"] = colin["name"]   # Colin never answers
        errors = check_p5(d, {"The Old Mill", "Miller's Cottage"},
                          {"Millbrook", "Wheatfields"},
                          need=("npcs",), couples={"Miller's Cottage": 1})
        self.assertTrue(any("does not name them back" in e for e in errors), errors)
        self.assertTrue(any("gives 0 whole partner pair" in e for e in errors),
                        errors)

    def test_a_mismatched_pair_is_dropped_rather_than_failing_the_batch(self):
        from worldgen.phases import sanitize_p5
        d, berta, colin = self._pair_reply()
        berta["partner"] = colin["name"]   # one-sided: dropped at sanitize
        log = []
        sanitize_p5(d, ["The Old Mill", "Miller's Cottage"],
                    ["Millbrook", "Wheatfields"], log,
                    need=("npcs",), couples={"Miller's Cottage": 1})
        self.assertEqual(len(d["npcs"]), 5, "the people stay; only the link goes")
        self.assertTrue(all("partner" not in p for p in d["npcs"]))
        self.assertTrue(any("partner" in w + r for (w, r) in log), log)

    def test_partners_share_the_double_room_and_the_child_the_other(self):
        import worldgen
        p1 = populated_p1()
        cottage = p1["zones"][0]["buildings"][1]
        cottage["residents"] = 3
        cottage["couples"] = 1
        design = json.loads(json.dumps(CANNED_COTTAGE))
        design["rooms"].append({"name": "Child's Room", "share": "small",
                                "purpose": "the child's bed"})
        design["connections"].append(["Main Room", "Child's Room"])
        design["furniture"] += [
            {"template": "Double bed", "room": "Sleeping Loft", "count": 1,
             "hint": "wall:north"},
            {"template": "Straw bed", "room": "Child's Room", "count": 1,
             "hint": "wall:north"}]
        batch, berta, colin = self._pair_reply()
        berta["partner"] = colin["name"]
        colin["partner"] = berta["name"]
        # the child sits between the partners in the roster, so only the
        # partner links - not the order - can pair Berta with Colin
        batch["npcs"].sort(key=lambda p: ["Aldous Miller", "Berta Miller",
                                          "Edda Straw", "Colin Miller",
                                          "Daria Wick"].index(p["name"]))
        replies = populated_replies(p1=p1, batch=batch)
        replies[1] = _dump({"templates": CANNED_TEMPLATES + [self.DOUBLE]})
        replies[3] = _dump(design)
        client = ScriptedClient(replies)
        plan, _stats = phases.run_phases("a mill village", client)
        by_name = {p["name"]: p for p in plan["npcs"]}
        self.assertEqual(by_name["Berta Miller"]["partner"], "Colin Miller")
        self.assertEqual(by_name["Colin Miller"]["partner"], "Berta Miller")
        world = worldgen.run(plan, seed=1)
        locs = {}
        for c in world.characters:
            locs[c.name] = next(b["location"] for b in c.schedule
                                if b["role"] == "sleep")
        self.assertEqual(locs["Berta Miller"], "Miller's Cottage Sleeping Loft")
        self.assertEqual(locs["Colin Miller"], "Miller's Cottage Sleeping Loft")
        self.assertEqual(locs["Edda Straw"], "Miller's Cottage Child's Room")
        # the scenario format has no relationship field: partner stays in the
        # plan, never in the spec
        spec = worldgen.build_spec(world, plan)
        for ent in spec["npcs"]:
            self.assertNotIn("partner", ent)


class TestPlanKeepsP1Layout(unittest.TestCase):
    """The first live 013 run planned a castle enclosure and a cotter row in
    P1, passed validation, and shipped neither: run_phases never copied
    `compounds` into the plan. The fixtures write compounds by hand, so only
    the full phase run can catch this."""

    def test_compounds_survive_into_the_plan(self):
        p1 = populated_p1()
        p1["compounds"] = [{
            "name": "Mill Row", "zone": "Millbrook", "shape": "row",
            "frontage": "south", "front": "none",
            "parts": [{"building": "The Old Mill", "at": "row:0"},
                      {"building": "Miller's Cottage", "at": "row:1"}]}]
        client = ScriptedClient(populated_replies(p1=p1))
        plan, stats = phases.run_phases("a mill village", client)
        self.assertEqual([c["name"] for c in plan.get("compounds", [])], ["Mill Row"],
                         stats["dropped"])
