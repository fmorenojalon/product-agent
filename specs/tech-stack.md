# Tech Stack — Product Agent

## Orchestration

**Custom Python orchestrator** built directly on the Anthropic SDK.

- No external agent framework. The orchestrator is a single Python module that sequences agent calls, passes shared context between them, and surfaces errors.
- Each skill is invoked by reading its `SKILL.md` as a Claude API system prompt, with the user message carrying the task input and any upstream context.
- A shared context dict is built up as the pipeline runs and passed forward to each subsequent agent.

```
orchestrator.py
  ├── pre-step: competitor + persona extraction  (plain Claude call)
  ├── calls product-analysis/      (UC-1)
  ├── calls product-user-feedback/ (UC-2 — after UC-1)
  ├── synthesis + proposal generation           (plain Claude call)
  ├── [human gate]
  ├── calls product-specification/ (UC-3 — context-injection mode)
  └── calls product-user-story/    (UC-4 — context-injection mode)
```

## Skill Invocation Model

Each skill's `SKILL.md` is read at runtime and used as the Claude API system prompt. No separate Python wrapper scripts — the orchestrator handles the agentic tool-use loop directly:

1. Send system prompt (SKILL.md) + user message to Claude API
2. If Claude calls a tool (`web_search`), execute it and feed results back
3. Repeat until Claude returns a final text response (stop_reason = `end_turn`)

A short suffix appended to every skill system prompt instructs Claude to output markdown (not PDF/DOCX) and skip interactive interview steps when running in pipeline mode.

## AI Model

- **Claude** (Anthropic) — all agents call the Claude API
- Models: Claude Haiku 5.5, Sonnet 5.5 and Opus 5.5, set per step and profile in `config.yaml`; a step that names none uses Haiku 5.5. See [models-and-effort.md](models-and-effort.md).
- Each skill runs in its own agentic loop; the orchestrator owns context accumulation and handoff

## Web Search

- **Anthropic hosted web search** (`web_search_20250305` tool)
- No extra API key or dependency — billed through the existing Anthropic API account
- Declared as a tool in each skill call; Anthropic executes searches server-side and embeds results in the response
- Claude decides when and what to search, exactly as in Claude.ai

## Integrations

Integrations are implemented as connector scripts in `connectors/`, keeping the integration surface simple and replaceable.

| Integration | Purpose | Phase 1 | Phase 2 |
|---|---|---|---|
| **Discord** | Read recent user feedback from configured channels | Mock (fixture data) | Real — Discord REST API |
| **Notion** | Create user stories as database rows | Mock (stdout) | Real — Notion API |

## Output Format

All pipeline outputs are saved as markdown files in a timestamped folder under `output/`:

```
output/
└── 2026-05-19_my-product-idea/
    ├── research-brief.md        # UC-1 competitive research
    ├── feedback-synthesis.md    # UC-2 user feedback report
    ├── product-spec.md          # UC-3 product specification
    └── user-stories.md          # UC-4 user stories
```

`.docx` generation is out of scope for the PoC. The markdown output is the primary deliverable.

## Language & Runtime

- **Python 3.11+**
- `anthropic` — Claude API SDK (includes hosted web search); pinned in `requirements.txt` because retry behaviour differs between SDK versions
- `python-dotenv` — secrets management (`.env`, never committed)

## Configuration

- Pipeline settings (model, Discord channels, Notion workspace) in `config.yaml`
- Secrets (API keys) in `.env`

## Observability (Phase 3)

Built into the orchestrator — no third-party APM required for the PoC:

- **Latency:** wall-clock time per agent call and per pipeline step
- **Cost attribution:** token counts from each Claude API response, mapped to agent name + task ID, converted to estimated USD
- **Handoff quality:** structured output validated at each handoff; degraded outputs surface warnings
- Metrics written to `output/<run>/run-metrics.jsonl`; summary printed at pipeline end

## Rate management and resilience (Phase 4)

Specified in [rate-management.md](rate-management.md):

- **Retries:** one wrapper (`api_call_with_retry` in `agent.py`) owns all retrying; SDK retries are disabled. It obeys `retry-after`, backs off otherwise, fails fast on errors a retry cannot fix, and limits total waiting.
- **Persistence:** each step is saved as it finishes, with a `run-state.json` for what the output files do not hold; `python orchestrator.py --resume <run folder>` continues a stopped run.
- **Request load:** every request is streamed. Searching steps send `max_uses` (the per-step `max_searches`) and use automatic prompt caching; `max_tokens` is a ceiling set above the expected output. See the constraints and limitations in [rate-management.md](rate-management.md).
- **Telemetry:** each step records its waiting time, its retries by kind and the least rate-limit allowance the API reported as left, read from the `anthropic-ratelimit-*` response headers. The fields are in `run-metrics.jsonl` and `run-report.md`.
