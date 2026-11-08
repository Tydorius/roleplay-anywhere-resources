"""The library interface: a mocked provider (the scripted client) produces
a zip and progress events through api.generate, cancel stops the run between
model calls, estimate returns sane numbers from an idea or a plan, and
relayout rebuilds a plan with no model calls at all."""
import json
import os
import tempfile
import unittest

from tests.test_model import ScriptedClient, canned_replies
from worldgen import api

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


class TestGenerateWithAMockedProvider(unittest.TestCase):
    def test_generate_builds_a_zip_and_emits_progress_events(self):
        events = []
        client = ScriptedClient(canned_replies())
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.generate("a mill village", client=client, seed=3, cast=False,
                                   out_dir=tmp, progress=events.append, library=False)
            zip_path = os.path.join(tmp, summary["zip"])
            self.assertTrue(os.path.exists(zip_path), summary)
            for artifact in ("plan.json", "spec.json", "spec.py", "metrics.json"):
                self.assertTrue(os.path.exists(os.path.join(tmp, artifact)), artifact)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["calls"], 11)
        self.assertEqual(summary["provider"], "stub")
        self.assertEqual(summary["extensions"], [])
        self.assertEqual(summary["validator_errors"], 0, summary)

        phases = [e["phase"] for e in events]
        self.assertEqual(phases[0], "P1")
        self.assertEqual(phases[-1], "done")
        self.assertIn("layout", phases)
        p3 = [e for e in events if e["phase"] == "P3"]
        self.assertEqual([e["label"] for e in p3],
                         ["building 1/2: The Old Mill",
                          "building 2/2: Miller's Cottage"])
        self.assertEqual(p3[0]["calls"], 3, "the first building is call 3")
        # every event carries the running counts
        for e in events:
            self.assertIn("calls", e)
            self.assertIn("tokens", e)

    def test_cancel_stops_between_model_calls(self):
        client = ScriptedClient(canned_replies())

        def cancel():
            return client.calls >= 2   # stop after P2 (its scripted retry included)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(api.Cancelled) as caught:
                api.generate("a mill village", client=client, seed=1, cast=False,
                             out_dir=tmp, cancel=cancel, library=False)
        # the run stopped at the first P3 call, which was never made
        self.assertIn("p3", str(caught.exception))
        self.assertEqual(client.calls, 2)

    def test_unknown_extension_fails_fast(self):
        with self.assertRaises(ValueError):
            api.generate("x", client=ScriptedClient([]), extensions=("levitate",),
                         out_dir="out/never")


class TestRelayout(unittest.TestCase):
    def test_relayout_rebuilds_without_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = api.relayout(os.path.join(FIXTURES, "village.json"),
                                   seed=5, out_dir=tmp)
            self.assertTrue(os.path.exists(os.path.join(tmp, summary["zip"])), summary)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["calls"], 0)
        self.assertEqual(summary["tokens"], 0)
        self.assertIsNone(summary["provider"])
        self.assertEqual(summary["buildings"], 5)


class TestEstimate(unittest.TestCase):
    def test_idea_uses_the_measured_runs(self):
        e = api.estimate("a fogbound harbour town of smugglers")
        self.assertTrue(e["calls_range"][0] <= e["calls"] <= e["calls_range"][1])
        self.assertGreaterEqual(e["tokens"], 200000)
        self.assertLessEqual(e["tokens"], 320000)
        self.assertTrue(e["minutes_range"][0] <= e["minutes"] <= e["minutes_range"][1])
        self.assertEqual(e["basis"].startswith("measured"), True)

    def test_plan_pins_the_call_count(self):
        with open(os.path.join(FIXTURES, "village.json"), "r", encoding="utf-8") as f:
            plan = json.load(f)
        e = api.estimate(plan)
        zones = len(plan["zones"])
        buildings = sum(len(z["buildings"]) for z in plan["zones"])
        # P1, P2 + one P3 per own design + one P4 per zone + a P5 batch per
        # peopled zone + the player's call (village.json carries no frame;
        # King's Wood has no buildings, so it gets no batch)
        peopled = sum(1 for z in plan["zones"] if z["buildings"])
        self.assertEqual(e["calls"], 3 + buildings + zones + peopled + 1 + 3)
        self.assertEqual(e["calls_range"][0], e["calls"])
        self.assertGreater(e["calls_range"][1], e["calls"], "retries add calls")
        self.assertEqual(e["tokens"], 8500 * e["calls"])
        self.assertTrue(5 <= e["minutes"] <= 60, e)

    def test_a_framed_plan_counts_p0(self):
        with open(os.path.join(FIXTURES, "village.json"), "r", encoding="utf-8") as f:
            plan = json.load(f)
        plain = api.estimate(plan)["calls"]          # no frame: no P0 call
        plan["frame"] = {"premise": "x"}
        plan["questionnaire"] = {"mode": "short", "answers": {}, "population": [20, 40]}
        self.assertEqual(api.estimate(plan)["calls"], plain + 1)
        self.assertIn("1 P0 call", api.estimate(plan)["basis"])

    def test_plan_path_is_loaded(self):
        e = api.estimate(os.path.join(FIXTURES, "village.json"))
        self.assertTrue(e["basis"].startswith("plan"))


if __name__ == "__main__":
    unittest.main()
