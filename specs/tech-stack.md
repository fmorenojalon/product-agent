# Tech Stack — Product Agent

## Orchestration

**Custom Python orchestrator** built directly on the Anthropic SDK.

- No external agent framework. The orchestrator is a single Python module that sequences agent calls, passes shared context between them, and surfaces errors.
- Each skill is invoked by reading its `SKILL.md` as a Claude API system prompt, with the user message carrying the task input and any upstream context.
- A shared context dict is built up as the pipeline runs and passed forward to each subsequent agent.

```
orchestrator.py
  ├── pre-step: competitor + persona extraction  (plain Claude call)
  ├── calls product-analysis/      (UC-1 — parallel)
  ├── calls product-user-feedback/ (UC-2 — parallel)
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
- Default model: `claude-sonnet-4-6` (configurable in `config.yaml`)
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
- `anthropic` — Claude API SDK (includes hosted web search)
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
