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
  - UC-3 (`product-specification`) runs in context-injection mode — upstream research (the full reports by default), the proposals and the confirmed direction are prepended as pre-filled context, bypassing the interactive interview. See [context-handling.md](context-handling.md).
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

**Exit criteria:** Running `python orchestrator.py idea.md` completes the full flow — pre-step extraction, sequential research, proposal presentation, user selection, spec, and user story output — with all artefacts saved to `output/`.

---

## Phase 2 — Connector Integrations

**Goal:** Replace mock connectors with real integrations so the pipeline reads live Discord feedback and writes user stories to Notion.

**Scope:**
- **Notion connector:** Authenticate via Notion API; create user stories as database rows in a configured workspace. One new database per run, named `"{title} — YYYY-MM-DD HH:MM"`.
- **Discord connector:** Dropped. `product-user-feedback` already runs `site:reddit.com` queries via Anthropic hosted web search; a Discord API integration would add a credential with no additional signal.
- Secret management via `.env` (`NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`).
- End-to-end smoke test with real credentials.

**Exit criteria:** A single `python orchestrator.py idea.md` run results in user stories appearing in the configured Notion workspace. If Notion is unreachable, the pipeline continues and local files are still written.

---

## Phase 3 — Observability

**Goal:** Make the pipeline's cost, latency, and handoff quality visible and attributable per agent and per run.

**Scope:**
- **Latency tracking:** Wall-clock time recorded around each agent call and the synthesis step.
- **Cost attribution:** Input, output, cache write, and cache read token counts extracted from each Claude API response; web search query count tracked; estimated USD computed per step including all charge types.
- **Handoff quality:** Each step's output validated before passing downstream via heuristic checks (all profiles) and an optional Haiku LLM confidence score (profiles 3 and 4). Failures prompt the user to continue or halt.
- **Logging:** Per-step metrics written to `output/<run>/run-metrics.jsonl` (one JSON object per step).
- **Run report:** Human-readable markdown table written to `output/<run>/run-report.md` alongside the existing output files.
- **Summary table:** Printed to the terminal at pipeline end — model, tokens in/out, search count, estimated cost, latency, and quality per step; footnote shows total cache and search charges.

**Exit criteria:** Every pipeline run produces `run-metrics.jsonl` and `run-report.md` in the output folder, and prints a per-step summary table to the terminal. Handoff failures produce visible warnings and prompt the user before the pipeline continues or halts.

**Files introduced in Phase 3:**
```
observability.py      # cost estimation, heuristic + LLM quality checks, RunTracker
tests/
  test_observability.py
```

---

## Phase 4 — Rate Management and Run Resilience

**Goal:** No API fault loses finished work, and no wait is silent or unbounded. Full requirements and design: [rate-management.md](rate-management.md).

**Scope:**
- **Per-step saving and resume:** every step's output is written as it finishes; `python orchestrator.py --resume <run folder>` skips finished steps.
- **Single retry policy:** one wrapper owns retrying, SDK retries are disabled, `retry-after` is obeyed, permanent errors fail fast, total waiting is bounded and visible.
- **Pinned SDK version.**
- **Stop-reason handling:** one loop runs skills and direct calls; it resumes paused search turns, continues past `max_tokens`, and raises on anything else instead of saving a partial output.
- **Request load:** the search cap is sent to the API as `max_uses`, steps that search use prompt caching, every request is streamed, and `max_tokens` ceilings are set above the expected output. There is no fixed pause between phases. The constraints that come with this are listed in rate-management.md.
- **Wait and limit telemetry:** each step records its active and waiting time, its retries by kind (rate-limited, server error, other) and the least input and output allowance the API reported as left, read from the rate-limit headers.

**Exit criteria:** Killing a run at any step and resuming repeats no finished step; a permanent API error makes exactly one request; every wait over 5 seconds is printed with its reason; a paused search turn is resumed and a refusal stops the run instead of saving a partial output; the search cap is enforced by the API and no fixed pause separates steps; each step's metrics separate its waiting from its working time.

**Files introduced in Phase 4:**
```
run_state.py                # RunState: step completion and values saved in run-state.json
specs/rate-management.md
tests/
  test_run_state.py
  test_resume.py
  test_stop_reasons.py
  test_request_load.py
  test_telemetry.py
  fakes.py
```
