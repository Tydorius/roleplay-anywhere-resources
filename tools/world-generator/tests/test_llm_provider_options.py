"""Provider options for endpoints with their own rules: ``max_output`` holds
every request's budget under a provider's output cap (P2 asks for 32000 and a
cut-off reply doubles it, which a provider with a smaller cap answers with HTTP
400), and ``extra_body`` adds request fields such as DeepSeek's ``thinking``."""
import json
import os
import tempfile
import unittest
from unittest import mock

from worldgen import llm

from tests.test_llm_budget import BudgetClient


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


OK_REPLY = {"choices": [{"message": {"content": "ok", "reasoning_content": "thinking"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}


def providers_file(entry):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "providers.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"p": dict({"base_url": "https://example.test", "api_key": "k",
                              "model": "m", "max_tokens": 16000}, **entry)}, f)
    return p


class TestMaxOutput(unittest.TestCase):
    def test_phase_budgets_are_held_to_the_cap(self):
        c = BudgetClient([('{"ok": 1}', 5)])
        c.max_output = 8000
        c.call("p2", "sys", "user")
        self.assertEqual(c.budgets, [8000])

    def test_doubling_stops_at_the_cap(self):
        c = BudgetClient([("", 10 ** 6)] * 3)
        c.max_output = 150
        c.call("px", "sys", "user")
        self.assertEqual(c.budgets, [100, 150, 150])

    def test_no_cap_leaves_budgets_alone(self):
        c = BudgetClient([('{"ok": 1}', 5)])
        c.call("p2", "sys", "user")
        self.assertEqual(c.budgets, [llm.PHASE_BUDGETS["p2"]])

    def test_a_bad_cap_is_a_clear_error(self):
        for bad in ("lots", 0):
            with self.assertRaises(llm.LLMError):
                llm.Client("p", providers_path=providers_file({"max_output": bad}))


class TestRequestBody(unittest.TestCase):
    def sent_body(self, entry, max_tokens=32000):
        c = llm.Client("p", providers_path=providers_file(entry))
        seen = {}

        def fake(req, timeout=None):
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse(OK_REPLY)
        with mock.patch.object(llm.urllib.request, "urlopen", fake):
            content, usage = c._post([{"role": "user", "content": "hi"}], max_tokens)
        self.assertEqual(content, "ok", "only message.content is read, not the reasoning")
        return seen["body"]

    def test_extra_fields_are_sent(self):
        body = self.sent_body({"extra_body": {"thinking": {"type": "disabled"},
                                              "_comment": "a note"}})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("_comment", body)

    def test_extra_fields_cannot_replace_the_core_ones(self):
        body = self.sent_body({"extra_body": {"model": "other", "max_tokens": 5,
                                              "messages": []}})
        self.assertEqual((body["model"], body["max_tokens"]), ("m", 32000))
        self.assertEqual(len(body["messages"]), 1)

    def test_the_cap_applies_to_the_sent_body(self):
        self.assertEqual(self.sent_body({"max_output": 8192})["max_tokens"], 8192)

    def test_extra_body_must_be_an_object(self):
        with self.assertRaises(llm.LLMError):
            llm.Client("p", providers_path=providers_file({"extra_body": "thinking"}))

    def test_check_provider_sends_them_too(self):
        path = providers_file({"max_output": 500, "extra_body": {"reasoning_effort": "low"}})
        seen = {}

        def fake(req, timeout=None):
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse(OK_REPLY)
        with mock.patch.object(llm.urllib.request, "urlopen", fake):
            report = llm.check_provider("p", providers_path=path)
        self.assertTrue(report["ok"])
        self.assertEqual(seen["body"]["max_tokens"], 500)
        self.assertEqual(seen["body"]["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()
