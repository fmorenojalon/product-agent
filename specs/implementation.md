# Implementation Plan — Product Agent

High-level phases. Each phase will be broken into detailed tasks separately.

---

## Phase 1 — Core Agent Pipeline

**Goal:** A working end-to-end orchestration flow from a user prompt to a generated spec and user stories, with a human decision gate in the middle. External connectors (Discord, Notion) are mocked so the full pipeline can run without live credentials.

**Scope:**

- **Pre-step:** A fast Claude call extracts 2–3 competitor names and a target persona from the raw user idea, providing precise inputs to the downstream skills.

- **Brave Search tool:** Implemented as a `web_search` tool (Brave Search API free tier) available to UC-1 and UC-2. Claude decides when and what to search, replicating the Claude.ai experience via the API.

- **Skill invocation:** Each skill's `SKILL.md` is used as the Claude API system prompt. The orchestrator runs an agentic tool-use loop (send → handle tool calls → repeat until `end_turn`) for each skill. A pipeline-mode suffix appended to every skill prompt instructs Claude to output markdown and skip interactive steps.

- **Phase A (parallel):** UC-1 (`product-analysis`) and UC-2 (`product-user-feedback`) run concurrently via `ThreadPoolExecutor`.

- **Synthesis step:** The orchestrator combines both research outputs in a single Claude call and generates 2–3 product direction proposals.

- **Human gate:** Proposals are printed to the CLI; the user types a selection before the pipeline continues.

- **Phase B (sequential):**
  - UC-3 (`product-specification`) runs in context-injection mode — upstream research and the confirmed direction are prepended as pre-filled context, bypassing the interactive interview.
  - UC-4 (`product-user-story`) runs next with UC-3's output. The mandatory clarification step is bypassed via the same pipeline-mode instruction.

- **Mock connectors:** Discord returns fixture data; Notion prints to stdout.

- **Output:** All artefacts saved as markdown files in `output/<date>_<slug>/`.

- **CLI entry point:** `python orchestrator.py "idea"` runs the full pipeline.

**Files introduced in Phase 1:**
```
orchestrator.py       # main entry point and pipeline logic
agent.py              # skill runner (agentic loop + Brave Search tool)
connectors/
  __init__.py
  discord.py          # mock Discord connector
  notion.py           # mock Notion connector
config.yaml           # model and connector settings
.env.example          # secrets template
requirements.txt
output/               # generated artefacts (gitignored)
```

**Exit criteria:** Running `python orchestrator.py "idea"` completes the full flow — pre-step extraction, parallel research, proposal presentation, user selection, spec, and user story output — with all artefacts saved to `output/`.

---

## Phase 2 — Connector Integrations

**Goal:** Replace mock connectors with real integrations so the pipeline reads live Discord feedback and writes user stories to Notion.

**Scope:**
- **Discord connector:** Authenticate via Discord REST API; fetch recent messages from configured channels; inject into the UC-2 synthesis step alongside web-sourced feedback.
- **Notion connector:** Authenticate via Notion API; create user stories as database rows or pages in a configured workspace.
- `config.yaml` fully wired: channel IDs, Notion database ID, model name.
- Secret management via `.env`.
- End-to-end smoke test with real credentials.

**Exit criteria:** A single `python orchestrator.py "idea"` run results in user stories appearing in the configured Notion workspace, with Discord feedback included in the UC-2 synthesis.

---

## Phase 3 — Observability

**Goal:** Make the pipeline's cost, latency, and handoff quality visible and attributable per agent and per run.

**Scope:**
- **Latency tracking:** Wall-clock time recorded around each agent call and the synthesis step.
- **Cost attribution:** Input/output token counts extracted from each Claude API response, mapped to agent name and task ID; estimated USD cost computed per step.
- **Handoff quality:** Structured output from each agent validated before passing downstream (schema check or confidence score); degraded handoffs surface actionable warnings.
- **Logging:** All metrics written to `output/<run>/run-metrics.jsonl`.
- **Summary report:** Printed at pipeline end — total estimated cost, total latency, per-agent breakdown, and any handoff warnings.

**Exit criteria:** Every pipeline run produces a JSONL metrics log and a printed summary with per-agent cost and latency. Handoff failures produce visible warnings before the pipeline continues or halts.
