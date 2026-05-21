#!/usr/bin/env python3
"""
Format regression test: runs UC-4 (real API) and verifies parse_stories extracts stories.

Guards against the UC-4 skill changing its output format in a way that silently
breaks the Notion connector — parse_stories returns [] and no rows are written.

Cost per run: ~$0.02–0.05 (profile 1, brief mode, one epic scope)

Run with:
    RUN_FORMAT_TESTS=1 python -m pytest tests/test_uc4_parse.py -v
    RUN_FORMAT_TESTS=1 python -m pytest tests/test_uc4_parse.py -v -k test_parse -n 3

Skip by default (omit RUN_FORMAT_TESTS) to avoid accidental API spend.
"""
import os
import sys
import unittest
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Minimal spec — just enough for UC-4 to produce real stories
_FIXTURE_SPEC = """
# TurnUp MVP — Community Discovery

## Overview
TurnUp is a mobile app that lets people discover and join local hobby communities.

## Core feature: Community discovery
Users open the app, grant location permission, and see a map/list of local communities
(sports clubs, art groups, tech meetups) within 50 miles. They can filter by category
and keyword search, then tap through to a community page to join.

## Scope
- Map view: communities as map pins, tap to preview
- List view: paginated distance-sorted list
- Search & filter by category (Art, Music, Sports, Tech, Food) and distance
- Community preview page (name, description, member count, join button)

## Out of scope
- Authentication / sign-up flow
- Content posting inside communities
- Event creation
"""


@unittest.skipUnless(
    os.getenv("RUN_FORMAT_TESTS"),
    "Set RUN_FORMAT_TESTS=1 to run UC-4 format regression tests (costs ~$0.05/run)",
)
class TestUC4ParseFormat(unittest.TestCase):
    """Each test method calls UC-4 once and checks that parse_stories extracts stories."""

    @classmethod
    def _generate(cls) -> str:
        from agent import load_profile, run_skill
        from orchestrator import _STORIES_FORMAT

        profile = load_profile("1")  # brief mode — fastest and cheapest
        return run_skill(
            "product-user-story",
            f"Generate epics and user stories for the following product specification:"
            f"\n\n{_FIXTURE_SPEC}"
            f"\n\nIMPORTANT: Generate stories for ONE epic only — the single most critical epic."
            f"{_STORIES_FORMAT}",
            profile=profile,
            step="stories",
        )

    def _assert_parseable(self, raw: str, label: str = "") -> list[dict]:
        from connectors.notion import parse_stories

        stories = parse_stories(raw)
        tag = f" [{label}]" if label else ""

        # Fail loudly with the raw output so you can inspect the format
        self.assertGreater(
            len(stories), 0,
            f"parse_stories returned [] for UC-4 output{tag}.\n\n"
            f"--- RAW OUTPUT (first 3000 chars) ---\n{raw[:3000]}\n---",
        )
        for s in stories:
            for field in ("title", "epic", "description", "acceptance_criteria"):
                self.assertIn(field, s, f"Missing field '{field}' in story{tag}: {s}")
            self.assertTrue(s["title"].strip(), f"Empty title in story{tag}")
            self.assertTrue(s["epic"].strip(), f"Empty epic in story{tag}")
        return stories

    def test_run_1(self):
        raw = self._generate()
        stories = self._assert_parseable(raw, "run 1")
        print(f"\n  run 1: {len(stories)} stories, epic='{stories[0]['epic']}'")

    def test_run_2(self):
        raw = self._generate()
        stories = self._assert_parseable(raw, "run 2")
        print(f"\n  run 2: {len(stories)} stories, epic='{stories[0]['epic']}'")

    def test_run_3(self):
        raw = self._generate()
        stories = self._assert_parseable(raw, "run 3")
        print(f"\n  run 3: {len(stories)} stories, epic='{stories[0]['epic']}'")


if __name__ == "__main__":
    # Allow running directly: RUN_FORMAT_TESTS=1 python tests/test_uc4_parse.py
    os.environ.setdefault("RUN_FORMAT_TESTS", "1")
    unittest.main(verbosity=2)
