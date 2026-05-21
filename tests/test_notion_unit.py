#!/usr/bin/env python3
"""Unit tests for the Notion connector. No real API calls, no cost."""
import os
import unittest
from unittest.mock import MagicMock, patch

from connectors.notion import parse_stories, create_database, push_stories

# ── Fixtures ──────────────────────────────────────────────────────────────────

# Fixture A: new UC-4 format (### story headers, #### AC heading)
FIXTURE_MARKDOWN = """
## EPIC: User Onboarding

### Story 1: Sign up

| User Story | Files and Documentation |
|------------|------------------------|
| As a new user, I can create an account with my email. | Designs: TBD |

#### Background

Users need to create accounts to access communities.

#### Acceptance Criteria

## Email Validation
- Email must be validated on submit.
- Confirmation email is sent on success.

#### Linked Stories / Dependencies

- Story 2

---

### Story 2: Complete profile

| User Story | Files and Documentation |
|------------|------------------------|
| As a user, I can add my interests after signing up. | Designs: TBD |

#### Background

Capturing interests enables community recommendations.

#### Acceptance Criteria

## Interest Selection
- At least one interest is required before saving.
- Interests are persisted to the user profile.

#### Linked Stories / Dependencies

- Story 1

---

## EPIC: Community Discovery

### Story 3: Browse communities

| User Story | Files and Documentation |
|------------|------------------------|
| As a user, I can browse local communities by category. | Designs: TBD |

#### Background

Users need to find communities relevant to their location and interests.

#### Acceptance Criteria

## Category List
- Categories are listed on the discover screen.
- Tapping a category shows matching communities.
"""

# Fixture B: old UC-4 format (#### story headers, **AC** bold marker)
FIXTURE_MARKDOWN_OLD_FORMAT = """
## Epic 1: User Onboarding

#### Story 1.1: Sign up

| User Story | Files and Documentation |
|------------|------------------------|
| As a new user, I can create an account with my email. | Designs: TBD |

**Background**

Users need to create accounts to access communities.

**Acceptance Criteria**

- Email must be validated on submit.

**Linked Stories / Dependencies**

- Story 1.2
"""

# Notion API v2025 databases.create response includes data_sources
DB_CREATE_RESPONSE = {"id": "db-123", "data_sources": [{"id": "ds-abc"}]}

PARSED_FIXTURE = parse_stories(FIXTURE_MARKDOWN)
PARSED_FIXTURE_OLD = parse_stories(FIXTURE_MARKDOWN_OLD_FORMAT)


# ── parse_stories ─────────────────────────────────────────────────────────────

class TestParseStories(unittest.TestCase):

    def test_happy_path_story_count(self):
        self.assertEqual(len(PARSED_FIXTURE), 3)

    def test_title_extracted(self):
        self.assertEqual(PARSED_FIXTURE[0]["title"], "Story 1: Sign up")

    def test_epic_assigned_correctly(self):
        self.assertEqual(PARSED_FIXTURE[0]["epic"], "User Onboarding")
        self.assertEqual(PARSED_FIXTURE[2]["epic"], "Community Discovery")

    def test_description_is_verbatim_not_summary(self):
        desc = PARSED_FIXTURE[0]["description"]
        self.assertIn("Background", desc)
        self.assertIn("Users need to create accounts", desc)

    def test_acceptance_criteria_verbatim(self):
        ac = PARSED_FIXTURE[0]["acceptance_criteria"]
        self.assertIn("Email must be validated on submit", ac)

    def test_acceptance_criteria_excludes_linked_stories(self):
        ac = PARSED_FIXTURE[0]["acceptance_criteria"]
        self.assertNotIn("Linked Stories", ac)
        self.assertNotIn("Story 1.2", ac)

    def test_description_excludes_acceptance_criteria(self):
        desc = PARSED_FIXTURE[0]["description"]
        self.assertNotIn("Acceptance Criteria", desc)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(parse_stories(""), [])

    def test_whitespace_only_returns_empty_list(self):
        self.assertEqual(parse_stories("   \n  "), [])

    def test_markdown_without_story_headers_returns_empty(self):
        self.assertEqual(parse_stories("# Some doc\n\nNo stories here."), [])

    # ── Old format (#### story headers, **AC** bold) ──────────────────────────

    def test_old_format_story_count(self):
        self.assertEqual(len(PARSED_FIXTURE_OLD), 1)

    def test_old_format_title_extracted(self):
        self.assertEqual(PARSED_FIXTURE_OLD[0]["title"], "Story 1.1: Sign up")

    def test_old_format_epic_assigned(self):
        self.assertEqual(PARSED_FIXTURE_OLD[0]["epic"], "User Onboarding")

    def test_old_format_acceptance_criteria_extracted(self):
        ac = PARSED_FIXTURE_OLD[0]["acceptance_criteria"]
        self.assertIn("Email must be validated", ac)
        self.assertNotIn("Linked Stories", ac)


# ── create_database ───────────────────────────────────────────────────────────

class TestCreateDatabase(unittest.TestCase):

    def _make_client(self, db_id="new-db-xyz", ds_id="ds-abc"):
        mock_client = MagicMock()
        mock_client.databases.create.return_value = {
            "id": db_id,
            "data_sources": [{"id": ds_id}],
        }
        return mock_client

    def test_creates_database_with_given_name(self):
        mock_client = self._make_client()
        result = create_database(mock_client, "parent-page-123", "turnup — 2026-05-21 14:30")
        self.assertEqual(result, "new-db-xyz")
        mock_client.databases.create.assert_called_once()
        title_arg = mock_client.databases.create.call_args[1]["title"]
        self.assertEqual(title_arg[0]["text"]["content"], "turnup — 2026-05-21 14:30")

    def test_always_creates_new_database(self):
        mock_client = self._make_client()
        create_database(mock_client, "parent-page-123", "run 1")
        mock_client.databases.create.return_value = {"id": "db-2", "data_sources": [{"id": "ds-2"}]}
        create_database(mock_client, "parent-page-123", "run 2")
        self.assertEqual(mock_client.databases.create.call_count, 2)

    def test_schema_applied_via_data_sources_update(self):
        mock_client = self._make_client(ds_id="ds-abc")
        create_database(mock_client, "parent-page-123", "test db")
        mock_client.data_sources.update.assert_called_once()
        self.assertEqual(
            mock_client.data_sources.update.call_args[1]["data_source_id"], "ds-abc"
        )

    def test_created_database_has_all_required_columns(self):
        mock_client = self._make_client()
        create_database(mock_client, "parent-page-123", "test db")
        props = mock_client.data_sources.update.call_args[1]["properties"]
        for col in ("Epic", "Description", "Acceptance Criteria", "Status"):
            self.assertIn(col, props, f"Missing column: {col}")

    def test_no_run_column_in_schema(self):
        mock_client = self._make_client()
        create_database(mock_client, "parent-page-123", "test db")
        props = mock_client.data_sources.update.call_args[1]["properties"]
        self.assertNotIn("Run", props)


# ── push_stories ──────────────────────────────────────────────────────────────

class TestPushStories(unittest.TestCase):

    def _run(self, stories_md=FIXTURE_MARKDOWN, db_name="turnup — 2026-05-21 14:30"):
        mock_notion = MagicMock()
        mock_notion.databases.create.return_value = DB_CREATE_RESPONSE
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion):
            push_stories(stories_md, db_name)
        return mock_notion

    def test_skips_when_token_missing(self):
        mock_notion = MagicMock()
        env = {k: v for k, v in os.environ.items() if k not in ("NOTION_TOKEN", "NOTION_PARENT_PAGE_ID")}
        with patch.dict(os.environ, env, clear=True), \
             patch("connectors.notion.NotionClient", return_value=mock_notion):
            push_stories(FIXTURE_MARKDOWN, "some db")
        mock_notion.pages.create.assert_not_called()

    def test_creates_one_database_per_call(self):
        mock_notion = self._run()
        mock_notion.databases.create.assert_called_once()

    def test_database_name_passed_correctly(self):
        db_name = "turnup — 2026-05-21 14:30"
        mock_notion = self._run(db_name=db_name)
        title_arg = mock_notion.databases.create.call_args[1]["title"]
        self.assertEqual(title_arg[0]["text"]["content"], db_name)

    def test_row_count_matches_story_count(self):
        mock_notion = self._run()
        self.assertEqual(mock_notion.pages.create.call_count, 3)

    def test_field_mapping_correct(self):
        mock_notion = self._run()
        props = mock_notion.pages.create.call_args_list[0][1]["properties"]
        for field in ("Name", "Epic", "Description", "Acceptance Criteria", "Status"):
            self.assertIn(field, props, f"Missing field: {field}")
        self.assertEqual(props["Status"]["select"]["name"], "To Do")

    def test_description_content_is_verbatim(self):
        mock_notion = self._run()
        props = mock_notion.pages.create.call_args_list[0][1]["properties"]
        full_text = "".join(b["text"]["content"] for b in props["Description"]["rich_text"])
        self.assertIn("Users need to create accounts", full_text)

    def test_no_run_field_in_rows(self):
        mock_notion = self._run()
        props = mock_notion.pages.create.call_args_list[0][1]["properties"]
        self.assertNotIn("Run", props)

    def test_notion_failure_warns_and_does_not_raise(self):
        mock_notion = MagicMock()
        mock_notion.databases.create.side_effect = Exception("401 Unauthorized")
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion):
            push_stories(FIXTURE_MARKDOWN, "some db")  # must not raise

    def test_empty_markdown_skips_write(self):
        mock_notion = MagicMock()
        with patch.dict(os.environ, {"NOTION_TOKEN": "secret_t", "NOTION_PARENT_PAGE_ID": "pg-1"}), \
             patch("connectors.notion.NotionClient", return_value=mock_notion):
            push_stories("", "some db")
        mock_notion.pages.create.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
