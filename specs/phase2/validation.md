# Phase 2 Validation Plan — Notion Connector

## Principle

No Phase 2 code merges until all gates below pass in order. The Phase 1 lesson: mock-only tests let broken integrations through at real cost. This plan adds a real-API smoke test gate before any full pipeline run.

---

## Gate 1 — Unit tests (zero cost, no real API)

All tests use mocked Notion client and pre-written fixture data. Run with:

```bash
python -m pytest tests/test_notion_unit.py -v
```

**Story parsing**
- [ ] `test_parse_stories_happy_path` — `parse_stories()` returns correct number of stories with Title, Epic, Description, Acceptance Criteria populated from a fixture markdown
- [ ] `test_parse_stories_empty_input` — empty string returns `[]`, no exception
- [ ] `test_parse_stories_malformed` — garbled markdown returns `[]` or a best-effort partial list, no exception

**Database creation**
- [ ] `test_ensure_database_creates` — when `NOTION_DATABASE_ID` is not set, `ensure_database()` calls Notion create API with the correct schema (all 6 columns, correct types)
- [ ] `test_ensure_database_reuses` — when `NOTION_DATABASE_ID` is set in env, `ensure_database()` skips creation and returns the existing ID

**Row creation**
- [ ] `test_push_stories_row_count` — `push_stories()` calls Notion page-create exactly N times for N stories
- [ ] `test_push_stories_field_mapping` — each created row has correct Title, Epic, Description, Acceptance Criteria, Status (`To Do`), and Run fields
- [ ] `test_push_stories_run_id` — the Run field matches the `run_id` passed to `push_stories()`

**Failure handling**
- [ ] `test_push_stories_auth_failure` — if the Notion client raises `APIResponseError` (e.g. 401), `push_stories()` prints a warning and returns without raising
- [ ] `test_push_stories_partial_failure` — if row creation fails on story 3 of 5, stories 1–2 are already written; warning is printed; no exception propagates to the orchestrator

---

## Gate 2 — Real API smoke test (minimal cost, real Notion)

Run against your real Notion workspace using a small hardcoded fixture (2 stories). Does not invoke the LLM or the full pipeline.

```bash
python -m pytest tests/test_notion_smoke.py -v
```

Preconditions: `NOTION_TOKEN` and `NOTION_PARENT_PAGE_ID` set in `.env`.

- [ ] Two rows appear in the Notion database after the test runs
- [ ] All six fields are populated correctly in Notion (verify by eye)
- [ ] Running the test a second time appends two more rows (expected — no deduplication)
- [ ] After the first run, `NOTION_DATABASE_ID` is written to `.env` (or printed with instructions to add it)
- [ ] Revoking the token and re-running prints a warning and exits 0 — does not crash

---

## Gate 3 — Pipeline integration test (profile 1, brief mode, ~$0.02)

Run the full pipeline in test mode to verify the Notion connector is correctly wired into the orchestrator.

```bash
python orchestrator.py idea.md   # select profile 1
```

- [ ] Pipeline completes without error
- [ ] `output/<run>/user-stories.md` is written locally
- [ ] At least one row appears in Notion (brief mode output is minimal but non-empty)
- [ ] The `Run` field in Notion rows matches the output folder timestamp
- [ ] If `NOTION_TOKEN` is missing from `.env`, pipeline prints a clear warning and continues — does not crash

---

## Gate 4 — Pre-merge code checklist

- [ ] `.env.example` updated with `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, `NOTION_DATABASE_ID`
- [ ] `requirements.txt` updated with `notion-client`
- [ ] No credentials or IDs hardcoded anywhere in source
- [ ] `connectors/notion.py` has no dead mock code remaining
- [ ] README updated with Notion setup instructions (create integration, share page, copy IDs)
- [ ] All Gate 1 tests pass with `pytest`

---

## Definition of Done

A single `python orchestrator.py idea.md` run (profile 3, balanced) results in:

1. All four local markdown files written to `output/<run>/`
2. User stories appearing in the Notion database with correct fields
3. Run timestamp in Notion matches the output folder name
4. If Notion is unreachable (network, bad token), the run still completes and local files are written
