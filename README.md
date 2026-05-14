# Product Agent

## Intro

Product Agent helps product leads, product managers, and senior management working on strategy to take decisions or get in-depth insights about adding new products or features into their existing portfolio.

## Concept

A multi-agent system where Claude agents orchestrate end-to-end product management workflows. Five Claude skills (product-analysis, product-user-feedback, product-roadmap-fit, product-specification, product-user-story) are coordinated by a Python orchestrator to take a product idea from raw research all the way to Notion-ready user stories.

The pipeline has two phases separated by a human decision gate:

1. **Research phase (parallel):** competitive research + user feedback synthesis run simultaneously
2. **You choose a direction:** the agent presents 2–3 product proposals grounded in the research; you pick one
3. **Specification phase:** spec drafting and user story generation run sequentially from your confirmed direction

Integrations: Notion (user story output), Discord (user feedback input). Agent observability included: latency, cost attribution per agent, and handoff quality metrics.

---

## Usage

### Prerequisites

```bash
pip install anthropic python-dotenv
cp .env.example .env   # add your ANTHROPIC_API_KEY and connector credentials
```

### Run the pipeline

```bash
python orchestrator.py "your product idea or hypothesis"
```

### Examples

```bash
# Explore adding an AI writing assistant to an existing SaaS product
python orchestrator.py "AI writing assistant feature for our project management tool"

# Evaluate a payments product idea
python orchestrator.py "embedded buy-now-pay-later option for B2B invoicing"

# Research a new vertical
python orchestrator.py "mobile app targeting independent personal trainers"
```

### What happens when you run it

```
$ python orchestrator.py "AI writing assistant for our project management tool"

[1/2] Running competitive research...        ✓ (12s)
[2/2] Running user feedback synthesis...     ✓ (18s)

── Research complete. Here are 3 directions to consider: ──────────────────

Option 1 — Contextual AI suggestions
  Draft and improve task descriptions inline. Competitors (Asana, Linear) 
  have this but feedback shows users want tone/length control they don't offer.

Option 2 — Meeting-to-task AI
  Auto-generate tasks from meeting transcripts. High demand in Reddit threads,
  low competitive saturation at the mid-market tier.

Option 3 — Status update generator
  One-click stakeholder summaries from project state. Solves a pain point
  mentioned repeatedly in G2 reviews of competitors.

───────────────────────────────────────────────────────────────────────────
Which direction do you want to pursue? (1 / 2 / 3 or describe your own):
> 2

[3/3] Drafting product spec...               ✓ (21s)
[4/4] Generating user stories...             ✓ (14s)
      → Pushed 6 stories to Notion workspace

── Run complete ────────────────────────────────────────────────────────────
Total time: 1m 5s  |  Estimated cost: $0.08
Agents: research $0.03 · feedback $0.02 · spec $0.02 · stories $0.01
Output: ./output/2024-01-15_meeting-to-task-ai/
───────────────────────────────────────────────────────────────────────────
```

### Output files

Each run creates a timestamped folder under `./output/`:

```
output/
└── 2024-01-15_meeting-to-task-ai/
    ├── research-brief.md        # UC-1 competitive research
    ├── feedback-synthesis.md    # UC-2 user feedback report
    ├── product-spec.docx        # UC-3 product specification
    ├── user-stories.docx        # UC-4 user stories
    └── run-metrics.jsonl        # latency, cost, handoff quality per agent
```

---

## Configuration

| Key in `config.yaml` | Description |
|---|---|
| `model` | Claude model to use (default: `claude-sonnet-4-6`) |
| `discord.channels` | List of Discord channel IDs to pull feedback from |
| `notion.database_id` | Notion database where user stories are created |

Secrets (API keys) go in `.env` — never committed.

---

## Project structure

```
product-agent/
├── orchestrator.py              # main entry point
├── config.yaml                  # pipeline configuration
├── .env.example                 # secrets template
├── connectors/
│   ├── discord.py               # Discord feedback connector
│   └── notion.py                # Notion output connector
├── product-analysis/            # competitive research skill
├── product-user-feedback/       # user feedback synthesis skill
├── product-specification/       # spec drafting skill
├── product-user-story/          # user story generation skill
├── product-roadmap-fit/         # roadmap fit skill (future phase)
└── specs/                       # PRD, tech stack, implementation plan
```

