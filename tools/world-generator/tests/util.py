"""Shared test helpers: build a fixture plan through the whole pipeline and
hand back the laid-out world, so layout tests assert on what the build measures
instead of re-running worldgen.run by hand."""
import json
import os

import worldgen

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load_plan(name):
    """The parsed JSON of a fixture plan."""
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def build_world(name, extensions=(), seed=1):
    """Build one fixture plan (with any extensions) and return the World."""
    return worldgen.run(load_plan(name), seed=seed, extensions=extensions)
