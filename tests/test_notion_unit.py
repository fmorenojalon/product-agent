#!/usr/bin/env python3
"""
Unit tests for the Notion connector. No real API calls, no cost.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from connectors.notion import parse_stories, ensure_database, push_stories

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


# ── ensure_database ───────────────────────────────────────────────────────────

class TestEnsureDatabase(unittest.TestCase):

    def test_reuses_existing_id_without_calling_api(self):
        mock_client = MagicMock()
        with patch.dict(os.environ, {"NOTION_DATABASE_ID": "existing-db-abc"}):
            result = ensure_database(mock_client, "parent-page-123")
        self.assertEqual(result, "existing-db-abc")
        mock_client.databases.create.assert_not_called()

    def test_creates_database_when_id_not_set(self):
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "new-db-xyz"}
        env = {k: v for k, v in os.environ.items() if k != "NOTION_DATABASE_ID"}
        with patch.dict(os.environ, env, clear=True), \
             patch("connectors.notion.set_key"):
            result = ensure_database(mock_client, "parent-page-123")
        self.assertEqual(result, "new-db-xyz")
        mock_client.databases.create.assert_called_once()

    def test_created_database_has_all_required_columns(self):
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "new-db-xyz"}
        env = {k: v for k, v in os.environ.items() if k != "NOTION_DATABASE_ID"}
        with patch.dict(os.environ, env, clear=True), \
             patch("connectors.notion.set_key"):
            ensure_database(mock_client, "parent-page-123")
        props = mock_client.databases.create.call_args[1]["properties"]
        for col in ("Title", "Epic", "Description", "Acceptance Criteria", "Status", "Run"):
            self.assertIn(col, props, f"Missing column: {col}")

    def test_new_id_persisted_to_env(self):
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {"id": "new-db-xyz"}
        env = {k: v for k, v in os.environ.items() if k != "NOTION_DATABASE_ID"}
        with patch.dict(os.environ, env, clear=True), \
             patch("connectors.notion.set_key") as mock_set_key:
            ensure_database(mock_client, "parent-page-123")
        mock_set_key.assert_called_once_with(".env", "NOTION_DATABASE_ID", "new-db-xyz")


# ── push_stories ──────────────────────────────────────────────────────────────

class TestPushStories(unittest.TestCase):

    def _run(self, stories_md="markdown", run_id="2026-05-21_14-30"):
        mock_notion = MagicMock()
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=PARSED_FIXTURE), \
             patch("connectors.notion.ensure_database", return_value="db-123"):
            push_stories(stories_md, run_id)
        return mock_notion

    def test_skips_when_token_missing(self):
        mock_notion = MagicMock()
        env = {k: v for k, v in os.environ.items() if k not in ("NOTION_TOKEN", "NOTION_PARENT_PAGE_ID")}
        with patch.dict(os.environ, env, clear=True), \
             patch("connectors.notion.NotionClient", return_value=mock_notion):
            push_stories("markdown", "2026-05-21_14-30")
        mock_notion.pages.create.assert_not_called()

    def test_row_count_matches_story_count(self):
        mock_notion = self._run()
        self.assertEqual(mock_notion.pages.create.call_count, len(PARSED_FIXTURE))

    def test_run_id_in_every_row(self):
        run_id = "2026-05-21_14-30"
        mock_notion = self._run(run_id=run_id)
        for call in mock_notion.pages.create.call_args_list:
            props = call[1]["properties"]
            stored_run = props["Run"]["rich_text"][0]["text"]["content"]
            self.assertEqual(stored_run, run_id)

    def test_field_mapping_correct(self):
        mock_notion = self._run()
        first_call_props = mock_notion.pages.create.call_args_list[0][1]["properties"]
        self.assertIn("Title", first_call_props)
        self.assertIn("Epic", first_call_props)
        self.assertIn("Description", first_call_props)
        self.assertIn("Acceptance Criteria", first_call_props)
        self.assertIn("Status", first_call_props)
        self.assertIn("Run", first_call_props)
        self.assertEqual(first_call_props["Status"]["select"]["name"], "To Do")

    def test_notion_failure_warns_and_does_not_raise(self):
        """A Notion API error must print a warning, not propagate."""
        mock_notion = MagicMock()
        mock_notion.pages.create.side_effect = Exception("401 Unauthorized")
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=PARSED_FIXTURE), \
             patch("connectors.notion.ensure_database", return_value="db-123"):
            push_stories("markdown", "2026-05-21_14-30")  # must not raise

    def test_partial_failure_does_not_raise(self):
        """If a row fails mid-batch, the function catches and warns."""
        mock_notion = MagicMock()
        mock_notion.pages.create.side_effect = [None, Exception("timeout"), None]
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=PARSED_FIXTURE), \
             patch("connectors.notion.ensure_database", return_value="db-123"):
            push_stories("markdown", "2026-05-21_14-30")  # must not raise

    def test_empty_parse_result_skips_write(self):
        mock_notion = MagicMock()
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion), \
             patch("connectors.notion.parse_stories", return_value=[]), \
             patch("connectors.notion.ensure_database", return_value="db-123"):
            push_stories("", "2026-05-21_14-30")
        mock_notion.pages.create.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
