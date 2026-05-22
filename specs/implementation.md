# Implementation Plan — Product Agent

High-level phases. Each phase will be broken into detailed tasks separately.

---

## Phase 1 — Core Agent Pipeline

**Goal:** A working end-to-end orchestration flow from a user prompt to a generated spec and user stories, with a human decision gate in the middle. External connectors (Discord, Notion) are mocked so the full pipeline can run without live credentials.

**Scope:**

- **Input:** A free-form markdown document (`idea.md` by default, or any `.md` file passed as a CLI argument). The full document content is passed as context to every pipeline step, giving the agent rich input from the start.

- **Pre-step:** A fast Claude call reads the input document and extracts 2–3 competitor names and a target persona, providing precise inputs to the downstream skills.

- **Anthropic hosted web search:** Declared as `web_search_20250305` tool available to UC-1 and UC-2. Executed server-side by Anthropic — no extra API key or dependency required.

- **Skill invocation:** Each skill's `SKILL.md` is used as the Claude API system prompt. The orchestrator runs an agentic tool-use loop (send → handle tool calls → repeat until `end_turn`) for each skill. A pipeline-mode suffix appended to every skill prompt instructs Claude to output markdown and skip interactive steps.

- **Phase A (sequential):** UC-1 (`product-analysis`) runs first, then UC-2 (`product-user-feedback`). Originally designed as parallel but kept sequential to stay within the API's tokens-per-minute rate limit.

- **Synthesis step:** The orchestrator combines both research outputs in a single Claude call and generates 2–3 product direction proposals.

- **Human gate:** Proposals are printed to the CLI; the user types a selection before the pipeline continues.

- **Phase B (sequential):**
  - UC-3 (`product-specification`) runs in context-injection mode — upstream research and the confirmed direction are prepended as pre-filled context, bypassing the interactive interview.
  - UC-4 (`product-user-story`) runs next with UC-3's output. The mandatory clarification step is bypassed via the same pipeline-mode instruction.

- **Mock connectors:** Discord returns fixture data; Notion prints to stdout.

- **Output:** All artefacts saved as markdown files in `output/<date>_<slug>/`.

- **Story scope prompt:** After mode selection, the user is asked `Scope (F/1)` — `F` generates all epics and stories (production run), `1` limits UC-4 to the single most important epic (useful for faster/cheaper test runs).

- **CLI entry point:** `python orchestrator.py idea.md` runs the full pipeline. Defaults to `idea.md` if no argument is given.

**Files introduced in Phase 1:**
```
orchestrator.py       # main entry point and pipeline logic
agent.py              # skill runner (agentic loop + Anthropic hosted web search)
connectors/
  __init__.py
  discord.py          # stub connector (Discord integration dropped in Phase 2)
  notion.py           # Notion connector (real integration added in Phase 2)
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
- **Handoff quality:** Each step's output validated before passing downstream via heuristic checks (all profiles) and an optional Haiku LLM confidence score (profiles 3 and 4). Failures prompt the user to continue or halt.
- **Logging:** Per-step metrics written to `output/<run>/run-metrics.jsonl` (one JSON object per step).
- **Run report:** Human-readable markdown table written to `output/<run>/run-report.md` alongside the existing output files.
- **Summary table:** Printed to the terminal at pipeline end — model, tokens in/out, estimated cost, latency, and quality per step.

**Exit criteria:** Every pipeline run produces `run-metrics.jsonl` and `run-report.md` in the output folder, and prints a per-step summary table to the terminal. Handoff failures produce visible warnings and prompt the user before the pipeline continues or halts.

**Files introduced in Phase 3:**
```
observability.py      # cost estimation, heuristic + LLM quality checks, RunTracker
tests/
  test_observability.py
```
