#!/usr/bin/env python3
"""
Unit tests for the Notion connector. No real API calls, no cost.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from connectors.notion import parse_stories, create_database, push_stories

# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXTURE_MARKDOWN = """
## Epic 1: User Onboarding

**Story 1.1: Sign up**
As a new user, I can create an account with my email.
Acceptance Criteria:
- Email validation on submit
- Confirmation email sent

**Story 1.2: Complete profile**
As a user, I can add my interests after signing up.
Acceptance Criteria:
- At least one interest required
- Interests saved to my profile

## Epic 2: Community Discovery

**Story 2.1: Browse communities**
As a user, I can browse local communities by category.
Acceptance Criteria:
- Categories listed on discover screen
- Tapping a category shows matching communities
"""

PARSED_FIXTURE = [
    {
        "title": "Sign up",
        "epic": "User Onboarding",
        "description": "As a new user, I can create an account with my email.",
        "acceptance_criteria": "- Email validation on submit\n- Confirmation email sent",
    },
    {
        "title": "Complete profile",
        "epic": "User Onboarding",
        "description": "As a user, I can add my interests after signing up.",
        "acceptance_criteria": "- At least one interest required\n- Interests saved to my profile",
    },
    {
        "title": "Browse communities",
        "epic": "Community Discovery",
        "description": "As a user, I can browse local communities by category.",
        "acceptance_criteria": "- Categories listed on discover screen\n- Tapping a category shows matching communities",
    },
]


def _mock_anthropic(data: list) -> MagicMock:
    """Build a fake Anthropic client whose messages.create returns JSON of `data`."""
    block = MagicMock()
    block.text = json.dumps(data)
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


# ── parse_stories ─────────────────────────────────────────────────────────────

class TestParseStories(unittest.TestCase):

    def test_happy_path(self):
        with patch("connectors.notion.Anthropic", return_value=_mock_anthropic(PARSED_FIXTURE)):
            result = parse_stories(FIXTURE_MARKDOWN)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["title"], "Sign up")
        self.assertEqual(result[0]["epic"], "User Onboarding")
        self.assertIn("email", result[0]["description"])
        self.assertNotEqual(result[0]["acceptance_criteria"], "")

    def test_empty_input_returns_empty_list(self):
        result = parse_stories("")
        self.assertEqual(result, [])

    def test_whitespace_only_returns_empty_list(self):
        result = parse_stories("   \n  ")
        self.assertEqual(result, [])

    def test_malformed_llm_response_returns_empty_list(self):
        """Non-JSON LLM response must not raise — return []."""
        block = MagicMock()
        block.text = "sorry, I cannot do that"
        response = MagicMock()
        response.content = [block]
        client = MagicMock()
        client.messages.create.return_value = response
        with patch("connectors.notion.Anthropic", return_value=client):
            result = parse_stories(FIXTURE_MARKDOWN)
        self.assertEqual(result, [])

    def test_llm_failure_returns_empty_list(self):
        """If the Anthropic call raises, return [] without propagating."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("network error")
        with patch("connectors.notion.Anthropic", return_value=client):
            result = parse_stories(FIXTURE_MARKDOWN)
        self.assertEqual(result, [])

    def test_json_with_fences_is_parsed(self):
        """LLM sometimes wraps JSON in ```json fences — must strip them."""
        block = MagicMock()
        block.text = "```json\n" + json.dumps(PARSED_FIXTURE) + "\n```"
        response = MagicMock()
        response.content = [block]
        client = MagicMock()
        client.messages.create.return_value = response
        with patch("connectors.notion.Anthropic", return_value=client):
            result = parse_stories(FIXTURE_MARKDOWN)
        self.assertEqual(len(result), 3)


# ── create_database ───────────────────────────────────────────────────────────

class TestCreateDatabase(unittest.TestCase):

    def test_creates_database_with_given_name(self):
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "new-db-xyz"}
        result = create_database(mock_client, "parent-page-123", "turnup — 2026-05-21 14:30")
        self.assertEqual(result, "new-db-xyz")
        mock_client.databases.create.assert_called_once()
        title_arg = mock_client.databases.create.call_args[1]["title"]
        self.assertEqual(title_arg[0]["text"]["content"], "turnup — 2026-05-21 14:30")

    def test_always_creates_new_database(self):
        """Every call to create_database hits the API — no caching."""
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "db-1"}
        create_database(mock_client, "parent-page-123", "run 1")
        mock_client.databases.create.return_value = {"id": "db-2"}
        create_database(mock_client, "parent-page-123", "run 2")
        self.assertEqual(mock_client.databases.create.call_count, 2)

    def test_created_database_has_all_required_columns(self):
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "db-xyz"}
        create_database(mock_client, "parent-page-123", "test db")
        props = mock_client.databases.create.call_args[1]["properties"]
        for col in ("Title", "Epic", "Description", "Acceptance Criteria", "Status"):
            self.assertIn(col, props, f"Missing column: {col}")

    def test_no_run_column_in_schema(self):
        """Run column was removed — each database IS the run."""
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "db-xyz"}
        create_database(mock_client, "parent-page-123", "test db")
        props = mock_client.databases.create.call_args[1]["properties"]
        self.assertNotIn("Run", props)


# ── push_stories ──────────────────────────────────────────────────────────────

class TestPushStories(unittest.TestCase):

    def _run(self, stories_md="markdown", db_name="turnup — 2026-05-21 14:30"):
        mock_notion = MagicMock()
        mock_notion.databases.create.return_value = {"id": "db-123"}
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=PARSED_FIXTURE):
            push_stories(stories_md, db_name)
        return mock_notion

    def test_skips_when_token_missing(self):
        mock_notion = MagicMock()
        env = {k: v for k, v in os.environ.items() if k not in ("NOTION_TOKEN", "NOTION_PARENT_PAGE_ID")}
        with patch.dict(os.environ, env, clear=True), \
             patch("connectors.notion.NotionClient", return_value=mock_notion):
            push_stories("markdown", "some db")
        mock_notion.pages.create.assert_not_called()

    def test_creates_one_database_per_call(self):
        mock_notion = self._run()
        mock_notion.databases.create.assert_called_once()

    def test_database_name_passed_correctly(self):
        db_name = "turnup — 2026-05-21 14:30"
        mock_notion = MagicMock()
        mock_notion.databases.create.return_value = {"id": "db-123"}
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=PARSED_FIXTURE):
            push_stories("markdown", db_name)
        title_arg = mock_notion.databases.create.call_args[1]["title"]
        self.assertEqual(title_arg[0]["text"]["content"], db_name)

    def test_row_count_matches_story_count(self):
        mock_notion = self._run()
        self.assertEqual(mock_notion.pages.create.call_count, len(PARSED_FIXTURE))

    def test_field_mapping_correct(self):
        mock_notion = self._run()
        props = mock_notion.pages.create.call_args_list[0][1]["properties"]
        for field in ("Title", "Epic", "Description", "Acceptance Criteria", "Status"):
            self.assertIn(field, props, f"Missing field: {field}")
        self.assertEqual(props["Status"]["select"]["name"], "To Do")

    def test_no_run_field_in_rows(self):
        """Run column was removed from schema and row properties."""
        mock_notion = self._run()
        props = mock_notion.pages.create.call_args_list[0][1]["properties"]
        self.assertNotIn("Run", props)

    def test_notion_failure_warns_and_does_not_raise(self):
        mock_notion = MagicMock()
        mock_notion.databases.create.side_effect = Exception("401 Unauthorized")
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=PARSED_FIXTURE):
            push_stories("markdown", "some db")  # must not raise

    def test_empty_parse_result_skips_write(self):
        mock_notion = MagicMock()
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=[]):
            push_stories("", "some db")
        mock_notion.pages.create.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
