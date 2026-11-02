"""Brief 013 change 2: phase P0, the World Frame - the clarify turn, the
frame contract, and the frame flowing through P1-P5 in place of the bare
idea. All mocked; no network."""
import json
import unittest

from tests.test_model import ScriptedClient, canned_replies
from worldgen import phases
from worldgen.phases import (check_p0, check_p0_clarify, frame_brief,
                             sanitize_p0, sanitize_p0_clarify)


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


def a_frame(**over):
    """A valid frame, 100-word summary and all."""
    frame = {
        "genre": {"primary": "Fantasy", "influences": ["folk horror"]},
        "premise": "A mill town whose river spirit has stopped answering.",
        "reality": "Old spirits are real but rare, and mostly unseen.",
        "setting": {"era": "late medieval", "technology": "water and wood",
                    "climate": "wet temperate"},
        "tone": "cozy with an edge",
        "conflict": "The millers want the wheel turning; the river wants its due.",
        "playerRole": "A newcomer surveying the weir, stranded until spring.",
        "themes": ["small community", "old bargains"],
        "constraints": ["no graphic violence"],
        "summary": " ".join("Millbrook hugs its bend of the river and the wheel "
                            "that turns there. The millers keep their bargains, "
                            "the children keep clear of the weir, and every "
                            "household leaves a loaf on the sill at the month's "
                            "turn. This year the loaves go mouldy untouched and "
                            "the water runs low enough to count the stones. "
                            "Nobody says the spirit's name out loud. Somebody "
                            "has to walk the weir and ask what it wants.".split()),
        "unresolved": ["named the river spirit myself"],
    }
    frame.update(over)
    return frame


class TestCheckP0(unittest.TestCase):
    def test_a_good_frame_passes(self):
        self.assertEqual(check_p0(a_frame()), [])

    def test_missing_fields_are_errors(self):
        errors = check_p0({"summary": "too thin"})
        for key in ("genre", "premise", "reality", "tone", "conflict",
                    "playerRole", "setting", "summary"):
            self.assertTrue(any(e.startswith(key) for e in errors), errors)

    def test_the_summary_word_count_is_checked(self):
        short = a_frame(summary="Far too short.")
        self.assertTrue(any("words" in e for e in check_p0(short)))
        long = a_frame(summary=" ".join(["word"] * 250))
        self.assertTrue(any("words" in e for e in check_p0(long)))

    def test_sanitize_fills_every_field(self):
        log = []
        frame = sanitize_p0({}, log)
        for key in ("genre", "premise", "reality", "setting", "tone", "conflict",
                    "playerRole", "themes", "constraints", "summary", "unresolved"):
            self.assertIn(key, frame)
        self.assertTrue(log)


class TestCheckClarify(unittest.TestCase):
    def test_zero_questions_is_valid(self):
        self.assertEqual(check_p0_clarify({"questions": []}), [])

    def test_a_good_question_passes(self):
        d = {"questions": [{"question": "Cozy or deadly - which wins?",
                            "options": ["Cozy", "Deadly", "Both in turns"]}]}
        self.assertEqual(check_p0_clarify(d), [])

    def test_bad_shapes_are_errors(self):
        self.assertTrue(check_p0_clarify({"questions": [{"question": "?",
                                                        "options": ["only one"]}]}))
        self.assertTrue(check_p0_clarify(
            {"questions": [{"question": "?", "options": ["a", "b"]}] * 6}))

    def test_sanitize_drops_bad_questions_and_caps_five(self):
        log = []
        good = {"question": "Q?", "options": ["a", "b"]}
        d = {"questions": [good, {"question": "bad", "options": ["x"]},
                           {"question": "Q2?", "options": ["a", "b"]}] + [good] * 4}
        out = sanitize_p0_clarify(d, log)
        self.assertEqual(len(out["questions"]), 5)
        self.assertTrue(log)


class TestRunFrame(unittest.TestCase):
    def test_quick_expands_the_idea(self):
        client = ScriptedClient([_dump(a_frame())])
        frame, qs, stats = phases.run_frame(client, "quick", idea="a mill village")
        self.assertEqual(client._queue, [], "the one scripted reply was used")
        self.assertEqual(frame["genre"]["primary"], "Fantasy")
        self.assertEqual(qs, [])
        self.assertEqual([e["phase"] for e in stats["phase_log"]], ["p0"])
        self.assertIn("no questionnaire", client.sent[0][1]["content"])

    def test_short_carries_the_answers(self):
        client = ScriptedClient([_dump(a_frame())])
        frame, _qs, _stats = phases.run_frame(
            client, "short", idea="",
            answers={"genre": {"choices": ["Fantasy"], "other": ""}})
        self.assertIn("Fantasy", client.sent[0][1]["content"])
        self.assertIn("(skipped)", client.sent[0][1]["content"],
                      "an unanswered question says so")

    def test_long_asks_before_framing(self):
        q = {"question": "Cozy or deadly?", "options": ["Cozy", "Deadly"]}
        client = ScriptedClient([_dump({"questions": [q]}), _dump(a_frame())])
        frame, qs, _stats = phases.run_frame(client, "long", idea="x")
        self.assertIsNone(frame)
        self.assertEqual(qs, [q])
        # second call: the answered clarification goes in
        frame, qs, _stats = phases.run_frame(
            client, "long", idea="x", clarify=[{"question": "Cozy or deadly?",
                                                "answer": "Cozy"}])
        self.assertEqual(frame["genre"]["primary"], "Fantasy")
        self.assertIn("Cozy or deadly?", client.sent[1][1]["content"])
        self.assertIn("Cozy", client.sent[1][1]["content"])

    def test_long_with_nothing_to_ask_frames_at_once(self):
        client = ScriptedClient([_dump({"questions": []}), _dump(a_frame())])
        frame, qs, _stats = phases.run_frame(client, "long", idea="x")
        self.assertEqual(qs, [])
        self.assertEqual(frame["premise"], a_frame()["premise"])

    def test_unsalvageable_p0_raises(self):
        client = ScriptedClient(["no json here", "still nothing", "nope"])
        with self.assertRaises(phases.PhaseError):
            phases.run_frame(client, "quick", idea="x")


class TestFrameFlowsThroughThePhases(unittest.TestCase):
    def test_p1_gets_the_frame_and_the_plan_keeps_it(self):
        frame = a_frame()
        client = ScriptedClient(canned_replies())
        plan, stats = phases.run_phases(
            "a mill village", client, frame=frame,
            questionnaire={"mode": "short", "answers": {}, "population": [5, 6]})
        self.assertEqual(client.calls, 8, "no extra P0 call: the frame came in")
        p1_prompt = client.sent[0][1]["content"]
        self.assertIn("WORLD FRAME", p1_prompt)
        self.assertIn(frame["premise"], p1_prompt)
        self.assertIn("house 5-6 residents", p1_prompt)
        self.assertEqual(plan["frame"]["premise"], frame["premise"])
        self.assertEqual(plan["questionnaire"]["mode"], "short")

    def test_later_phases_see_the_frame_in_the_setting_line(self):
        frame = a_frame()
        client = ScriptedClient(canned_replies())
        phases.run_phases("a mill village", client, frame=frame,
                          questionnaire={"mode": "quick", "answers": {},
                                         "population": [5, 6]})
        p2_prompt = client.sent[1][1]["content"]   # P2 is the second call
        self.assertIn("FRAME (the user approved this)", p2_prompt)
        self.assertIn(frame["tone"], p2_prompt)
        self.assertIn("no graphic violence", p2_prompt)

    def test_a_questionnaire_without_a_frame_runs_p0_inline(self):
        client = ScriptedClient([_dump(a_frame())] + canned_replies())
        plan, _stats = phases.run_phases(
            "a mill village", client,
            questionnaire={"mode": "quick", "answers": {}, "population": [5, 6]})
        self.assertEqual(client.calls, 9, "P0 ran, then the eight canned calls")
        self.assertEqual(plan["frame"]["genre"]["primary"], "Fantasy")

    def test_no_frame_no_questionnaire_is_yesterdays_path(self):
        client = ScriptedClient(canned_replies())
        plan, _stats = phases.run_phases("a mill village", client)
        self.assertNotIn("frame", plan)
        self.assertNotIn("questionnaire", plan)
        self.assertEqual(client.calls, 8)

    def test_frame_brief_is_empty_without_a_frame(self):
        self.assertEqual(frame_brief(None), "")
        self.assertEqual(frame_brief({}), "")


if __name__ == "__main__":
    unittest.main()
