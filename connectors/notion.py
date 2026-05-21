"""Notion connector — writes UC-4 user stories to a Notion database."""

import os
import re
import json

from anthropic import Anthropic
from dotenv import set_key

try:
    from notion_client import Client as NotionClient
    _NOTION_AVAILABLE = True
except ImportError:
    _NOTION_AVAILABLE = False
    NotionClient = None  # type: ignore

_PARSE_MODEL = "claude-haiku-4-5-20251001"
_DB_TITLE = "Product Agent — User Stories"


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
    try:
        response = client.messages.create(
            model=_PARSE_MODEL,
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    "Extract all user stories from the markdown below. "
                    "Return a JSON array. Each object must have exactly these keys: "
                    '"title" (story name or As-a line), '
                    '"epic" (section or epic it belongs to), '
                    '"description" (full story text), '
                    '"acceptance_criteria" (criteria as a string, empty string if none). '
                    "Return ONLY valid JSON — no markdown fences, no explanation.\n\n"
                    f"{markdown}"
                ),
            }]
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception:
        return []


def ensure_database(client: "NotionClient", parent_page_id: str) -> str:
    """Return the Notion database ID to write stories to.

    Reuses NOTION_DATABASE_ID from .env if set; otherwise creates a new database
    under parent_page_id and persists the new ID back to .env.
    """
    db_id = os.getenv("NOTION_DATABASE_ID", "").strip()
    if db_id:
        return db_id

    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": _DB_TITLE}}],
        properties={
            "Title": {"title": {}},
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
            "Run": {"rich_text": {}},
        },
    )

    new_id = response["id"]
    try:
        set_key(".env", "NOTION_DATABASE_ID", new_id)
        print(f"  [ Notion ] Database created — ID saved to .env ({new_id})")
    except Exception:
        print(f"  [ Notion ] Database created. Add to .env: NOTION_DATABASE_ID={new_id}")

    return new_id


def push_stories(stories_markdown: str, run_id: str) -> None:
    """Parse UC-4 output and write one Notion database row per story.

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

        db_id = ensure_database(notion, parent_page_id)

        for story in stories:
            notion.pages.create(
                parent={"database_id": db_id},
                properties={
                    "Title": {
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
                    "Run": {"rich_text": [{"text": {"content": run_id}}]},
                },
            )

        print(f"  [ Notion ] {len(stories)} stories written")

    except Exception as e:
        print(f"  [ Notion ] Warning: write failed — {e}")
        print("  [ Notion ] Pipeline continuing; local files are unaffected")
