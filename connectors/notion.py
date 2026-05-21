"""Notion connector — writes UC-4 user stories to a new per-run Notion database."""

import os
import re

try:
    from notion_client import Client as NotionClient
    _NOTION_AVAILABLE = True
except ImportError:
    _NOTION_AVAILABLE = False
    NotionClient = None  # type: ignore


def _rich_text(text: str, chunk: int = 2000) -> list[dict]:
    """Split text into Notion rich_text blocks (2 000-char API limit per element)."""
    if not text:
        return [{"text": {"content": ""}}]
    return [{"text": {"content": text[i: i + chunk]}} for i in range(0, len(text), chunk)]


def parse_stories(markdown: str) -> list[dict]:
    """Extract stories from UC-4 markdown deterministically.

    Looks for '#### Story N.M: Title' headers nested under '## Epic N: Name' sections.
    Returns a list of dicts: title, epic, description, acceptance_criteria.
    Returns [] on empty input or if no story headers are found.
    """
    if not markdown.strip():
        return []

    lines = markdown.splitlines()
    current_epic = "General"
    story_spans: list[tuple[int, str, str]] = []  # (line_index, epic, title)

    for i, line in enumerate(lines):
        if re.match(r"^## (?!#)", line):
            current_epic = re.sub(r"^##\s+(?:Epic\s+\d+:\s*)?", "", line).strip()
        story_m = re.match(r"^####\s+(Story\s+[\d.]+:.+)", line)
        if story_m:
            story_spans.append((i, current_epic, story_m.group(1).strip()))

    stories = []
    for idx, (start, epic, title) in enumerate(story_spans):
        end = story_spans[idx + 1][0] if idx + 1 < len(story_spans) else len(lines)
        body = "\n".join(lines[start + 1: end]).strip()

        ac_parts = re.split(r"\*\*Acceptance Criteria\*\*", body, maxsplit=1)
        if len(ac_parts) == 2:
            description = ac_parts[0].strip()
            ac_remainder = ac_parts[1]
            linked_split = re.split(r"\*\*Linked Stories", ac_remainder, maxsplit=1)
            acceptance_criteria = linked_split[0].strip()
        else:
            description = body
            acceptance_criteria = ""

        stories.append({
            "title": title,
            "epic": epic,
            "description": description,
            "acceptance_criteria": acceptance_criteria,
        })

    return stories


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
                        "title": _rich_text(story.get("title", "Untitled"), chunk=2000)
                    },
                    "Epic": {
                        "select": {"name": story.get("epic", "General") or "General"}
                    },
                    "Description": {
                        "rich_text": _rich_text(story.get("description", ""))
                    },
                    "Acceptance Criteria": {
                        "rich_text": _rich_text(story.get("acceptance_criteria", ""))
                    },
                    "Status": {"select": {"name": "To Do"}},
                },
            )

        print(f"  [ Notion ] {len(stories)} stories written")

    except Exception as e:
        print(f"  [ Notion ] Warning: write failed — {e}")
        print("  [ Notion ] Pipeline continuing; local files are unaffected")
