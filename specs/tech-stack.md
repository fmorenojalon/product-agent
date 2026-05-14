# Tech Stack — Product Agent

## Orchestration

**Custom Python orchestrator** built directly on the Anthropic SDK.

- No external agent framework. The orchestrator is a single Python module that sequences agent calls, passes shared context between them, and surfaces errors.
- Each of the five skills (`product-analysis`, `product-user-feedback`, `product-roadmap-fit`, `product-specification`, `product-user-story`) is invoked as a sub-agent via its existing script, called through direct import or subprocess.
- A shared context dictionary is built up as the pipeline runs and passed forward to each subsequent agent.

```
orchestrator.py
  ├── calls product-analysis/      (research agent)
  ├── calls product-user-feedback/ (feedback agent)
  ├── calls product-specification/ (spec agent)
  └── calls product-user-story/    (user story agent → Notion)
```

## AI Model

- **Claude** (Anthropic) — all agents call the Claude API
- Recommended model: `claude-sonnet-4-6` for cost/quality balance across pipeline steps
- Each agent turn is an independent API call; the orchestrator owns context accumulation

## Integrations

Integrations are implemented as skill scripts (not an MCP server), keeping the integration surface simple and replaceable.

| Integration | Purpose | Implementation |
|---|---|---|
| **Discord** | Read recent user feedback from configured channels | Python script using Discord REST API |
| **Notion** | Create tasks / user stories from pipeline output | Python script using Notion API |

Additional connectors (Intercom, App Store, etc.) will follow the same skill-script pattern in a later phase.

## Language & Runtime

- **Python 3.11+**
- `anthropic` SDK for all Claude API calls
- `httpx` or `requests` for integration scripts
- `python-dotenv` for secrets management (API keys in `.env`, never committed)

## Observability (Phase 3)

Built into the orchestrator itself — no third-party APM required for the PoC:

- **Latency**: wall-clock time recorded around each agent call
- **Cost attribution**: input/output token counts from each API response, mapped to agent name and task ID
- **Handoff quality**: structured output from each agent is validated before passing to the next (schema check or confidence score)
- All metrics written to a local JSONL log file; queryable with standard tooling

## Configuration

- API keys and connector credentials in `.env`
- Pipeline behaviour (model, enabled agents, Notion workspace, Discord channels) in `config.yaml`
