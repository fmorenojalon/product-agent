# Phase 2 Requirements — Notion Connector

## Scope

Phase 2 replaces the mock Notion connector with a real integration. Discord and Reddit connectors are explicitly out of scope — the `product-user-feedback` skill already handles community feedback via web search (`site:reddit.com` queries), and adding API connectors for those sources would add credential overhead with no additional signal.

### In scope
- Notion API: write UC-4 user stories to a new Notion database
- Story parsing: extract structured story objects from the UC-4 markdown output via a Haiku LLM call
- Schema creation: connector creates the database on first run under a user-specified parent page
- Error handling: Notion failures warn and continue — local markdown files are always written
- Credentials: `NOTION_TOKEN` and `NOTION_PARENT_PAGE_ID` via `.env`

### Out of scope
- Discord connector (dropped)
- Reddit API connector (dropped)
- Pushing UC-3 spec to Notion (user stories only)
- Updating or deduplicating existing Notion rows (each run appends new rows)
- Two-way sync or approval workflows

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Discord/Reddit connector | Dropped | `product-user-feedback` already runs `site:reddit.com` searches via Anthropic hosted web search; API adds a new credential with no additional coverage |
| Notion output format | Database rows | Queryable, filterable, supports sprint tracking; more useful than a markdown page for actionable work |
| Notion schema | New database (connector creates it) | No existing task database; clean schema from the start |
| What goes to Notion | User stories only (UC-4) | Spec stays as a local markdown file; stories are the actionable artifact |
| Connector failure mode | Warn and continue | Local files are the primary deliverable; Notion is a convenience layer |
| Story extraction method | LLM-based (Haiku) | UC-4 markdown format can vary across runs; deterministic regex parsing is brittle; one Haiku call is cheap (~$0.001) and robust |

---

## Notion Database Schema

The connector creates this database under `NOTION_PARENT_PAGE_ID` on first run:

| Column | Notion Type | Notes |
|---|---|---|
| Title | title | Story name — the "As a… I want…" line |
| Epic | select | Epic the story belongs to |
| Description | rich_text | Full user story text |
| Acceptance Criteria | rich_text | Acceptance criteria list |
| Status | select | Default: `To Do` |
| Run | rich_text | Run timestamp (e.g. `2026-05-21_14-30`) for traceability |

---

## Credentials

Add to `.env`:

```
NOTION_TOKEN=secret_...          # Integration token from notion.so/my-integrations
NOTION_PARENT_PAGE_ID=...        # ID of the Notion page that will contain the database
```

Setup steps for the user:
1. Go to notion.so/my-integrations → create a new integration → copy the token
2. In Notion, open the page where you want the database → Share → Invite your integration
3. Copy the page ID from the URL (the 32-char hex after the last `/`)

---

## Implementation Plan

### `connectors/notion.py`

Replace the mock `push_stories()` with three functions:

| Function | Responsibility |
|---|---|
| `parse_stories(markdown, profile) -> list[dict]` | Haiku call — extracts structured story dicts from UC-4 markdown |
| `ensure_database(client, parent_page_id) -> str` | Creates the database with the schema above if it doesn't exist; returns database ID. Database ID is cached in `.env` after first creation (`NOTION_DATABASE_ID`) |
| `push_stories(stories_markdown, run_id) -> None` | Orchestrates parse → ensure_database → create one row per story |

### Dependencies

Add to `requirements.txt`:
```
notion-client
```

### Config changes

- `.env.example`: add `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, `NOTION_DATABASE_ID` (auto-populated after first run)
- `config.yaml`: no changes needed — Notion settings live in `.env` only
