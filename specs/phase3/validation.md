# Phase 3 Validation Plan — Observability

## Principle

No Phase 3 code merges until all gates below pass in order. Each gate is independently runnable. Gates build on each other — a failure at Gate 1 blocks Gates 2–4.

---

## Gate 1 — Unit tests (zero cost, no real API)

```bash
python -m pytest tests/test_observability.py -v
```

### `StepMetrics` and `estimate_cost`
- [ ] `test_estimate_cost_haiku` — correct USD for known haiku input/output token counts
- [ ] `test_estimate_cost_sonnet` — correct USD for known sonnet token counts
- [ ] `test_estimate_cost_opus` — correct USD for known opus token counts
- [ ] `test_estimate_cost_unknown_model` — unknown model name raises `ValueError` with the model name in the message

### `heuristic_check`
- [ ] `test_heuristic_research_pass` — output with `##` headers and >200 chars passes
- [ ] `test_heuristic_research_fail_too_short` — output under 200 chars fails with reason
- [ ] `test_heuristic_research_fail_no_headers` — output with no `##` headers fails
- [ ] `test_heuristic_spec_fail_too_short` — output under 500 chars fails
- [ ] `test_heuristic_synthesis_fail_too_few_proposals` — output with 1 numbered item fails
- [ ] `test_heuristic_stories_fail_no_stories` — output with no `## Story` / `### Story` headers fails
- [ ] `test_heuristic_stories_pass` — output with a valid story header passes

### `RunTracker`
- [ ] `test_run_tracker_accumulates_steps` — adding 3 `StepMetrics` objects results in 3 entries
- [ ] `test_run_tracker_total_cost` — total cost equals sum of individual step costs
- [ ] `test_run_tracker_total_latency` — total latency equals sum of individual step latencies
- [ ] `test_run_tracker_writes_jsonl` — `tracker.write(folder)` produces `run-metrics.jsonl` with one line per step
- [ ] `test_run_tracker_writes_report_md` — `tracker.write(folder)` produces `run-report.md` containing a markdown table
- [ ] `test_run_tracker_report_contains_totals` — `run-report.md` contains a TOTAL row with summed tokens and cost
- [ ] `test_run_tracker_report_quality_warning` — a step with a quality warning shows `⚠` in the Quality column and appears in the warnings section

### `llm_quality_score` (mocked)
- [ ] `test_llm_quality_score_returns_score_and_reason` — mock Haiku call returns score 4, reason captured
- [ ] `test_llm_quality_score_low_triggers_warning` — score ≤ 2 sets `warning` field on quality result
- [ ] `test_llm_quality_score_not_called_on_profile_1` — `check_quality` with profile 1 never invokes the LLM

---

## Gate 2 — Profile 1 pipeline run (real API, ~$0.02)

Run the full test pipeline and verify both report files are produced.

```bash
python orchestrator.py idea.md   # select profile 1, scope 1
```

- [ ] `output/<run>/run-report.md` exists and contains a markdown table with 5 data rows
- [ ] `output/<run>/run-metrics.jsonl` exists and contains 5 lines of valid JSON
- [ ] Each JSONL line has keys: `step`, `model`, `input_tokens`, `output_tokens`, `latency_s`, `cost_usd`, `quality`
- [ ] Terminal prints the summary table before the final output paths message
- [ ] `llm_score` is `null` in all JSONL lines (profile 1 = heuristic only)
- [ ] All quality checks pass (no interactive prompt triggered)

---

## Gate 3 — Handoff failure simulation (zero cost)

Unit-level test that exercises the warn + ask interaction path without running the full pipeline.

```bash
python -m pytest tests/test_observability.py -v -k failure
```

- [ ] `test_warn_and_continue_yes` — mock `input()` returning `'y'`; pipeline continues; `user_continued=true` in metrics
- [ ] `test_warn_and_halt_no` — mock `input()` returning `'n'`; `SystemExit` raised with code 1
- [ ] `test_failure_reason_printed` — the step name and failure reason appear in captured stdout

---

## Gate 4 — LLM quality scoring on profile 3 (real API, ~$0.10 extra)

Run a full pipeline on profile 3 and confirm LLM scores appear in the report.

```bash
python orchestrator.py idea.md   # select profile 3, scope 1
```

- [ ] `run-metrics.jsonl` — `llm_score` is an integer (not null) for all 5 steps
- [ ] `run-report.md` — Quality column shows scores, not just `✓`
- [ ] Terminal summary shows LLM scores alongside heuristic results
- [ ] No quality failure triggered on a normal run (scores should be ≥ 3 for a reasonable idea document)

---

## Gate 5 — Pre-merge checklist

- [ ] `observability.py` has no dead code; all public functions have unit tests
- [ ] `agent.py` returns `(str, usage)` tuple; all call sites in `orchestrator.py` updated
- [ ] `save_outputs()` signature updated; no regressions in existing output files
- [ ] Rates in `observability.py` verified against current Anthropic pricing page; `RATES_UPDATED` date set
- [ ] All Gate 1 tests pass with `pytest`
- [ ] `run-report.md` and `run-metrics.jsonl` added to `.gitignore` alongside other output files (or confirmed already excluded by `output/` rule)

---

## Definition of Done

A single `python orchestrator.py idea.md` run (profile 3, balanced, full scope) results in:

1. All four existing markdown files written to `output/<run>/`
2. `run-report.md` written with a 5-row table showing model, tokens, cost, latency, quality per step
3. `run-metrics.jsonl` written with one JSON object per step, `llm_score` populated
4. Terminal prints the summary table before the final paths message
5. If any step output fails the heuristic or scores ≤ 2, the user is prompted before the pipeline continues
