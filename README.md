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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
```

### 1. Write your idea document

Copy the template and fill it in — or just write freely. There is no required structure.

```bash
cp idea-template.md idea.md
```

Open `idea.md` and write whatever you know about the idea: the concept, context, target users, known constraints, open questions, competitors you're aware of. A few sentences or several pages — both work.

### 2. Run the pipeline

```bash
# Uses idea.md by default
python orchestrator.py

# Or pass a specific file
python orchestrator.py my-feature-idea.md
```

### What happens when you run it

```
$ python orchestrator.py idea.md

Product Agent  ·  idea.md

[ Pre-step ] Identifying competitors and persona...
  Competitors : Asana, Linear, Monday.com
  Persona     : project manager

[ Phase A ] Competitive research + user feedback running in parallel...
  ✓ Competitive research complete
  ✓ User feedback synthesis complete

[ Synthesis ] Generating product direction proposals...

──────────────────────────────────────────────────────────────────────
Option 1 — Contextual AI suggestions
  Draft and improve task descriptions inline. Competitors have this but
  feedback shows users want tone/length control they don't offer.

Option 2 — Meeting-to-task AI
  Auto-generate tasks from meeting transcripts. High demand in Reddit
  threads, low competitive saturation at the mid-market tier.

Option 3 — Status update generator
  One-click stakeholder summaries from project state. Repeatedly
  requested in G2 reviews of competitors.
──────────────────────────────────────────────────────────────────────

Which direction do you want to pursue? (enter a number or describe your choice):
> 2

[ Phase B ] Drafting product spec...
  ✓ Spec complete

[ Phase B ] Generating user stories...
  ✓ User stories complete

[ Notion ] Mock — stories would be pushed to Notion in Phase 2.

──────────────────────────────────────────────────────────────────────
  Run complete
  Output folder : output/2026-05-19_idea/
  Files         : research-brief.md · feedback-synthesis.md
                  product-spec.md · user-stories.md
──────────────────────────────────────────────────────────────────────
```

### Output files

Each run creates a timestamped folder under `./output/` named after your input file:

```
output/
└── 2026-05-19_idea/
    ├── research-brief.md        # UC-1 competitive research
    ├── feedback-synthesis.md    # UC-2 user feedback report
    ├── product-spec.md          # UC-3 product specification
    └── user-stories.md          # UC-4 user stories
```

---

## Input document

The input document is intentionally free-form. You can follow the structure in `idea-template.md` or ignore it entirely. Useful things to include:

- The core idea in your own words
- Why now — what triggered this
- Who it's for and what problem they have today
- What you already know (customer quotes, data, prior experiments)
- Constraints (budget, timeline, team, tech)
- Competitors or similar products you're aware of
- Open questions you want the research to help answer

The richer the document, the more grounded the proposals and spec will be.

---

## Configuration

### Run profiles

At startup you are prompted to choose a run profile. Profiles are defined in `config.yaml` and control the model, token budget, and web-search limit for each pipeline step.

| # | Name | Est. cost/run | Notes |
|---|---|---|---|
| 1 | Test — pipeline validation | $0.01–0.04 | Haiku, no search, short placeholder output. Validates the full pipeline runs end-to-end. |
| 2 | Budget — full run, all Haiku | $0.30–0.60 | Complete pipeline with web search using the fastest, cheapest model. |
| 3 | Balanced — Sonnet for quality steps | $1.20–2.00 | Sonnet for research, feedback, spec, and stories. Best cost/quality trade-off. |
| 4 | Optimal — Opus for research, Sonnet elsewhere | $3.50–6.00 | Deepest research quality. Recommended for high-stakes decisions. |

Each profile configures per-step `model`, `max_tokens`, and `max_searches`. To customise, edit `config.yaml` directly.

### Other settings

| Key | Description |
|---|---|
| `discord.channels` | Discord channel IDs to pull feedback from (Phase 2) |
| `notion.database_id` | Notion database for user stories (Phase 2) |

Secrets (API keys) go in `.env` — never committed.

---

## Project structure

```
product-agent/
├── orchestrator.py              # main entry point
├── agent.py                     # skill runner and agentic loop
├── idea-template.md             # starter template for input documents
├── idea.md                      # your input document (gitignored)
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
