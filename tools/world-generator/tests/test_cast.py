"""P1b, the cast: statuses and households decided before P5 names anyone."""
import json
import types
import unittest

import worldgen
from tests.test_013_population import populated_replies
from tests.test_model import (CANNED_COTTAGE, CANNED_P1, CANNED_P5_PLAYER, CANNED_P6A, CANNED_P6B, CANNED_P6C,
                              ScriptedClient, _dump)
from worldgen import cast, phases, questions, schedule
from worldgen import cast as cast_mod
from worldgen import spec_writer


def a_p1():
    return json.loads(json.dumps(CANNED_P1))


def good_cast():
    return {"buildings": [{"name": "The Old Mill", "status": "staffed"},
                          {"name": "Miller's Cottage", "status": "home"}],
            "households": [{"home": "Miller's Cottage", "couples": 0, "members": [
                {"kind": "adult", "role": "miller", "work": "The Old Mill", "sells": True},
                {"kind": "child"}]}]}


def check(d, lo=0, hi=10, strict=False):
    return cast.check_p1b(d, a_p1(), lo, hi, strict)


class Budget(unittest.TestCase):
    def test_zones_add_up_by_kind_and_homes(self):
        p1 = {"zones": [
            {"kind": "village", "buildings": [{"residents": 4}]},
            {"kind": "city block", "buildings": [{"units": {"count": 4, "residents": 2}}]},
            {"kind": "farmstead", "buildings": [{"residents": 2}]},
            {"kind": "harbour", "buildings": [{"name": "Boat Shed"}]},
            {"kind": "forest", "buildings": []}]}
        self.assertEqual(cast.budget(p1), (58, 131 - 11, False))

    def test_a_range_the_user_set_is_firm(self):
        self.assertEqual(cast.budget({"zones": []}, [20, 40]), (20, 40, True))


class Checks(unittest.TestCase):
    def test_a_good_cast_passes(self):
        self.assertEqual(check(good_cast()), [])

    def test_every_building_needs_a_status(self):
        d = good_cast()
        d["buildings"].pop()
        self.assertTrue(any("no status" in e for e in check(d)))

    def test_an_empty_building_says_why(self):
        d = good_cast()
        d["buildings"][0]["status"] = "abandoned"
        d["households"][0]["members"][0]["work"] = "Wheatfields"
        self.assertTrue(any(".why" in e for e in check(d)))

    def test_nobody_works_in_an_abandoned_building(self):
        d = good_cast()
        d["buildings"][0].update(status="abandoned", why="the wheel broke")
        self.assertTrue(any("nobody works there" in e for e in check(d)))

    def test_nobody_lives_in_a_vacant_building(self):
        d = good_cast()
        d["buildings"][1].update(status="vacant", why="they left")
        self.assertTrue(any("nobody lives there" in e for e in check(d)))

    def test_a_staffed_building_needs_a_worker(self):
        d = good_cast()
        d["households"][0]["members"][0]["work"] = "Wheatfields"
        self.assertTrue(any("is staffed but" in e for e in check(d)))

    def test_couples_need_adults(self):
        d = good_cast()
        d["households"][0]["couples"] = 1
        self.assertTrue(any("couples" in e for e in check(d)))

    def test_a_firm_range_binds_both_ways_and_the_budget_only_above(self):
        self.assertTrue(any("must be 5-9" in e for e in check(good_cast(), 5, 9, True)))
        self.assertEqual(check(good_cast(), 5, 9, False), [])
        self.assertTrue(any("the most here is 1" in e for e in check(good_cast(), 0, 1, False)))

    def test_homes_of_only_adults_are_refused_unless_the_world_says_why(self):
        d = good_cast()
        d["households"][0]["members"].pop()
        self.assertTrue(any("children or elders" in e for e in check(d)))
        d["noFamilies"] = "a ship's crew"
        self.assertEqual(check(d), [])


class Sanitize(unittest.TestCase):
    def test_a_missing_status_comes_from_the_plan(self):
        d = good_cast()
        d["buildings"] = []
        p1 = a_p1()
        p1["zones"][0]["buildings"][1]["residents"] = 2
        log = []
        got = cast.sanitize_p1b(d, p1, 10, log)
        self.assertEqual(got["status"], {"The Old Mill": "staffed", "Miller's Cottage": "home"})
        self.assertEqual(len(log), 2)

    def test_work_in_a_shut_building_falls_back_to_home(self):
        d = good_cast()
        d["buildings"][0].update(status="vacant", why="the lease is open")
        got = cast.sanitize_p1b(d, a_p1(), 10, [])
        self.assertEqual(got["households"][0]["members"][0]["work"], "Miller's Cottage")

    def test_a_cast_over_the_top_loses_whole_households(self):
        d = good_cast()
        d["households"].append({"home": "The Old Mill", "members": [{"kind": "elder"}] * 3})
        log = []
        got = cast.sanitize_p1b(d, a_p1(), 3, log)
        self.assertEqual([h["home"] for h in got["households"]], ["Miller's Cottage"])
        self.assertIn("capped", log[0][1])

    def test_nobody_at_all_is_no_cast(self):
        d = good_cast()
        d["households"] = []
        self.assertIsNone(cast.sanitize_p1b(d, a_p1(), 10, []))
        self.assertIsNone(cast.sanitize_p1b("nonsense", a_p1(), 10, []))

    def test_the_cast_rewrites_residents_and_couples(self):
        p1 = a_p1()
        mill, cottage = p1["zones"][0]["buildings"]
        mill["residents"], mill["couples"] = 4, 1
        d = good_cast()
        d["households"][0]["members"].insert(0, {"kind": "adult", "role": "wife", "work": "The Old Mill"})
        d["households"][0]["couples"] = 1
        cast.apply_cast(p1, cast.sanitize_p1b(d, p1, 10, []))
        self.assertNotIn("residents", mill)
        self.assertNotIn("couples", mill)
        self.assertEqual((cottage["residents"], cottage["couples"], cottage["status"]), (3, 1, "home"))


class Slots(unittest.TestCase):
    def houses(self, *sizes):
        return {"households": [{"home": f"Home {i}", "couples": 0,
                                "members": [{"kind": "child"}] * n}
                               for i, n in enumerate(sizes)]}

    def test_a_batch_takes_whole_households(self):
        slots = cast.slots_of(self.houses(4, 4, 4))
        self.assertEqual(len(cast.next_batch(slots, 10)), 8)

    def test_a_big_household_goes_alone(self):
        slots = cast.slots_of(self.houses(12, 2))
        self.assertEqual(len(cast.next_batch(slots, 10)), 12)

    def test_filling_takes_the_facts_from_the_slot(self):
        batch = cast.slots_of({"households": [{"home": "Inn", "members": [
            {"kind": "adult", "role": "cook", "work": "Inn", "shift": "evening", "sells": False},
            {"kind": "child"}]}]})
        d = {"npcs": [{"slot": 1, "role": "made up", "home": "Elsewhere"}, {"slot": 2}]}
        self.assertEqual(cast.fill_slots(d, batch), [])
        cook, child = d["npcs"]
        self.assertEqual((cook["role"], cook["home"], cook["work"], cook["shift"], cook["sells"]),
                         ("cook", "Inn", "Inn", "evening", False))
        self.assertEqual((child["role"], child["work"], child["kind"], child["sells"]),
                         ("child", "Inn", "child", False))

    def test_a_wrong_or_missing_slot_is_an_error(self):
        batch = cast.slots_of(self.houses(2))
        errors = cast.fill_slots({"npcs": [{"slot": 9}, {"slot": 1}, {"slot": 1}]}, batch)
        self.assertEqual(len(errors), 3, errors)


def person(slot, name):
    return {"slot": slot, "name": name, "gender": "female", "description": f"{name} wants more.",
            "physicalDescription": "tall"}


def cast_replies(reply, *batches):
    """p1, p1b, p2, p3 x2 (a cottage with two beds), p4 x2, the P5 replies, the
    player and P6."""
    r = populated_replies(p1=a_p1())
    cottage = json.loads(json.dumps(CANNED_COTTAGE))
    next(f for f in cottage["furniture"] if f["template"] == "Straw bed")["count"] = 2
    return (r[:1] + [_dump(reply)] + r[1:3] + [_dump(cottage)] + r[4:6]
            + [_dump(x) for x in batches] + [_dump(CANNED_P5_PLAYER), _dump(CANNED_P6A),
                                             _dump(CANNED_P6B), _dump(CANNED_P6C)])


class Run(unittest.TestCase):
    def test_people_come_from_the_slots(self):
        client = ScriptedClient(cast_replies(good_cast(), {"npcs": [person(1, "Ada Mill"),
                                                                    person(2, "Wyn Mill")]}))
        plan, stats = phases.run_phases("a mill village", client, cast=True)
        ada, wyn = plan["npcs"]
        self.assertEqual((ada["role"], ada["work"], ada["sells"], ada["kind"]),
                         ("miller", "The Old Mill", True, "adult"))
        self.assertEqual((wyn["work"], wyn["kind"]), ("Miller's Cottage", "child"))
        self.assertNotIn("slot", ada)
        self.assertEqual(plan["zones"][0]["buildings"][1]["residents"], 2)
        self.assertEqual(plan["zones"][0]["buildings"][0]["status"], "staffed")

    def test_no_cast_carries_on_as_before(self):
        replies = populated_replies(p1=a_p1())
        client = ScriptedClient(replies[:1] + ["no", "no", "no"] + replies[1:]
                                + [_dump(CANNED_P6A), _dump(CANNED_P6B), _dump(CANNED_P6C)])
        plan, stats = phases.run_phases("a mill village", client, cast=True)
        self.assertNotIn("cast", plan)
        self.assertTrue(plan["npcs"])
        self.assertTrue(any(k == "cast" for k, _why in stats["dropped"]))

    def test_an_abandoned_building_reaches_the_later_prompts_with_its_story(self):
        d = good_cast()
        d["buildings"][0].update(status="abandoned", why="The wheel broke in the flood.")
        d["households"][0]["members"][0]["work"] = "Wheatfields"
        client = ScriptedClient(cast_replies(d, {"npcs": [person(1, "Ada Mill"), person(2, "Wyn Mill")]}))
        plan, _stats = phases.run_phases("a mill village", client, cast=True)
        prompts = [m["content"] for sent in client.sent for m in sent if m["role"] == "user"]
        p3 = next(p for p in prompts if p.startswith("Design ONE building") and "The Old Mill -" in p)
        self.assertIn("[abandoned, left to rot", p3)
        self.assertIn("The wheel broke in the flood.", p3)
        self.assertNotIn("residents", plan["zones"][0]["buildings"][0])

    def test_a_slot_nobody_fills_is_logged_and_the_world_goes_on(self):
        first = [{"npcs": [person(1, "Ada Mill")]}] * 3         # a call and its two retries
        rest = [{"npcs": [person(9, "Nobody")]}] * 6            # two more calls, all wrong
        client = ScriptedClient(cast_replies(good_cast(), *first, *rest))
        plan, stats = phases.run_phases("a mill village", client, cast=True)
        self.assertEqual([p["name"] for p in plan["npcs"]], ["Ada Mill"])
        self.assertIn(("slot 2", "unfilled: child at Miller's Cottage"), stats["dropped"])

    def test_a_second_batch_picks_up_what_the_first_left(self):
        first = [{"npcs": [person(1, "Ada Mill")]}] * 3
        client = ScriptedClient(cast_replies(good_cast(), *first, {"npcs": [person(2, "Wyn Mill")]}))
        plan, _stats = phases.run_phases("a mill village", client, cast=True)
        self.assertEqual([p["name"] for p in plan["npcs"]], ["Ada Mill", "Wyn Mill"])


class MapDecides(unittest.TestCase):
    def test_it_survives_the_population_check(self):
        self.assertEqual(questions.sanitize_population("map"), "map")
        self.assertEqual(questions.sanitize_population("nonsense"), [20, 40])

    def test_there_is_no_target(self):
        self.assertIsNone(phases.resident_target({"population": "map"}))
        self.assertEqual(phases.resident_target({"population": [20, 40]}), 30)

    def test_the_frame_is_told(self):
        self.assertIn("decided later", phases._population_line("map"))


class Days(unittest.TestCase):
    def test_children_and_elders_stay_home(self):
        from tests.test_sleep import GUEST_ROOM_PLAN
        data = json.loads(json.dumps(GUEST_ROOM_PLAN))
        data["npcs"][0]["kind"] = "child"
        data["npcs"][1]["kind"] = "elder"
        world = worldgen.run(data, seed=1)
        for c in world.characters[:2]:
            roles = {b["role"] for b in c.schedule}
            self.assertEqual(roles, {"sleep", "leisure"}, c.name)
            spots = {b["location"] for b in c.schedule if b["role"] == "leisure"}
            self.assertEqual(len(spots), 1, c.name)

    def test_a_shut_inn_draws_nobody(self):
        from tests.test_sleep import GUEST_ROOM_PLAN
        data = json.loads(json.dumps(GUEST_ROOM_PLAN))
        data["zones"][0]["buildings"][0]["status"] = "vacant"
        world = worldgen.run(data, seed=1)
        self.assertFalse(schedule.is_inn(world.buildings[0]))


class Flats(unittest.TestCase):
    """One flat per household: the cast sizes a home building's copies."""

    def p1(self, status_units=None):
        return {"zones": [{"name": "Close", "buildings": [
            {"name": "Tower", "units": {"name": "Flat", "count": 10, "residents": 2}},
            {"name": "Tower II", "units": {"name": "Flat", "count": 10, "residents": 2}},
            {"name": "Inn", "units": {"name": "Guest Room", "count": 6, "residents": 1}},
        ]}], "compounds": [{"name": "Court", "zone": "Close", "parts": [
            {"building": "Tower"}, {"building": "Tower II", "sameAs": "Tower"}]}]}

    def house(self, home, adults=2, children=0, couples=1):
        return {"home": home, "couples": couples,
                "members": [{"kind": "adult", "role": "r", "work": "Inn"}] * adults
                + [{"kind": "child"}] * children}

    def cast(self, *houses):
        return {"status": {"Tower": "home", "Tower II": "home", "Inn": "staffed"},
                "why": {}, "households": list(houses)}

    def units(self, p1, name):
        return next(b for b in p1["zones"][0]["buildings"] if b["name"] == name)["units"]

    def test_copies_follow_the_households(self):
        p1 = self.p1()
        cast = self.cast(self.house("Tower", 2, 3), self.house("Tower"), self.house("Tower"))
        cast_mod.apply_cast(p1, cast)
        self.assertEqual((self.units(p1, "Tower")["count"], self.units(p1, "Tower")["residents"]),
                         (3, 5))
        self.assertEqual([h["flat"] for h in cast["households"]], [1, 2, 3])

    def test_a_same_as_tower_and_its_owner_take_the_bigger_need(self):
        p1 = self.p1()
        cast = self.cast(self.house("Tower"), self.house("Tower II", 2, 2),
                         self.house("Tower II"), self.house("Tower II"))
        cast_mod.apply_cast(p1, cast)
        for name in ("Tower", "Tower II"):
            self.assertEqual((self.units(p1, name)["count"], self.units(p1, name)["residents"]),
                             (3, 4), name)

    def test_an_inns_guest_rooms_stay_as_planned(self):
        p1 = self.p1()
        cast = self.cast(self.house("Inn", 2, 0))
        cast_mod.apply_cast(p1, cast)
        self.assertEqual(self.units(p1, "Inn")["count"], 6)
        self.assertNotIn("flat", cast["households"][0])

    def test_a_shrunken_tower_drops_a_floor_quota_it_cannot_meet(self):
        p1 = self.p1()
        self.units(p1, "Tower")["perStorey"] = 5
        cast_mod.apply_cast(p1, self.cast(self.house("Tower")))
        self.assertNotIn("perStorey", self.units(p1, "Tower"))

    def test_slots_carry_the_flat_and_show_the_household(self):
        p1 = self.p1()
        cast = self.cast(self.house("Tower", 2, 1), self.house("Tower", 1, 0, couples=0))
        cast_mod.apply_cast(p1, cast)
        slots = cast_mod.slots_of(cast)
        lines = cast_mod.slot_lines(slots)
        self.assertIn("one household, slots 1, 2, 3; 1 pair(s)", lines)
        self.assertIn("home Tower, flat 2", lines)
        d = {"npcs": [{"slot": s["slot"], "name": f"P{s['slot']}"} for s in slots]}
        self.assertEqual(cast_mod.fill_slots(d, slots), [])
        self.assertEqual([p["flat"] for p in d["npcs"]], [1, 1, 1, 2])

    def test_a_batch_owes_every_couple_of_its_households(self):
        cast = self.cast(self.house("Tower"), self.house("Tower"), self.house("Inn", 1, 0, 0))
        self.assertEqual(cast_mod.batch_couples(cast_mod.slots_of(cast)), {"Tower": 2})

    def test_a_lone_adult_left_over_owes_no_couple(self):
        slots = cast_mod.slots_of(self.cast(self.house("Tower")))
        self.assertEqual(cast_mod.batch_couples(slots[:1]), {})

    def test_partners_come_from_one_household(self):
        slots = cast_mod.slots_of(self.cast(self.house("Tower"), self.house("Tower")))
        d = {"npcs": [{"slot": s["slot"], "name": f"P{s['slot']}"} for s in slots]}
        d["npcs"][0]["partner"], d["npcs"][2]["partner"] = "P3", "P1"
        errors = cast_mod.fill_slots(d, slots)
        self.assertTrue(any("two households" in e for e in errors), errors)

    def test_a_household_too_big_for_a_flat_is_refused(self):
        p1 = self.p1()
        reply = {"buildings": [{"name": n, "status": s} for n, s in
                               (("Tower", "home"), ("Tower II", "home"), ("Inn", "staffed"))],
                 "noFamilies": "none",
                 "households": [self.house("Tower", 9, 0, 0), self.house("Inn", 1, 0, 0)]}
        errors = cast_mod.check_p1b(reply, p1, 0, 100, False)
        self.assertTrue(any("split the household" in e for e in errors), errors)

    def test_many_households_fit_a_tower_p1_sized_small(self):
        p1 = self.p1()
        reply = {"buildings": [{"name": n, "status": s} for n, s in
                               (("Tower", "home"), ("Tower II", "home"), ("Inn", "staffed"))],
                 "noFamilies": "none",
                 "households": [self.house("Tower", 2, 2) for _ in range(12)]
                 + [self.house("Inn", 1, 0, 0)]}
        self.assertEqual(cast_mod.check_p1b(reply, p1, 0, 100, False), [])


class Ages(unittest.TestCase):
    """The cast knows who is a child, so the built NPC must look and sound it."""

    def person(self, kind=None, gender="female", role="cook"):
        extras = {"kind": kind} if kind else {}
        return types.SimpleNamespace(gender=gender,
                                     person=types.SimpleNamespace(role=role, extras=extras))

    def test_a_child(self):
        c = self.person("child", role="the cook's daughter")
        self.assertEqual(spec_writer.animation_for(c), "child")
        self.assertEqual(spec_writer.voice_for(c)["age"], ["Child"])

    def test_an_elder(self):
        for gender, sprite in (("female", "old-woman"), ("male", "old-man")):
            c = self.person("elder", gender=gender)
            self.assertEqual(spec_writer.animation_for(c), sprite)
            self.assertEqual(spec_writer.voice_for(c)["age"], ["Senior"])

    def test_an_adult_keeps_their_role(self):
        c = self.person("adult", gender="male", role="noodle cook")
        self.assertEqual(spec_writer.voice_for(c)["age"], ["Adult"])
        self.assertEqual(spec_writer.animation_for(c),
                         spec_writer.animation_for(self.person(gender="male", role="noodle cook")))


class TestEstimate(unittest.TestCase):
    def test_a_cast_adds_its_call_and_one_people_call_per_ten(self):
        from worldgen import api
        plan = {"zones": [{"name": "Z", "buildings": [{"name": "Flats"}]}]}
        plain = api.estimate(plan)["calls"]
        plan["cast"] = {"households": [{"home": "Flats",
                                        "members": [{"kind": "adult"}] * 25}]}
        e = api.estimate(plan)
        self.assertEqual(e["calls"], plain + 1 + 2)     # P1b, then 3 calls not 1
        self.assertIn("P1b", e["basis"])


if __name__ == "__main__":
    unittest.main()
