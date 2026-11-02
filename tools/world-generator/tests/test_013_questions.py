"""Brief 013 change 1: the World Frame question bank — plain data, one
loader, the same questions for the launcher, the editor and P0."""
import os
import tempfile
import unittest

from worldgen import questions


class TestTheBank(unittest.TestCase):
    def setUp(self):
        self.bank = questions.load_bank()

    def test_the_bank_loads_and_is_well_formed(self):
        self.assertEqual(len(self.bank["short"]), 7)
        self.assertEqual(len(self.bank["medium"]), 7)
        for q in self.bank["short"] + self.bank["medium"]:
            self.assertTrue(q["prompt"].strip())
            self.assertTrue(q["feeds"])
            if not q.get("free"):
                self.assertTrue(q["options"])
                self.assertNotIn("Other", q["options"])

    def test_ids_are_unique_across_forms(self):
        ids = [q["id"] for q in self.bank["short"] + self.bank["medium"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_broken_bank_fails_loudly(self):
        bad = {"population": {"default": [20, 40], "min": 5, "max": 60},
               "short": [{"id": "q", "prompt": "?", "options": ["Other"], "feeds": ["x"]}],
               "medium": self.bank["medium"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                import json
                json.dump(bad, f)
            with self.assertRaises(ValueError):
                questions.load_bank(path)


class TestForms(unittest.TestCase):
    def test_every_mode_gets_its_questions(self):
        self.assertEqual(questions.form_questions("quick"), [])
        self.assertEqual(len(questions.form_questions("short")), 7)
        for mode in ("medium", "long"):
            self.assertEqual(len(questions.form_questions(mode)), 14)
        short_ids = [q["id"] for q in questions.form_questions("short")]
        medium_ids = [q["id"] for q in questions.form_questions("medium")]
        self.assertEqual(medium_ids[:7], short_ids, "medium is short plus more")

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            questions.form_questions("gigantic")


class TestAnswers(unittest.TestCase):
    def test_unknown_questions_and_choices_drop(self):
        answers = {"genre": {"choices": ["Fantasy", "Not an option"], "other": ""},
                   "mystery": {"choices": ["A mystery"]},
                   "avoid": {"choices": [], "other": "no spiders"}}
        clean = questions.sanitize_answers("short", answers)
        self.assertEqual(clean, {"genre": {"choices": ["Fantasy"], "other": ""},
                                 "avoid": {"choices": [], "other": "no spiders"}})

    def test_multi_is_capped(self):
        clean = questions.sanitize_answers(
            "short", {"genre": {"choices": ["Fantasy", "Horror", "Modern day"]}})
        self.assertEqual(clean["genre"]["choices"], ["Fantasy", "Horror"])

    def test_free_text_is_trimmed_to_a_steer(self):
        clean = questions.sanitize_answers(
            "short", {"avoid": {"choices": [], "other": "x" * 900}})
        self.assertEqual(len(clean["avoid"]["other"]), questions.MAX_OTHER_CHARS)

    def test_medium_answers_do_not_leak_into_short(self):
        clean = questions.sanitize_answers("short", {"stakes": {"choices": ["Cosmic"]}})
        self.assertEqual(clean, {})

    def test_other_text_survives_without_choices(self):
        clean = questions.sanitize_answers("short", {"tone": {"other": "hopeful punk"}})
        self.assertEqual(clean, {"tone": {"choices": [], "other": "hopeful punk"}})

    def test_render_answers_lines_every_question(self):
        lines = questions.render_answers(
            "short", {"genre": {"choices": ["Fantasy"], "other": ""}})
        self.assertEqual(len(lines), 7)
        self.assertIn("Fantasy", lines[0])
        self.assertIn("(skipped)", lines[1], "an unanswered question says so")


class TestPopulation(unittest.TestCase):
    def test_default_range(self):
        self.assertEqual(questions.sanitize_population(None), [20, 40])
        self.assertEqual(questions.sanitize_population([]), [20, 40])
        self.assertEqual(questions.sanitize_population("many"), [20, 40])

    def test_clamped_and_ordered(self):
        self.assertEqual(questions.sanitize_population([0, 999]), [5, 60])
        self.assertEqual(questions.sanitize_population([40, 10]), [10, 40])
        self.assertEqual(questions.sanitize_population([12]), [20, 40])


if __name__ == "__main__":
    unittest.main()
