"""A reply that spent the whole max_tokens budget is retried with twice the
budget, on the same messages. Found by the live zombie-town run: P2 (templates,
30-60 items, loot pools) used exactly 16000 completion tokens three times and
replied empty. A reply can also stop mid-item, and the bracket repair then
closes the stump into valid JSON: Downpour Block shipped that way with 10 items,
no loot pools and every container empty."""
import json
import unittest
from unittest import mock

from worldgen import llm, phases


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
        self.assertEqual(c.call("px", "sys", "user"), {"ok": 1})
        self.assertEqual(c.budgets, [100, 200, 400])
        self.assertEqual(c.sent, [2, 2, 2], "no correction turn for an empty reply")

    def test_a_short_empty_reply_is_corrected_not_doubled(self):
        c = BudgetClient([("", 5), ('{"ok": 1}', 5)])
        c.call("px", "sys", "user")
        self.assertEqual(c.budgets, [100, 100])
        self.assertEqual(c.sent, [2, 4])

    def test_the_budget_stops_at_the_ceiling(self):
        c = BudgetClient([("", 10 ** 9)] * 3)
        c.max_tokens = llm.MAX_TOKENS_CEILING
        c.call("px", "sys", "user")
        self.assertEqual(c.budgets, [llm.MAX_TOKENS_CEILING] * 3)


class TestCutOff(unittest.TestCase):
    STUMP = '{"templates": [{"name": "Stove"}], "items": [{"name": "Soup"}, {"name": "Te'
    WHOLE = '{"templates": [{"name": "Stove"}], "items": [], "lootPools": {}}'

    def test_a_reply_stopped_mid_item_never_counts(self):
        c = BudgetClient([(self.STUMP, 100), (self.WHOLE, 150)])
        self.assertEqual(c.call("px", "sys", "user"), json.loads(self.WHOLE))
        self.assertEqual(c.budgets, [100, 200])
        self.assertEqual(c.sent, [2, 2], "the stump isn't fed back")

    def test_the_provider_saying_so_counts_too(self):
        c = BudgetClient([(self.STUMP, 40), (self.WHOLE, 40)])
        real = c._request

        def stopped(messages, max_tokens=None):
            reply, usage = real(messages, max_tokens)
            if reply == self.STUMP:
                usage["finish"] = "length"
            return reply, usage
        c._request = stopped
        self.assertEqual(c.call("px", "sys", "user"), json.loads(self.WHOLE))
        self.assertEqual(c.budgets, [100, 200])

    def test_a_stump_is_all_there_is_after_every_try(self):
        c = BudgetClient([(self.STUMP, 10 ** 6)] * 3)
        result = c.call("px", "sys", "user")
        self.assertEqual(result["items"], [{"name": "Soup"}])
        self.assertTrue(c.last_cut)

    def test_a_good_reply_clears_the_mark(self):
        c = BudgetClient([(self.STUMP, 100), (self.WHOLE, 150)])
        c.call("px", "sys", "user")
        self.assertFalse(c.last_cut)

    def test_the_run_reports_a_stump_it_kept(self):
        c = BudgetClient([(self.STUMP, 10 ** 6)] * 3)
        stats = {"dropped": [], "phase_log": []}
        call = phases._make_caller(c, stats, None, None)
        with mock.patch.object(phases, "assemble_prompt", return_value="prompt"):
            call("px", "template")
        self.assertTrue(any("cut off" in why for _what, why in stats["dropped"]))

    def test_the_catalogue_starts_with_room(self):
        c = BudgetClient([(self.WHOLE, 5)])
        c.call("p2", "sys", "user")
        self.assertEqual(c.budgets, [llm.PHASE_BUDGETS["p2"]])


class TestTransport(unittest.TestCase):
    """The rerun of the zombie-town world died with a raw TimeoutError from a
    read past REQUEST_TIMEOUT, uncaught, ending the whole run."""

    def test_a_read_timeout_is_an_llm_error(self):
        import unittest.mock as mock
        c = BudgetClient([])
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(llm.LLMError):
                llm.Client._request(c, [{"role": "user", "content": "x"}])

    def test_call_retries_after_a_timeout(self):
        c = BudgetClient([('{"ok": 1}', 5)])
        real = c._request
        state = {"n": 0}

        def flaky(messages, max_tokens=None):
            state["n"] += 1
            if state["n"] == 1:
                raise llm.LLMError("the connection failed: TimeoutError()")
            return real(messages, max_tokens)
        c._request = flaky
        self.assertEqual(c.call("p1", "sys", "user"), {"ok": 1})


if __name__ == "__main__":
    unittest.main()
