# Product Agent

## Intro

An AI product-research pipeline that takes a product idea from raw research to Notion-ready user stories. Claude skills coordinated by a Python orchestrator, with a human decision gate between research and specification.

Product Agent helps product leads, product managers, and senior management working on strategy to take decisions or get in-depth insights about adding new products or features into their existing portfolio.

## Concept

An agentic system where a Python orchestrator coordinates five Claude skills (product-analysis, product-user-feedback, product-roadmap-fit, product-specification, product-user-story) to take a product idea from raw research all the way to Notion-ready user stories.

The pipeline has two phases separated by a human decision gate:

1. **Research phase:** competitive research + user feedback synthesis run sequentially
2. **You choose a direction:** the agent presents 2–3 product proposals grounded in the research; you pick one
3. **Specification phase:** spec drafting and user story generation run sequentially from your confirmed direction

Integrations: Notion (user story output). Observability included: per-step latency, cost attribution (input, cache, and search charges), and handoff quality checks with interactive failure prompts.

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

[ Phase A ] Competitive research + user feedback...
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

──────────────────────────────────────────────────────────────────────
  Run summary
──────────────────────────────────────────────────────────────────────
  ──────────────────────────────────────────────────────────────────────────────────────
  Step         Model      In tok  Out tok  Srch      Cost  Latency    Wait  Quality
  ──────────────────────────────────────────────────────────────────────────────────────
  research     sonnet      4,821    3,102     4  $ 0.0612    18.3s       -  ✓
  feedback     sonnet      3,944    2,871     3  $ 0.0532    15.1s    8.2s  ✓
  synthesis    haiku       1,203      412     -  $ 0.0026     3.1s       -  ✓
  spec         sonnet      6,203    5,441     -  $ 0.0558    22.7s       -  ✓
  stories      sonnet      7,102    4,983     -  $ 0.0593    26.2s       -  ✓
  ──────────────────────────────────────────────────────────────────────────────────────
  TOTAL                   23,273   16,809     7  $ 0.2321    85.4s    8.2s
  ──────────────────────────────────────────────────────────────────────────────────────
  * cost includes cache write (9,813 tok) + cache read (10,225 tok) + 7 search(es)
  * 1 retry, 8s waiting: 1 rate-limited, 0 server errors, 0 other
  * lowest input-token allowance left: 1,984,000 of 2,000,000 (research)
  * lowest output-token allowance left: 398,000 of 400,000 (spec)

──────────────────────────────────────────────────────────────────────
  Run complete
──────────────────────────────────────────────────────────────────────
  Profile       : Balanced — Sonnet for quality steps
  Output folder : output/2026-05-19_idea/
  Files         : research-brief.md · feedback-synthesis.md
                  proposals.md · product-spec.md · user-stories.md
                  run-report.md · run-metrics.jsonl · run-state.json
──────────────────────────────────────────────────────────────────────
```

### Output files

Each run creates a timestamped folder under `./output/` named after your input file:

```
output/
└── 2026-05-19_idea/
    ├── research-brief.md        # UC-1 competitive research
    ├── feedback-synthesis.md    # UC-2 user feedback report
    ├── proposals.md             # the product directions you chose between
    ├── product-spec.md          # UC-3 product specification
    ├── user-stories.md          # UC-4 user stories
    ├── run-report.md            # per-step cost, latency (working vs waiting), retries, quality
    ├── run-metrics.jsonl        # machine-readable metrics (one JSON object per step)
    └── run-state.json           # what --resume needs (choices, finished steps)
```

Files are written as each step finishes, so a run that stops part-way keeps everything it completed.

### Resuming a stopped run

If a run stops — an API error that retrying cannot fix, a quality check you declined, or Ctrl-C — the pipeline prints the exact command to continue:

```bash
python orchestrator.py --resume output/2026-05-19_14-03_idea
```

Your profile, mode, story scope and direction choice are remembered, and finished steps are loaded from disk instead of being paid for again. The step that was interrupted runs again from its start.

### API errors and rate limits

The pipeline owns all retrying. It waits as long as the API's `retry-after` says (or backs off when there is none), prints every wait over 5 seconds with the reason, and gives up after 15 minutes of total waiting. There is no fixed pause between steps: it waits only when the API says so. Errors a retry cannot fix — a bad request, a rejected key, a billing problem, a spend limit — stop the run immediately. So does a model refusal, or any ending that would leave an output incomplete: the run stops with the reason instead of saving a partial output. A search turn the API paused is resumed automatically. Details: [specs/rate-management.md](specs/rate-management.md).

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
| 2 | Budget — full run, all Haiku | $0.10–0.60 | Complete pipeline with web search using the fastest, cheapest model. |
| 3 | Balanced — Sonnet for quality steps | $0.20–2.00 | Sonnet for research, feedback, spec, and stories. Best cost/quality trade-off. |
| 4 | Optimal — Opus for research, Sonnet elsewhere | $3.50–6.00 | Deepest research quality. Recommended for high-stakes decisions. |

Each profile configures per-step `model`, `max_tokens`, and `max_searches`. To customise, edit `config.yaml` directly; the file explains each setting.

- **`max_searches` is a hard cap.** It is sent to the API, which stops searching at that number. Each search adds roughly 9,000 to 12,000 input tokens (measured twice), so a lower number is cheaper and faster but narrows the research. At a low rate-limit tier, a step's searches must fit within one minute of input allowance, or the step can never pass.
- **`max_tokens` is a ceiling, not a budget.** It is billed only when used and does not count toward the output rate limit. Profiles 2–4 set it above the expected output, so a step normally finishes in one request; profile 1 keeps small ceilings on purpose.
- **Steps that search use prompt caching.** The other steps do not: they make a single request, so caching would only add its write premium. How much caching saves has not been measured.
- **Costs shown are rough.** The estimates above have not been measured with these settings, and the cost table in the run summary uses out-of-date rates for Haiku 4.5 and Opus 4.7, so its totals are not reliable.

All known limits are listed in [specs/rate-management.md](specs/rate-management.md#constraints-and-limitations).

### Notion setup

User stories are pushed to Notion at the end of every run. Add these to your `.env`:

```
NOTION_TOKEN=secret_...          # Integration token from notion.so/my-integrations
NOTION_PARENT_PAGE_ID=...        # ID of the Notion page that will contain all run databases
```

Setup steps:
1. Go to [notion.so/my-integrations](https://notion.so/my-integrations) → create a new integration → copy the token
2. In Notion, open the page where you want the databases → Share → Invite your integration
3. Copy the page ID from the URL (the 32-char hex after the last `/`)

Each run creates a new database named `"{title} — YYYY-MM-DD HH:MM"` under that page. If `NOTION_TOKEN` is missing, the pipeline continues and writes local files only.

Secrets go in `.env` — never committed.

---

## Project structure

```
product-agent/
├── orchestrator.py              # main entry point and pipeline logic
├── agent.py                     # skill runner, agentic loop, web search
├── observability.py             # cost, latency, and quality tracking
├── run_state.py                 # per-step saving and resume state
├── idea-template.md             # starter template for input documents
├── idea.md                      # your input document (gitignored)
├── config.yaml                  # pipeline configuration
├── .env.example                 # secrets template
├── connectors/
│   ├── discord.py               # stub (Discord integration not active)
│   └── notion.py                # Notion output connector
├── tests/                       # unit and integration tests
├── product-analysis/            # competitive research skill
├── product-user-feedback/       # user feedback synthesis skill
├── product-specification/       # spec drafting skill
├── product-user-story/          # user story generation skill
├── product-roadmap-fit/         # roadmap fit skill 
└── specs/                       # PRD, tech stack, implementation plan
```
