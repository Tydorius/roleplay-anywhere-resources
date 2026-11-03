"""Model-half tests, all mocked: JSON extraction, contract checks, retries
and a canned five-phase transcript that must produce a plan.json the
deterministic layout accepts. No network, no providers.json needed."""
import json
import os
import tempfile
import unittest

import worldgen
from worldgen import llm, phases


# ------------------------------------------------------------------ stubs

class ScriptedClient(llm.Client):
    """A Client whose transport pops scripted raw replies, in call order.
    Everything else (parsing, contract retries, logging, stats) is the real
    Client machinery."""

    def __init__(self, replies):
        self.provider = "stub"
        self.model = "stub-model"
        self.max_tokens = 16
        self.base_url = "http://stub"
        self._api_key = "stub-secret"
        self.log_dir = None
        self.calls = 0
        self.retries = 0
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.seconds = 0.0
        self._queue = list(replies)
        self.sent = []

    def _request(self, messages, max_tokens=None):
        self.sent.append([dict(m) for m in messages])
        usage = {"prompt": 10, "completion": 5, "total": 15}
        if not self._queue:
            raise llm.LLMError("scripted queue is empty")
        return self._queue.pop(0), usage


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


# ------------------------------------------------------- a canned world

CANNED_P1 = {
    "name": "Millbrook",
    "worldBackground": "A mill village of thirty souls; the wheel turns when the river lets it.",
    "setting": {"era": "medieval", "technology": "water and wood",
                "density": "sparse", "climate": "temperate"},
    "mapSize": "small",
    "zones": [
        {"name": "Millbrook", "kind": "village", "sizeClass": "medium",
         "description": "The mill, a cottage and the green between them.",
         "ground": "grass", "adjacentTo": ["Wheatfields"],
         "outdoor": ["village well"],
         "buildings": [
             {"name": "The Old Mill", "kind": "mill", "sizeClass": "medium",
              "purpose": "grinding the village grain",
              "yard": {"kind": "millyard", "side": "front"}},
             {"name": "Miller's Cottage", "kind": "cottage", "sizeClass": "small",
              "purpose": "the miller's home", "yard": None},
         ]},
        {"name": "Wheatfields", "kind": "farmland", "sizeClass": "large",
         "description": "Wheat in strips, scarecrows at the corners.",
         "ground": "dirt", "adjacentTo": ["Millbrook"],
         "outdoor": ["scarecrows"], "buildings": []},
    ],
    "roads": [{"from": "Millbrook", "to": "Wheatfields", "kind": "dirt"}],
}

CANNED_TEMPLATES = [
    {"name": "Straw bed", "size": [1, 2], "walkability": 0, "tags": ["bed"],
     "description": "A straw bed.", "physicalDescription": "wooden frame, straw mattress",
     "rule": "along the wall of a sleeping room"},
    {"name": "Trestle table", "size": [2, 1], "walkability": 0, "tags": ["table"],
     "description": "A trestle table.", "physicalDescription": "plank table on trestles",
     "rule": "in the middle of the room"},
    {"name": "Wooden stool", "size": [1, 1], "walkability": 0, "tags": ["chair"],
     "description": "A stool.", "physicalDescription": "three-legged stool",
     "rule": "around the tables"},
    {"name": "Clay hearth", "size": [2, 1], "walkability": 0, "tags": ["light", "food"],
     "description": "The hearth.", "physicalDescription": "clay hearth with iron pot",
     "rule": "against a wall, away from the door"},
    {"name": "Oak barrel", "size": [1, 1], "walkability": 0, "tags": ["storage"],
     "description": "An oak barrel.", "physicalDescription": "wooden barrel, iron hoops",
     "rule": "in corners"},
    {"name": "Village well", "size": [2, 2], "walkability": 0, "tags": ["landmark"],
     "description": "The well.", "physicalDescription": "stone well with windlass",
     "rule": "one public well in the open centre of the village"},
    {"name": "Wheat row", "size": [3, 1], "walkability": 0.6, "tags": ["plant"],
     "description": "A row of stooks.", "physicalDescription": "golden wheat stooks",
     "rule": "in long rows across the open fields"},
    {"name": "Scarecrow", "size": [1, 1], "walkability": 0, "tags": ["filler"],
     "description": "A scarecrow.", "physicalDescription": "ragged scarecrow on poles",
     "rule": "standing watch in the fields"},
    {"name": "Oak tree", "size": [2, 2], "walkability": 0, "tags": ["plant", "filler"],
     "description": "An oak.", "physicalDescription": "broad oak seen from above",
     "rule": "at the village edges, off paths"},
]

CANNED_MILL = {
    "name": "The Old Mill", "wall": "wood", "ground": "wood",
    "rooms": [
        {"name": "Mill Floor", "share": "large", "purpose": "the wheel, the stones, the sacks"},
        {"name": "Granary", "share": "small", "purpose": "counted sacks and bins"},
    ],
    "connections": [["Mill Floor", "Granary"]],
    "entrance": {"room": "Mill Floor", "side": "south"},
    "furniture": [
        {"template": "Trestle table", "room": "Mill Floor", "count": 1, "hint": "center"},
        {"template": "Wooden stool", "room": "Mill Floor", "count": 2, "hint": "around:Trestle table"},
        {"template": "Clay hearth", "room": "Mill Floor", "count": 1, "hint": "wall:north"},
        {"template": "Straw bed", "room": "Mill Floor", "count": 1, "hint": "corner"},
        {"template": "Oak barrel", "room": "Granary", "count": 2, "hint": "corner"},
    ],
    "yard": {"props": [{"template": "Wheat row", "count": 2, "hint": "scatter"}]},
}

CANNED_COTTAGE = {
    "name": "Miller's Cottage", "wall": "wood", "ground": "wood",
    "rooms": [
        {"name": "Main Room", "share": "medium", "purpose": "hearth and table"},
        {"name": "Sleeping Loft", "share": "small", "purpose": "a bed under the thatch"},
    ],
    "connections": [["Main Room", "Sleeping Loft"]],
    "entrance": {"room": "Main Room", "side": "south"},
    "furniture": [
        {"template": "Clay hearth", "room": "Main Room", "count": 1, "hint": "wall:north"},
        {"template": "Trestle table", "room": "Main Room", "count": 1, "hint": "center"},
        {"template": "Wooden stool", "room": "Main Room", "count": 2, "hint": "around:Trestle table"},
        {"template": "Straw bed", "room": "Sleeping Loft", "count": 1, "hint": "wall:north"},
    ],
    "yard": None,
}

CANNED_P4_VILLAGE = {
    "paths": "dirt",
    "props": [{"template": "Village well", "count": 1, "hint": "center"}],
    "filler": [{"template": "Oak tree", "density": "low"}],
}

CANNED_P4_FIELDS = {
    "paths": "dirt",
    "props": [{"template": "Wheat row", "count": 8, "hint": "scatter"},
              {"template": "Scarecrow", "count": 2, "hint": "scatter"}],
    "filler": [],
}

CANNED_P5 = {
    "npcs": [
        {"name": "Aldous Miller", "gender": "male", "role": "miller",
         "home": "The Old Mill", "work": "The Old Mill",
         "description": "The miller; counts every sack twice.",
         "physicalDescription": "Flour-dusted man, leather apron"},
        {"name": "Berta Miller", "gender": "female", "role": "miller's wife",
         "home": "Miller's Cottage", "work": "Wheatfields",
         "description": "Keeps the cottage and the strip behind it.",
         "physicalDescription": "Sun-browned woman, yarn at her belt"},
        {"name": "Colin Miller", "gender": "male", "role": "miller's son",
         "home": "Miller's Cottage", "work": "The Old Mill",
         "description": "Hefts sacks and dodges lessons; wants his own boat.",
         "physicalDescription": "Gangly boy, flour on one ear"},
        {"name": "Daria Wick", "gender": "female", "role": "sieve-maker",
         "home": "The Old Mill", "work": "Millbrook",
         "description": "Bolts the flour and mends sieves; saves for winter.",
         "physicalDescription": "Quiet woman, sieve-ribbon in her hair"},
        {"name": "Edda Straw", "gender": "female", "role": "bonded labourer",
         "home": "Miller's Cottage", "work": "Wheatfields",
         "description": "Works the strips for her keep; owes the mill two days.",
         "physicalDescription": "Broad-shouldered, straw cuts on her palms"},
    ],
    "player": {"name": "Wren Ash", "gender": "female", "role": "traveller",
               "home": "Miller's Cottage", "work": "Millbrook",
               "description": "A traveller staying for the harvest.",
               "physicalDescription": "Lean, patched coat, walking staff"},
}

CANNED_P5_BATCH = {"npcs": CANNED_P5["npcs"]}          # one zone's batch
CANNED_P5_PLAYER = {"player": CANNED_P5["player"]}     # the player's own call


def _perk(name, desc, children=()):
    return {"name": name, "type": "passive", "description": desc,
            "physicalDescription": f"{name} icon, white background",
            "children": [_perk(*c) for c in children]}


CANNED_P6A = {
    "narrativeRules": [
        "Keep the village cozy; real danger stays off the green.",
        "The river's old bargains are honoured, never explained.",
        "Never say what lives under the weir; show the current instead.",
        "Every sack counted twice stays counted twice.",
        "Adults keep secrets from children, not from the player.",
    ],
    "narrativeFlavor": "adaptive",
    "difficulty": "medium",
    "currency": {"name": "Copper penny", "description": "The mill's tally coin.",
                 "format": "5 pennies"},
    "startingCurrency": 8,
    "attributes": {"strength": 6, "dexterity": 5, "intellect": 4,
                   "perception": 5, "charisma": 5},
    "skills": {"Milling": 3, "Bargaining": 2, "Swimming": 1, "Foraging": 2,
               "Carpentry": 1, "Weather-sense": 2, "Animal handling": 1,
               "Reading": 0, "Sprinting": 1, "Net-making": 0, "Carting": 1,
               "Brewing": 0, "First aid": 1, "Storytelling": 2},
    "weatherKinds": ["clear", "rain", "fog", "thunderstorm"],
    "variables": [
        {"name": "Supplies", "emoji": "\U0001F372", "type": "number",
         "value": 8, "initial": 8, "min": 0, "max": 12, "ratePerHour": -0.1},
        {"name": "Weir rumours", "emoji": "\U0001F5E3", "type": "text",
         "value": "the well speaks at night", "initial": "the well speaks at night"},
        {"name": "Mill debt", "emoji": "\u2696", "type": "number",
         "value": 3, "initial": 3, "min": 0, "max": 6},
        {"name": "Season", "emoji": "\U0001F342", "type": "text",
         "value": "harvest", "initial": "harvest"},
    ],
}

CANNED_P6B = {"perkTrees": [
    {"name": "Miller's Craft", "root": _perk(
        "Sack and Tally", "You count twice as fast and never lose the number.",
        [("Steady Back", "Heavy loads cost you half the effort."),
         ("Stone-set Hands", "Your grip holds even when the wheel shudders."),
         ("Bargain Face", "Traders take your first offer seriously."),
         ("Wheel-wright", "You mend a seized mechanism with cord and grease.")])},
    {"name": "River-sense", "root": _perk(
        "Current-reader", "You can tell the river's mood from the drift of leaves.",
        [("Weir-legs", "Wading costs you nothing in cold or current."),
         ("Deep Breath", "You hold your breath three times as long."),
         ("Old Bargain", "Once a day, the water gives back what it took."),
         ("Night-water", "You see the river's shape in the dark.")])},
    {"name": "Village Trust", "root": _perk(
        "Known Face", "Villagers tell you small truths unprompted.",
        [("Hearth-invite", "Doors open for you at supper time."),
         ("Quiet Word", "You calm one argument a day with a word."),
         ("Winter-keep", "The village shares its stores with you before its own."),
         ("Kin-to-anyone", "One family a season calls you their own.")])},
]}

CANNED_P6C = {
    "calendar": [
        {"name": "Morning sacking", "location": "The Old Mill", "day": 0,
         "start": "07:00", "hours": 2, "recurrence": "daily",
         "missedConsequence": "The sacks pile up and Aldous notices who slept in."},
        {"name": "Strip-tending", "location": "Wheatfields", "day": 0,
         "start": "10:00", "hours": 4, "recurrence": "daily",
         "missedConsequence": "The strips go unpicked and Edda's debt grows."},
        {"name": "The weir tally", "location": "The Old Mill", "day": 2,
         "start": "18:00", "hours": 1, "recurrence": "none",
         "missedConsequence": "The river keeps its own count, and it counts against you."},
        {"name": "Harvest supper", "location": "Miller's Cottage", "day": 5,
         "start": "19:00", "hours": 3, "recurrence": "none",
         "missedConsequence": "The village eats apart and remembers who skipped it."},
    ],
    "quests": [
        {"title": "The Wheel and the Water", "objectives": [
            {"text": "Be at the weir tally when the river answers",
             "prerequisites": [
                 {"text": "Work three morning sackings beside Aldous", "primary": True},
                 {"text": "Hear Berta's telling of the old bargain", "primary": False},
                 {"text": "Find what Edda dropped in the shallows", "primary": False}]}]},
    ],
}


# -------------------------------------------------------- JSON extraction

class TestExtractJson(unittest.TestCase):
    def test_plain_object(self):
        obj, err = llm.extract_json('{"a": 1}')
        self.assertIsNone(err)
        self.assertEqual(obj, {"a": 1})

    def test_fenced(self):
        obj, err = llm.extract_json('```json\n{"a": {"b": 2}}\n```')
        self.assertIsNone(err)
        self.assertEqual(obj, {"a": {"b": 2}})

    def test_extra_text_around_and_after(self):
        obj, err = llm.extract_json(
            'Here is the plan you asked for:\n{"a": 1, "b": [1, 2]}\nHope this helps!')
        self.assertIsNone(err)
        self.assertEqual(obj, {"a": 1, "b": [1, 2]})

    def test_nested_braces_in_strings(self):
        obj, err = llm.extract_json('{"a": "brace } inside", "b": 2}')
        self.assertIsNone(err)
        self.assertEqual(obj["a"], "brace } inside")

    def test_empty_and_garbage(self):
        self.assertIsNotNone(llm.extract_json("")[1])
        self.assertIsNotNone(llm.extract_json("no json here")[1])
        self.assertIsNotNone(llm.extract_json('{"a": truncated')[1])


# ------------------------------------------------------- client + retries

class TestClientRetries(unittest.TestCase):
    def _client(self, replies, log_dir=None):
        c = ScriptedClient(replies)
        c.log_dir = log_dir
        return c

    def test_bad_json_then_good(self):
        c = self._client(['not json at all', '{"ok": true}'])
        result = c.call("p1", "sys", "usr", validate=None)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(c.retries, 1)
        self.assertEqual(len(c.sent), 2)
        # the retry carried the failure back to the model
        self.assertEqual(c.sent[1][-1]["role"], "user")
        self.assertIn("no JSON object", c.sent[1][-1]["content"])

    def test_contract_violation_sent_back(self):
        c = self._client([_dump({"a": 1}), _dump({"a": 2})])
        seen = []

        def validate(parsed):
            seen.append(parsed)
            return ["a must be 2"] if parsed.get("a") != 2 else []
        result = c.call("p1", "sys", "usr", validate=validate)
        self.assertEqual(result, {"a": 2})
        self.assertEqual(seen, [{"a": 1}, {"a": 2}])
        self.assertIn("a must be 2", c.sent[1][-1]["content"])

    def test_retries_exhausted_returns_last_parse(self):
        c = self._client([_dump({"a": 1}), _dump({"a": 1})])
        result = c.call("p1", "sys", "usr", validate=lambda p: ["nope"], max_retries=1)
        self.assertEqual(result, {"a": 1})   # caller drops bad entries
        self.assertEqual(c.retries, 1)

    def test_call_log_written_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._client(['{"ok": true}'], log_dir=tmp)
            c.call("p1", "sys", "usr")
            c.call("p2-zone-x", "sys", "usr")
            files = sorted(os.listdir(tmp))
            self.assertEqual(files, ["01-p1.json", "02-p2-zone-x.json"])
            with open(os.path.join(tmp, files[0]), encoding="utf-8") as f:
                record = json.load(f)
            for key in ("attempts", "result", "ok", "seconds", "tokens"):
                self.assertIn(key, record)
            attempt = record["attempts"][0]
            for key in ("messages", "raw_reply", "parsed", "errors", "usage"):
                self.assertIn(key, attempt)
            self.assertNotIn("stub-secret", json.dumps(record))
            self.assertNotIn("api_key", json.dumps(record))


# ------------------------------------------------------- contract checks

GOOD_P1 = json.loads(json.dumps(CANNED_P1))


class TestContracts(unittest.TestCase):
    def test_p1_accepts_good(self):
        self.assertEqual(phases.check_p1(GOOD_P1), [])

    def test_p1_missing_fields(self):
        d = json.loads(json.dumps(GOOD_P1))
        del d["worldBackground"]
        d["setting"]["density"] = "busy"
        errors = phases.check_p1(d)
        self.assertTrue(any("worldBackground" in e for e in errors), errors)
        self.assertTrue(any("density" in e for e in errors), errors)

    def test_p1_unknown_references(self):
        d = json.loads(json.dumps(GOOD_P1))
        d["zones"][0]["adjacentTo"] = ["Nowhere"]
        d["roads"].append({"from": "Millbrook", "to": "Nowhere"})
        errors = phases.check_p1(d)
        self.assertTrue(any("adjacentTo unknown zone 'Nowhere'" in e for e in errors), errors)
        self.assertTrue(any("roads[1].to" in e for e in errors), errors)

    def test_p1_building_cap(self):
        d = json.loads(json.dumps(GOOD_P1))
        d["zones"][0]["buildings"] = [
            {"name": f"Hut {i}", "kind": "hut", "sizeClass": "hut", "purpose": "x", "yard": None}
            for i in range(13)]
        errors = phases.check_p1(d)
        self.assertTrue(any("at most 12" in e for e in errors), errors)

    def test_p2_duplicate_names_and_bad_size(self):
        d = {"templates": [
            {"name": "Bed", "size": [1, 2], "walkability": 0, "description": "d",
             "physicalDescription": "p", "tags": ["bed"], "rule": "r"},
            {"name": "Bed", "size": [9, 9], "walkability": 0, "description": "d",
             "physicalDescription": "p", "tags": [], "rule": "r"},
        ]}
        errors = phases.check_p2(d)
        self.assertTrue(any("used twice" in e for e in errors), errors)
        self.assertTrue(any("size" in e for e in errors), errors)

    def test_p2_needs_a_double_bed_only_when_a_home_has_couples(self):
        singles = [{"templates": [
            {"name": "Straw bed", "size": [1, 2], "walkability": 0.3,
             "forSleep": True, "description": "d", "physicalDescription": "p",
             "tags": ["bed"], "rule": "r"}]}]
        self.assertEqual(phases.check_p2(singles[0]), [])
        self.assertTrue(any("double bed" in e for e in
                            phases.check_p2(singles[0], needs_double=True)))
        with_double = {"templates": singles[0]["templates"] + [
            {"name": "Wide bed", "size": [2, 2], "walkability": 0.3,
             "forSleep": True, "description": "d", "physicalDescription": "p",
             "tags": ["bed"], "rule": "r"}]}
        self.assertEqual(phases.check_p2(with_double, needs_double=True), [])

    def test_p3_unknown_references_and_bad_hint(self):
        tnames = {t["name"] for t in CANNED_TEMPLATES}
        d = json.loads(json.dumps(CANNED_MILL))
        d["name"] = "Wrong Name"
        d["furniture"][0]["template"] = "Golden Throne"
        d["furniture"][0]["room"] = "Nowhere"
        d["furniture"][1]["hint"] = "next to the window"
        errors = phases.check_p3(d, "The Old Mill", tnames, has_yard=True)
        self.assertTrue(any("exactly 'The Old Mill'" in e for e in errors), errors)
        self.assertTrue(any("'Golden Throne' is not in the catalogue" in e for e in errors), errors)
        self.assertTrue(any("'Nowhere' is not one of the rooms" in e for e in errors), errors)
        self.assertTrue(any("unknown token 'next to the window'" in e for e in errors), errors)

    def test_p3_yard_without_plan_yard(self):
        tnames = {t["name"] for t in CANNED_TEMPLATES}
        d = json.loads(json.dumps(CANNED_COTTAGE))
        d["yard"] = {"props": [{"template": "Oak barrel", "count": 1, "hint": "scatter"}]}
        errors = phases.check_p3(d, "Miller's Cottage", tnames, has_yard=False)
        self.assertTrue(any("no yard in the plan" in e for e in errors), errors)

    def test_p4_unknown_template(self):
        tnames = {t["name"] for t in CANNED_TEMPLATES}
        d = json.loads(json.dumps(CANNED_P4_FIELDS))
        d["props"][0]["template"] = "Fountain"
        d["filler"] = [{"template": "Oak tree", "density": "thick"}]
        errors = phases.check_p4(d, "Wheatfields", tnames, {"The Old Mill"})
        self.assertTrue(any("'Fountain' is not in the catalogue" in e for e in errors), errors)
        self.assertTrue(any("density" in e for e in errors), errors)

    def test_p4_building_reference_hint(self):
        tnames = {t["name"] for t in CANNED_TEMPLATES}
        d = json.loads(json.dumps(CANNED_P4_VILLAGE))
        d["props"].append({"template": "Oak barrel", "count": 1, "hint": "behind:Haunted House"})
        errors = phases.check_p4(d, "Millbrook", tnames, {"The Old Mill"})
        self.assertTrue(any("building 'Haunted House' does not exist" in e for e in errors), errors)

    def test_p5_unknown_home_and_work(self):
        d = json.loads(json.dumps(CANNED_P5))
        d["npcs"][0]["home"] = "Cave"
        d["npcs"][1]["work"] = "Moon"
        errors = phases.check_p5(d, {"The Old Mill", "Miller's Cottage"}, {"Millbrook", "Wheatfields"})
        self.assertTrue(any("npcs[0].home" in e for e in errors), errors)
        self.assertTrue(any("npcs[1].work" in e for e in errors), errors)

    def test_p5_home_without_bed_flagged_and_rehomed(self):
        d = json.loads(json.dumps(CANNED_P5))
        errors = phases.check_p5(d, {"The Old Mill", "Miller's Cottage"},
                                 {"Millbrook", "Wheatfields"}, {"Miller's Cottage"})
        self.assertTrue(any("has no bed" in e for e in errors), errors)
        log = []
        clean = phases.sanitize_p5(d, ["The Old Mill", "Miller's Cottage"],
                                   ["Millbrook", "Wheatfields"], log,
                                   bedded=["Miller's Cottage"])
        self.assertEqual(clean["npcs"][0]["home"], "Miller's Cottage")
        self.assertEqual(clean["player"]["home"], "Miller's Cottage")
        self.assertTrue(any("re-homed" in r for _w, r in log), log)

    def test_sanitize_p3_drops_bad_entries(self):
        tnames = {t["name"] for t in CANNED_TEMPLATES}
        d = json.loads(json.dumps(CANNED_MILL))
        d["furniture"].append({"template": "Golden Throne", "room": "Mill Floor",
                               "count": 1, "hint": "center"})
        d["furniture"][0]["hint"] = "on the ceiling"
        log = []
        clean = phases.sanitize_p3(d, "The Old Mill", tnames, log)
        self.assertEqual([f["template"] for f in clean["furniture"]],
                         ["Trestle table", "Wooden stool", "Clay hearth", "Straw bed",
                          "Oak barrel"])
        self.assertEqual(clean["furniture"][0]["hint"], "")
        self.assertTrue(any("Golden Throne" in w + r for w, r in log), log)

    def test_sanitize_p1_drops_bad_road_and_caps_buildings(self):
        d = json.loads(json.dumps(GOOD_P1))
        d["roads"].append({"from": "Millbrook", "to": "Nowhere"})
        d["zones"][0]["buildings"] = [
            {"name": f"Hut {i}", "kind": "hut", "sizeClass": "hut",
             "purpose": "x", "yard": None} for i in range(13)]
        log = []
        clean = phases.sanitize_p1(d, log)
        self.assertEqual(len(clean["roads"]), 1)
        total = sum(len(z["buildings"]) for z in clean["zones"])
        self.assertLessEqual(total, 12)
        self.assertTrue(any("road" in w for w, _r in log), log)
        self.assertTrue(any("12-building cap" in r for _w, r in log), log)


# ------------------------------------------- the canned five-phase run

def canned_replies():
    """Call order: p1, p2, p3 x2, p4 x2, p5 batch (the village zone; the
    fields zone has no buildings, so no batch), p5 player, p6 x3 - with one
    p2 retry scripted."""
    return [
        _dump(CANNED_P1),
        "I will surely help with the catalogue!",   # bad JSON -> one retry
        _dump({"templates": CANNED_TEMPLATES}),
        _dump(CANNED_MILL),
        _dump(CANNED_COTTAGE),
        _dump(CANNED_P4_VILLAGE),
        _dump(CANNED_P4_FIELDS),
        _dump(CANNED_P5_BATCH),
        _dump(CANNED_P5_PLAYER),
        _dump(CANNED_P6A),
        _dump(CANNED_P6B),
        _dump(CANNED_P6C),
    ]


class TestBedCapacity(unittest.TestCase):
    """A sleep object at least 2 cells in both directions sleeps 2; anything
    narrower sleeps 1, a 2x1 single bed turned on its side included."""

    def test_sizes(self):
        from worldgen.model import ObjectTemplate, bed_capacity
        for size, want in [((1, 1), 1), ((1, 2), 1), ((2, 1), 1),
                           ((2, 2), 2), ((3, 2), 2)]:
            self.assertEqual(bed_capacity(size), want, f"{size} should sleep {want}")
            self.assertEqual(bed_capacity(ObjectTemplate(name="B", size=size)),
                             want, f"a {size} template should sleep {want}")


class TestCannedFivePhases(unittest.TestCase):
    def test_plan_json_the_layout_accepts(self):
        client = ScriptedClient(canned_replies())
        plan, stats = phases.run_phases("a mill village", client)
        self.assertEqual(client.calls, 11)
        self.assertEqual(client.retries, 1)
        self.assertEqual(stats["dropped"], [])
        self.assertEqual(len(plan["buildings"]), 2)
        self.assertEqual(plan["zones"][0]["dressing"]["paths"], "dirt")
        self.assertEqual(len(plan["templates"]), len(CANNED_TEMPLATES))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan.json")
            phases.write_plan(plan, path)
            with open(path, encoding="utf-8") as f:
                from_disk = json.load(f)
            world = worldgen.run(from_disk, seed=1)

        self.assertEqual(len(world.zones_by_name), 2)
        self.assertEqual(len(world.buildings), 2)
        zone_failures = [f for f in world.failures if f[0].startswith("zone ")]
        self.assertEqual(zone_failures, [])
        self.assertEqual(world.metrics["rooms"]["reachable"],
                         world.metrics["rooms"]["total"], world.metrics["rooms"])
        self.assertEqual(world.metrics["entrances"]["reachable_from_road"],
                         world.metrics["entrances"]["total"])
        self.assertEqual(world.metrics["objects"]["unplaced"], [])
        self.assertGreater(len(world.objects), 10)

    def test_run_phases_survives_a_bad_building(self):
        replies = canned_replies()
        # p3 for the mill never parses: 1 attempt + 2 retries, all garbage
        replies[3:4] = ["total nonsense", "still nonsense", "no json either"]
        client = ScriptedClient(replies)
        plan, stats = phases.run_phases("a mill village", client)
        self.assertTrue(any("The Old Mill" in w for w, _r in stats["dropped"]), stats["dropped"])
        # the P1 shell survives; the cottage has its design
        self.assertEqual([b["name"] for b in plan["buildings"]], ["Miller's Cottage"])
        zone = plan["zones"][0]
        self.assertEqual([b["name"] for b in zone["buildings"]],
                         ["The Old Mill", "Miller's Cottage"])
        world = worldgen.run(plan, seed=1)
        self.assertEqual(len(world.buildings), 2)


class TestSpareRooms(unittest.TestCase):
    def test_inn_and_hospital_rooms_are_spare(self):
        from worldgen.model import is_spare_room
        for name, purpose in (("Guest Chamber", ""), ("Letting Room", ""),
                              ("Lodging room", ""), ("Patient Room", ""),
                              ("West Wing Rest Ward", ""), ("Sick Room", ""),
                              ("Infirmary", ""), ("Room 3", "for travellers"),
                              ("Back Room", "lodging for paying guests")):
            self.assertTrue(is_spare_room(name, purpose), name)

    def test_words_that_only_contain_ward_are_not(self):
        from worldgen.model import is_spare_room
        for name, purpose in (("Warden's Room", ""), ("Steward's Cabin", ""),
                              ("Bedroom", "a wardrobe and a bed"),
                              ("Master Bedchamber", "the parents' bed"),
                              ("Keeper's Room", "the keeper's own bed")):
            self.assertFalse(is_spare_room(name, purpose), name)


if __name__ == "__main__":
    unittest.main()
