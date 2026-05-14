# Implementation Plan — Product Agent

High-level phases. Each phase will be broken into detailed tasks separately.

---

## Phase 1 — Core Agent Pipeline

**Goal:** A working end-to-end orchestration flow from a user prompt to a generated spec and user stories, with a human decision gate in the middle. External connectors (Discord, Notion) are mocked so the full pipeline can run without live credentials.

**Scope:**
- Implement the Python orchestrator with the two-phase structure:
  - **Phase A (parallel):** Launch UC-1 (`product-analysis`) and UC-2 (`product-user-feedback`) concurrently from the user's initial prompt
  - **Synthesis step:** Orchestrator combines both outputs in a single Claude API call and generates 2–3 product direction proposals
  - **Human gate:** Present proposals in the CLI; wait for user selection before continuing
  - **Phase B (sequential):** Run UC-3 (`product-specification`) in context-injection mode using the confirmed direction + research artifacts, then UC-4 (`product-user-story`)
- Adapt each existing skill script to accept structured input from the orchestrator (consistent input/output contracts)
- Mock the Discord connector (return fixture data) and Notion connector (print stories to stdout)
- CLI entry point: `python orchestrator.py "idea"` runs the full pipeline

**Exit criteria:** Running `python orchestrator.py "idea"` completes the full flow — parallel research, proposal presentation, user selection, spec, and user story output — without errors.

---

## Phase 2 — Connector Integrations

**Goal:** Replace mock connectors with real integrations so the pipeline reads live Discord feedback and writes user stories to Notion.

**Scope:**
- **Discord connector:** Authenticate via Discord REST API; fetch recent messages from configured channels; inject into the UC-2 synthesis step alongside web-sourced feedback
- **Notion connector:** Authenticate via Notion API; create user stories as database rows or pages in a configured workspace
- `config.yaml` for connector settings (channel IDs, workspace IDs, model name)
- Secret management via `.env` (API keys never committed)
- End-to-end smoke test with real credentials

**Exit criteria:** A single `python orchestrator.py "idea"` run results in user stories appearing in the configured Notion workspace, with Discord feedback included in the UC-2 synthesis.

---

## Phase 3 — Observability

**Goal:** Make the pipeline's cost, latency, and handoff quality visible and attributable per agent and per run.

**Scope:**
- **Latency tracking:** Wall-clock time recorded around each agent call and the synthesis step
- **Cost attribution:** Input/output token counts extracted from each Claude API response, mapped to agent name and task ID; estimated USD cost computed per step
- **Handoff quality:** Structured output from each agent validated before passing downstream (schema check or confidence score); degraded handoffs surface actionable warnings rather than silently passing bad output
- **Logging:** All metrics written to a JSONL log file per run
- **Summary report:** Printed at pipeline end — total estimated cost, total latency, per-agent breakdown, and any handoff warnings

**Exit criteria:** Every pipeline run produces a JSONL log and a printed summary with per-agent cost and latency. Handoff failures produce visible warnings before the pipeline continues or halts.
