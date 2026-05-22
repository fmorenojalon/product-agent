# Phase 3 Requirements — Observability

## Scope

Phase 3 makes every pipeline run's cost, latency, and output quality visible and attributable per step. It produces two persistent artefacts alongside the existing markdown outputs, and prints a summary table to the terminal at the end of every run.

### In scope

- **Latency tracking**: wall-clock time recorded around every instrumented step call
- **Cost attribution**: input/output token counts extracted from each Claude API response; estimated USD computed using hardcoded per-model rates
- **Handoff quality checks**: each step's output is validated before passing downstream; failures trigger an interactive warn + ask prompt
- **Terminal summary**: per-step table printed at pipeline end (model, tokens in/out, cost, latency)
- **`run-report.md`**: human-readable markdown table written to `output/<run>/` alongside the existing files
- **`run-metrics.jsonl`**: machine-readable log written to `output/<run>/`; one JSON object per step

### Out of scope

- Real-time streaming metrics or a live dashboard
- Storing metrics outside the local output folder (no Notion, no external service)
- Modifying the quality check thresholds at runtime via CLI flags
- Retroactive metrics for previous runs

---

## Instrumented Steps

Only the five main pipeline steps are tracked. Pre-step extraction and compression calls are excluded — they are auxiliary and low-cost.

| Step key   | Skill / call         | Tracked |
|------------|----------------------|---------|
| `research` | UC-1 product-analysis | ✓ |
| `feedback` | UC-2 product-user-feedback | ✓ |
| `synthesis`| Direct LLM call      | ✓ |
| `spec`     | UC-3 product-specification | ✓ |
| `stories`  | UC-4 product-user-story | ✓ |
| `pre_step` | Competitor / persona extraction | — |
| `compress` | Summary compression  | — |

---

## Handoff Quality Checks

### Heuristic checks (all profiles)

Applied immediately after each step completes, before passing output downstream.

| Step       | Failure condition |
|------------|-------------------|
| `research` | Output < 200 chars, or no `##` section header found |
| `feedback` | Output < 200 chars, or no `##` section header found |
| `synthesis`| Fewer than 2 numbered proposals in output |
| `spec`     | Output < 500 chars, or no `##` section header found |
| `stories`  | `parse_stories()` returns 0 stories |

### LLM quality score (profiles 3 and 4 only)

Applied after the heuristic passes. A single Haiku call rates the output 1–5 and returns a one-sentence reason if the score is ≤ 2.

- Score 1–2: treated as a quality failure (warn + ask)
- Score 3–5: passes; score recorded in metrics
- Cost: ~$0.001 per step

### Failure behaviour

When any check fails (heuristic or LLM score):

1. A warning is printed to the terminal with the step name, the failure reason, and the first 300 chars of the output for context
2. The user is asked interactively: `Continue anyway? (y/n)`
3. If `n`: pipeline exits with code 1; all outputs written so far are preserved
4. If `y`: pipeline continues with the flagged output; the warning is recorded in metrics

---

## Output Files

### `run-report.md`

Human-readable markdown table. Written to `output/<run>/run-report.md` at pipeline end.

```
## Run Report — {title} — {timestamp}

| Step      | Model   | Input tok | Output tok | Est. cost | Latency | Quality |
|-----------|---------|-----------|------------|-----------|---------|---------|
| research  | sonnet  | 4,821     | 3,102      | $0.042    | 18.3s   | ✓       |
| feedback  | sonnet  | 3,944     | 2,871      | $0.035    | 15.1s   | ✓       |
| synthesis | haiku   | 1,203     | 412        | $0.003    | 3.1s    | ✓       |
| spec      | sonnet  | 6,203     | 5,441      | $0.063    | 22.7s   | ✓       |
| stories   | sonnet  | 7,102     | 4,983      | $0.066    | 26.2s   | ✓       |
| **TOTAL** |         | 23,273    | 16,809     | **$0.209**| 85.4s   |         |

### Quality warnings
None.
```

If a step was warned and continued, Quality shows `⚠` and the reason appears in the Quality warnings section.

### `run-metrics.jsonl`

One JSON object per line. Each object:

```json
{
  "step": "research",
  "model": "claude-sonnet-4-6",
  "input_tokens": 4821,
  "output_tokens": 3102,
  "latency_s": 18.3,
  "cost_usd": 0.042,
  "quality": {
    "heuristic_ok": true,
    "llm_score": 4,
    "warning": null,
    "user_continued": null
  }
}
```

`llm_score` is `null` for profiles 1 and 2. `user_continued` is `null` if no failure occurred, `true` if the user chose to continue past a failure, `false` if the pipeline halted.

---

## Cost Model

Rates are hardcoded in `observability.py` with a `RATES_UPDATED` date constant. Cost = `(input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate`.

| Model | Input $/M | Output $/M |
|-------|-----------|------------|
| claude-haiku-4-5-20251001 | $0.80 | $4.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 |
| claude-opus-4-7 | $15.00 | $75.00 |

**Note**: rates must be verified at implementation time against the current Anthropic pricing page. Update `RATES_UPDATED` whenever rates are refreshed.

---

## Implementation Plan

### New file: `observability.py`

| Function / class | Responsibility |
|------------------|----------------|
| `StepMetrics` (dataclass) | Holds step name, model, tokens, latency, cost, quality result |
| `RunTracker` | Accumulates `StepMetrics` across a run; writes `run-report.md` and `run-metrics.jsonl` at the end |
| `estimate_cost(model, input_tokens, output_tokens) -> float` | Looks up hardcoded rates and returns USD |
| `heuristic_check(step, output) -> tuple[bool, str]` | Returns `(passed, reason)` |
| `llm_quality_score(step, output, profile) -> tuple[int, str]` | Haiku call; returns `(score, reason)`; only called on profiles 3 and 4 |
| `check_quality(step, output, profile) -> QualityResult` | Orchestrates heuristic + optional LLM check |

### Modified: `orchestrator.py`

- Instantiate `RunTracker` at the start of `main()`
- Wrap each instrumented step: record start time, call the step, record end time + token counts, call `check_quality`, handle failure interaction
- Pass `RunTracker` to `save_outputs()` to write the report files
- Print the summary table before the final output paths message

### Modified: `agent.py`

- `run_skill` currently returns a `str`. Return a `(str, usage)` tuple where `usage` is `{"input_tokens": int, "output_tokens": int}` — summed across all continuation rounds.
- Update all call sites in `orchestrator.py` accordingly.

### Modified: `save_outputs()`

- Accept `tracker: RunTracker` and call `tracker.write(folder)` to produce both report files.

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Failure behaviour | Warn + ask interactively | Gives the user control without forcing a re-run on every minor quality issue |
| Quality check method | Heuristic (profiles 1–2), heuristic + Haiku score (profiles 3–4) | Test runs don't need scoring overhead; production runs benefit from the extra signal |
| Metrics persistence | JSONL + markdown report in output folder | JSONL for future tooling; markdown for immediate human readability; no new external dependency |
| Cost model | Hardcoded rates with `RATES_UPDATED` constant | Transparent, zero-dependency, trivially updatable |
| Steps tracked | 6 main steps (research, feedback, synthesis, spec, stories) | Pre-step and compress are auxiliary; tracking them adds noise without actionable insight |
| Token accumulation | Sum across continuation rounds | A step that required 3 continuation rounds should report total tokens, not just the last round |
