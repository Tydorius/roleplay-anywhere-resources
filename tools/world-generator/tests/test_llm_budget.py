"""An empty reply that spent the whole max_tokens budget (a reasoning model
thinking past it) is retried with twice the budget, on the same messages.
Found by the live zombie-town run: P2 (templates, 30-60 items, loot pools)
used exactly 16000 completion tokens three times and replied empty."""
import unittest

from worldgen import llm


class BudgetClient(llm.Client):
    def __init__(self, script):
        self.provider, self.model, self.max_tokens = "stub", "stub-model", 100
        self.base_url, self._api_key, self.log_dir = "http://stub", "x", None
        self.calls, self.retries, self.seconds = 0, 0, 0.0
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.script = list(script)   # [(reply, completion tokens)]
        self.budgets, self.sent = [], []

    def _request(self, messages, max_tokens=None):
        self.budgets.append(max_tokens)
        self.sent.append(len(messages))
        reply, used = self.script.pop(0)
        return reply, {"prompt": 1, "completion": used, "total": used + 1}


class TestBudget(unittest.TestCase):
    def test_spent_budget_doubles_and_keeps_the_messages(self):
        c = BudgetClient([("", 100), ("", 200), ('{"ok": 1}', 150)])
        self.assertEqual(c.call("p2", "sys", "user"), {"ok": 1})
        self.assertEqual(c.budgets, [100, 200, 400])
        self.assertEqual(c.sent, [2, 2, 2], "no correction turn for an empty reply")

    def test_a_short_empty_reply_is_corrected_not_doubled(self):
        c = BudgetClient([("", 5), ('{"ok": 1}', 5)])
        c.call("p2", "sys", "user")
        self.assertEqual(c.budgets, [100, 100])
        self.assertEqual(c.sent, [2, 4])

    def test_the_budget_stops_at_the_ceiling(self):
        c = BudgetClient([("", 10 ** 9)] * 3)
        c.max_tokens = llm.MAX_TOKENS_CEILING
        c.call("p2", "sys", "user")
        self.assertEqual(c.budgets, [llm.MAX_TOKENS_CEILING] * 3)


if __name__ == "__main__":
    unittest.main()
