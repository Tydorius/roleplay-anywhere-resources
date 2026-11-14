"""Client.chat: a whole conversation in one call — the caller's history with
the system message in front, OpenAI content parts (text and image) passed
through, the same JSON contract loop as call(), image_part's data URLs, and
the per-provider "vision" flag that gates image parts before any request.
The transport is stubbed the way tests.test_llm_budget stubs it: request
messages captured, replies scripted."""
import base64
import json
import os
import tempfile
import unittest
from unittest import mock

from worldgen import llm


class ChatClient(llm.Client):
    def __init__(self, script, vision=True):
        self.provider, self.model, self.max_tokens = "stub", "stub-model", 100
        self.base_url, self._api_key, self.log_dir = "http://stub", "x", None
        self.calls, self.retries, self.seconds = 0, 0, 0.0
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.vision = vision
        self.script = list(script)   # [(reply, completion tokens)]
        self.sent = []               # the messages of each request

    def _request(self, messages, max_tokens=None):
        self.sent.append([dict(m) for m in messages])
        reply, used = self.script.pop(0)
        return reply, {"prompt": 1, "completion": used, "total": used + 1}


HISTORY = [{"role": "user", "content": "name three herbs"},
           {"role": "assistant", "content": '{"herbs": ["sage"]}'},
           {"role": "user", "content": "and one more"}]


class TestChat(unittest.TestCase):
    def test_sends_the_history_with_the_system_message_first(self):
        c = ChatClient([('{"herbs": ["sage", "thyme"]}', 5)])
        result = c.chat("chat", "be brief", HISTORY)
        self.assertEqual(result, {"herbs": ["sage", "thyme"]})
        self.assertEqual(c.sent[0], [{"role": "system", "content": "be brief"}] + HISTORY)
        self.assertEqual(c.calls, 1)

    def test_without_a_system_message_the_history_goes_as_is(self):
        c = ChatClient([('{"ok": 1}', 5)])
        c.chat("chat", None, HISTORY)
        self.assertEqual(c.sent[0], HISTORY)

    def test_a_failed_check_is_retried_and_the_callers_list_untouched(self):
        c = ChatClient([('{"answer": 41}', 5), ('{"answer": 42}', 5)])
        msgs = [{"role": "user", "content": "the answer?"}]

        def check(parsed):
            return [] if parsed.get("answer") == 42 else ["the answer must be 42"]
        self.assertEqual(c.chat("chat", None, msgs, validate=check), {"answer": 42})
        self.assertEqual(len(c.sent), 2)
        follow = c.sent[1]
        self.assertEqual(follow[-2], {"role": "assistant", "content": '{"answer": 41}'})
        self.assertEqual(follow[-1]["role"], "user")
        self.assertIn("the answer must be 42", follow[-1]["content"])
        self.assertIn("Reply again with ONE corrected JSON object",
                      follow[-1]["content"])
        self.assertEqual(msgs, [{"role": "user", "content": "the answer?"}],
                         "the caller's list must not gain the retry turn")

    def test_string_and_content_part_content_pass_through(self):
        parts = [{"type": "text", "text": "what is in this image?"},
                 {"type": "image_url", "image_url": {"url": "data:image/webp;base64,AAA"}}]
        c = ChatClient([('{"sees": "a cat"}', 5)])
        c.chat("chat", None, [{"role": "user", "content": parts},
                              {"role": "user", "content": "plain text"}])
        self.assertIs(c.sent[0][0]["content"], parts, "the parts arrive as-is")
        self.assertEqual(c.sent[0][1]["content"], "plain text")


class TestImagePart(unittest.TestCase):
    def test_bytes_become_a_webp_data_url(self):
        raw = b"\x89PNG\r\n\x1a\n-not-really"
        part = llm.image_part(raw)
        self.assertEqual(part["type"], "image_url")
        self.assertEqual(part["image_url"]["url"],
                         "data:image/webp;base64,"
                         + base64.b64encode(raw).decode("ascii"))

    def test_a_file_is_read_and_the_mime_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sprite.png")
            with open(path, "wb") as f:
                f.write(b"\x00\x01")
            part = llm.image_part(path, "image/png")
        self.assertEqual(part["image_url"]["url"],
                         "data:image/png;base64,"
                         + base64.b64encode(b"\x00\x01").decode("ascii"))

    def test_a_missing_file_is_a_clear_error(self):
        missing = os.path.join(tempfile.gettempdir(), "no-such-image-9x7.webp")
        with self.assertRaises(llm.LLMError) as cm:
            llm.image_part(missing)
        self.assertIn("no-such-image-9x7.webp", str(cm.exception))


def providers_file(entry):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "providers.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"p": dict({"base_url": "https://example.test", "api_key": "k",
                              "model": "m", "max_tokens": 16000}, **entry)}, f)
    return p


class TestVisionFlag(unittest.TestCase):
    def test_the_flag_comes_from_the_provider_config(self):
        self.assertTrue(llm.Client("p", providers_path=providers_file({"vision": True})).vision)
        self.assertFalse(llm.Client("p", providers_path=providers_file({})).vision)

    def test_an_image_without_the_flag_fails_before_any_request(self):
        c = ChatClient([('{"ok": 1}', 5)], vision=False)
        with self.assertRaises(llm.LLMError) as cm:
            c.chat("chat", None, [{"role": "user", "content": [llm.image_part(b"img")]}])
        self.assertIn("providers.json", str(cm.exception))
        self.assertIn("stub", str(cm.exception))
        self.assertEqual(c.sent, [], "no request was made")

    def test_an_image_with_the_flag_goes_through(self):
        c = ChatClient([('{"sees": "a sword"}', 5)], vision=True)
        part = llm.image_part(b"img")
        result = c.chat("chat", None, [{"role": "user", "content": [part]}])
        self.assertEqual(result, {"sees": "a sword"})
        self.assertEqual(c.sent[0][0]["content"], [part])


class TestCheckProviderReport(unittest.TestCase):
    def test_the_success_report_says_whether_the_model_takes_images(self):
        class FakeResponse:
            def __init__(self, data):
                self.data = json.dumps(data).encode("utf-8")

            def read(self):
                return self.data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        reply = FakeResponse({"choices": [{"message": {"content": "ok"},
                                           "finish_reason": "stop"}],
                              "usage": {"total_tokens": 4}})
        for entry, want in (({"vision": True}, True), ({}, False)):
            with mock.patch.object(llm.urllib.request, "urlopen", return_value=reply):
                report = llm.check_provider("p", providers_path=providers_file(entry))
            self.assertTrue(report["ok"])
            self.assertIs(report["vision"], want)


if __name__ == "__main__":
    unittest.main()
