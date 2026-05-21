"""Notion connector — writes UC-4 user stories to a new per-run Notion database."""

import os
import re
import json

from anthropic import Anthropic
from agent import api_call_with_retry

try:
    from notion_client import Client as NotionClient
    _NOTION_AVAILABLE = True
except ImportError:
    _NOTION_AVAILABLE = False
    NotionClient = None  # type: ignore

_PARSE_MODEL = "claude-haiku-4-5-20251001"


def _trunc(text: str, limit: int = 2000) -> str:
    return text[:limit] if len(text) > limit else text


def parse_stories(markdown: str) -> list[dict]:
    """Extract structured story objects from UC-4 markdown using Haiku.

    Returns a list of dicts with keys: title, epic, description, acceptance_criteria.
    Returns [] on empty input or if the LLM response cannot be parsed.
    """
    if not markdown.strip():
        return []

    client = Anthropic()
    # Keep title/epic/AC only — omit description to stay well within the output
    # token budget regardless of how many stories the spec produced.
    prompt = (
        "Extract all user stories from the markdown below. "
        "Return a JSON array. Each object must have exactly these keys: "
        '"title" (story name, short), '
        '"epic" (section or epic it belongs to), '
        '"description" (one sentence summary of the story), '
        '"acceptance_criteria" (acceptance criteria as a single string, empty string if none). '
        "Return ONLY valid JSON — no markdown fences, no explanation.\n\n"
        f"{markdown}"
    )
    try:
        response = api_call_with_retry(
            lambda: client.messages.create(
                model=_PARSE_MODEL,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        print(f"  [ Notion ] Warning: story parsing failed — {e}")
        return []


def create_database(client: "NotionClient", parent_page_id: str, db_name: str) -> str:
    """Create a new Notion database under parent_page_id and return its ID.

    The Notion API (2025) separates databases (views) from data sources (schema).
    databases.create no longer accepts a properties argument — the schema must be
    applied via data_sources.update on the auto-created data source.
    """
    db_resp = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": db_name}}],
    )
    db_id = db_resp["id"]
    ds_id = db_resp["data_sources"][0]["id"]

    client.data_sources.update(
        data_source_id=ds_id,
        properties={
            "Epic": {"select": {}},
            "Description": {"rich_text": {}},
            "Acceptance Criteria": {"rich_text": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "To Do", "color": "gray"},
                        {"name": "In Progress", "color": "blue"},
                        {"name": "Done", "color": "green"},
                    ]
                }
            },
        },
    )
    return db_id


def push_stories(stories_markdown: str, db_name: str) -> None:
    """Parse UC-4 output and write one Notion database row per story.

    Creates a new database named db_name under NOTION_PARENT_PAGE_ID on every call.
    Silently skips if credentials are not configured.
    Warns and continues if the Notion write fails for any reason.
    """
    token = os.getenv("NOTION_TOKEN", "").strip()
    parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID", "").strip()

    if not token or not parent_page_id:
        print("  [ Notion ] Skipping — NOTION_TOKEN or NOTION_PARENT_PAGE_ID not set in .env")
        return

    if not _NOTION_AVAILABLE:
        print("  [ Notion ] Warning: notion-client not installed. Run: pip install notion-client")
        return

    try:
        notion = NotionClient(auth=token)
        stories = parse_stories(stories_markdown)

        if not stories:
            print("  [ Notion ] No stories extracted from output — skipping write")
            return

        db_id = create_database(notion, parent_page_id, db_name)
        print(f"  [ Notion ] Created database '{db_name}'")

        for story in stories:
            notion.pages.create(
                parent={"database_id": db_id},
                properties={
                    "Name": {
                        "title": [{"text": {"content": _trunc(story.get("title", "Untitled"))}}]
                    },
                    "Epic": {
                        "select": {"name": story.get("epic", "General") or "General"}
                    },
                    "Description": {
                        "rich_text": [{"text": {"content": _trunc(story.get("description", ""))}}]
                    },
                    "Acceptance Criteria": {
                        "rich_text": [{"text": {"content": _trunc(story.get("acceptance_criteria", ""))}}]
                    },
                    "Status": {"select": {"name": "To Do"}},
                },
            )

        print(f"  [ Notion ] {len(stories)} stories written")

    except Exception as e:
        print(f"  [ Notion ] Warning: write failed — {e}")
        print("  [ Notion ] Pipeline continuing; local files are unaffected")
