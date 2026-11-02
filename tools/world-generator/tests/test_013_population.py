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


class TestP3Beds(unittest.TestCase):
    def setUp(self):
        self.tnames = {t["name"] for t in CANNED_TEMPLATES}
        self.beds = {t["name"] for t in CANNED_TEMPLATES if "bed" in t["name"].lower()}

    def test_fewer_beds_than_residents_is_an_error(self):
        d = json.loads(json.dumps(CANNED_MILL))   # one Straw bed
        errors = check_p3(d, "The Old Mill", self.tnames, True,
                          beds=self.beds, residents=3)
        self.assertTrue(any("beds only 1" in e for e in errors), errors)
        errors = check_p3(d, "The Old Mill", self.tnames, True,
                          beds=self.beds, residents=1)
        self.assertEqual(errors, [])

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
        self.assertEqual(client.calls, 8)
        self.assertEqual(len(plan["npcs"]), 5)
        self.assertEqual(plan["player"]["name"], "Wren Ash")
        # sent[1] is P2's first (bad) attempt: P1, P2, P2-retry, P3 x2, P4 x2,
        # then the batch and the player
        batch_prompt = client.sent[7][1]["content"]
        self.assertIn("one batch", batch_prompt)
        self.assertIn("bed(s)", batch_prompt)
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
        self.assertEqual(plan["player"]["equipment"], {"weapon": "Walking staff"})

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
