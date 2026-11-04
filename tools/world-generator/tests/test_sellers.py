"""Who sells: the plan's word, a trade in the role, or running a shop."""
import json
import os
import tempfile
import unittest

import worldgen
from worldgen import api
from worldgen.schedule import is_inn
from worldgen.sellers import sellers
from worldgen.spec_writer import build_spec
from tests.test_sleep import GUEST_ROOM_PLAN


def world_of(*people, kind="shop", purpose="the corner shop"):
    data = json.loads(json.dumps(GUEST_ROOM_PLAN))
    for z in data["zones"]:
        for b in z["buildings"]:
            if b["name"] == "The Green Ox":
                b["kind"], b["purpose"] = kind, purpose
    base = data["npcs"][0]
    data["npcs"] = [dict(base, name=f"Person {i}", role=role, work=work, **extra)
                    for i, (role, work, extra) in enumerate(people)]
    return data


def names(data):
    return sellers(worldgen.run(data, seed=1))


class Trades(unittest.TestCase):
    def sold(self, role):
        return "Person 0" in names(world_of((role, "", {}), kind="cottage", purpose="a home"))

    def test_trades_sell(self):
        for role in ("baker", "Village Blacksmith", "smith at Aldford Smithy", "innkeeper of the Hart",
                     "skewer vendor on Neon Row", "herb-wife", "pharmacist at Mao's", "shopkeeper",
                     "bartender and rumor-broker", "fishmonger", "bookseller", "merchant"):
            self.assertTrue(self.sold(role), role)

    def test_other_work_does_not(self):
        for role in ("farmer", "captain", "gatekeeper", "ration bookkeeper", "orchard keeper",
                     "shepherd", "priest", "stockman of the Great Barn"):
            self.assertFalse(self.sold(role), role)

    def test_apprentices_and_relations_do_not(self):
        for role in ("apprentice smith", "dye apprentice", "miller's wife", "baker's boy"):
            self.assertFalse(self.sold(role), role)


class Shops(unittest.TestCase):
    def test_a_shop_gets_someone_to_sell(self):
        got = names(world_of(("night cook", "The Green Ox", {})))
        self.assertEqual(got, {"Person 0"})

    def test_the_owner_comes_before_the_staff(self):
        got = names(world_of(("clerk", "The Green Ox", {}), ("owner-cook", "The Green Ox", {}),
                             ("apprentice clerk", "The Green Ox", {})))
        self.assertEqual(got, {"Person 1"})

    def test_staff_come_before_apprentices(self):
        got = names(world_of(("apprentice clerk", "The Green Ox", {}), ("clerk", "The Green Ox", {})))
        self.assertEqual(got, {"Person 1"})

    def test_a_shop_with_a_trade_needs_nobody_else(self):
        got = names(world_of(("baker", "The Green Ox", {}), ("clerk", "The Green Ox", {})))
        self.assertEqual(got, {"Person 0"})

    def test_a_workshop_and_a_cottage_are_not_shops(self):
        for kind in ("workshop", "cottage", "barracks"):
            got = names(world_of(("clerk", "The Green Ox", {}), kind=kind, purpose="work"))
            self.assertEqual(got, set(), kind)

    def test_a_purpose_that_sells_makes_a_shop(self):
        got = names(world_of(("clerk", "The Green Ox", {}), kind="barn",
                             purpose="selling salt and thread"))
        self.assertEqual(got, {"Person 0"})


class PlanDecides(unittest.TestCase):
    def test_true_needs_no_trade(self):
        got = names(world_of(("farmer", "", {"sells": True}), kind="cottage", purpose="a home"))
        self.assertEqual(got, {"Person 0"})

    def test_false_beats_the_trade(self):
        got = names(world_of(("baker", "", {"sells": False}), kind="cottage", purpose="a home"))
        self.assertEqual(got, set())

    def test_false_leaves_the_counter_to_someone_else(self):
        got = names(world_of(("owner", "The Green Ox", {"sells": False}), ("clerk", "The Green Ox", {})))
        self.assertEqual(got, {"Person 1"})

    def test_everyone_refusing_leaves_the_shop_without_a_seller(self):
        self.assertEqual(names(world_of(("clerk", "The Green Ox", {"sells": False}))), set())


class Written(unittest.TestCase):
    def test_a_seller_is_a_merchant_in_the_scenario(self):
        data = world_of(("baker", "", {}), ("farmer", "", {}), kind="cottage", purpose="a home")
        with tempfile.TemporaryDirectory() as tmp:
            out = api._layout_and_build(data, seed=1, out_dir=os.path.join(tmp, "w"))
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["validator_errors"], 0, out)
            path = next(os.path.join(r, "scenario.json") for r, _d, f in os.walk(tmp)
                        if "scenario.json" in f)
            with open(path, encoding="utf-8") as fh:
                people = {e["name"]: e for e in json.load(fh)["entities"]
                          if e.get("type") == "npc"}
        self.assertEqual(people["Person 0"].get("merchant"), {})
        self.assertNotIn("merchant", people["Person 1"])

    def test_the_player_never_sells(self):
        data = world_of(("baker", "", {}), kind="cottage", purpose="a home")
        data["player"]["role"] = "travelling merchant"
        data["player"]["sells"] = True
        data["player"]["work"] = "The Green Ox"
        world = worldgen.run(data, seed=1)
        self.assertNotIn(data["player"]["name"], sellers(world))


class Inns(unittest.TestCase):
    def test_the_kind_decides_what_is_an_inn(self):
        class D:
            def __init__(self, kind, purpose):
                self.kind, self.purpose, self.status = kind, purpose, ""

        class B:
            def __init__(self, kind, purpose):
                self.layout = type("L", (), {"design": D(kind, purpose)})

        self.assertTrue(is_inn(B("inn", "beds")))
        self.assertTrue(is_inn(B("", "the village inn")))
        self.assertFalse(is_inn(B("cottage", "quarters of the couple who keep the inn")))


if __name__ == "__main__":
    unittest.main()
