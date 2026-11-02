"""Replies whose brackets close in the wrong order are rebalanced before
they are given up on. Found by the live zombie-town run: the perk-tree
reply (three trees, children nested four deep) closed with ']}]}]}' where
it needed ']}]}]}]}' style balance, identically on all three attempts, and
the scenario shipped with no perk trees."""
import json
import unittest

from worldgen import llm


class TestRepair(unittest.TestCase):
    def test_a_wrong_closer_closes_down_to_its_match(self):
        obj, err = llm.extract_json('{"a": [{"b": [1, 2}]}')
        self.assertIsNone(err)
        self.assertEqual(obj, {"a": [{"b": [1, 2]}]})

    def test_missing_closers_are_added(self):
        obj, err = llm.extract_json('{"t": [{"c": []}, {"c": [{"n": 1}]}]')
        self.assertIsNone(err)
        self.assertEqual(len(obj["t"]), 2)

    def test_brackets_inside_strings_are_left_alone(self):
        self.assertEqual(llm.repair_brackets('{"s": "a]b}"}'), '{"s": "a]b}"}')
        self.assertEqual(json.loads(llm.repair_brackets('{"s": "q\\"]"]')), {"s": 'q"]'})

    def test_hopeless_text_still_reports_the_parse_error(self):
        obj, err = llm.extract_json('{"a": 1 "b": 2}')
        self.assertIsNone(obj)
        self.assertIn("not valid JSON", err)

    def test_valid_json_is_untouched(self):
        self.assertEqual(llm.extract_json('{"a": [1, {"b": 2}]}')[0], {"a": [1, {"b": 2}]})


if __name__ == "__main__":
    unittest.main()
