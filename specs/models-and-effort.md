# Models and Effort

## In short

- The pipeline uses the **latest model of each family**: Claude Haiku 5.5, Claude Sonnet 5.5 and Claude Opus 5.5.
- Each step has an **`effort`** setting in `config.yaml`. Lower effort means less thinking, so a step costs less and finishes sooner.
- These models think by default. Thinking is billed as output and counts toward a step's `max_tokens`, so the token ceilings are set well above the size of the documents.
- Prices, rate limits and cache rules for these models are listed below, with what is measured and what is not.

## Models per profile

| Profile | Research and feedback | Synthesis | Spec and stories | Pre-step, summaries, quality score |
|---|---|---|---|---|
| 1 Test | Haiku 5.5 | Haiku 5.5 | Haiku 5.5 | Haiku 5.5 |
| 2 Budget | Haiku 5.5 | Haiku 5.5 | Haiku 5.5 | Haiku 5.5 |
| 3 Balanced | Sonnet 5.5 | Haiku 5.5 | Sonnet 5.5 | Haiku 5.5 |
| 4 Optimal | Opus 5.5 | Sonnet 5.5 | Sonnet 5.5 | Haiku 5.5 |

A step that names no model, and the quality score, use Haiku 5.5. The model IDs have no date suffix: `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`.

## Prices

Per million tokens, from the published pricing page (checked on the date in `RATES_UPDATED`):

| Model | Input | Output | Cache write (5 min) | Cache read |
|---|---:|---:|---:|---:|
| Claude Haiku 5.5 | $0.10 | $0.50 | $0.125 | $0.01 |
| Claude Sonnet 5.5 | $2.00 | $10.00 | $2.50 | $0.10 |
| Claude Opus 5.5 | $4.00 | $20.00 | $5.00 | $0.20 |
| Claude Haiku 4.5 | $1.00 | $5.00 | $1.25 | $0.10 |
| Claude Sonnet 4.6 | $3.00 | $15.00 | $3.75 | $0.30 |
| Claude Opus 4.7 | $5.00 | $25.00 | $6.25 | $0.50 |

- **Cache reads** cost 0.1 times the input price, except on Sonnet 5.5 and Opus 5.5, where they cost 0.05 times.
- **Web search** costs $10 per 1,000 searches on every model.
- **Older models** stay in the table so edited configs and old runs still price correctly. `config.yaml` names only the 5.5 models.

## Effort

Effort goes to the API as `output_config.effort` and takes `low`, `medium`, `high`, `xhigh` or `max`. Left out, the model's own default applies: `medium` on Haiku 5.5 and Opus 5.5, `high` on Sonnet 5.5.

| Step | Profile 1 | Profile 2 | Profile 3 | Profile 4 |
|---|---|---|---|---|
| Pre-step, summaries | low | low | low | low |
| Research, feedback | low | **high** | medium | **high** |
| Synthesis | low | medium | medium | medium |
| Spec, stories | low | medium | medium | medium |
| Quality score | low | low | low | low |

- **Small steps at `low`:** extracting two names, summarising a report and scoring an output need no reasoning.
- **Main steps at `medium`:** that is one level below Sonnet 5.5's default. The documentation names `medium` as the starting point for well-specified multi-step work, and it keeps cost and time near what the earlier models took. Research and feedback also run searches, and Haiku 5.5 is more likely to skip a search at `low`.
- **Profiles 2 and 4 research at `high`:** profile 4 exists for the deepest research, so its Opus steps think more. In profile 2 the model is Haiku 5.5, for which the documentation recommends `high` for knowledge work, longer agent tasks and strict instruction following. It is cheap on Haiku, so the extra thinking costs little.
- **Profile 1 at `low`:** it only checks the wiring.

The values are starting points. The run report shows output tokens per step, and thinking tokens are part of that figure, so a step that costs more than expected points at its effort.

## Output ceilings

Thinking counts toward `max_tokens`, and the newer tokenizer produces about 30% more tokens for the same text, so the ceilings sit well above the documents:

| Step | Profiles 2 to 4 | Profile 1 |
|---|---|---|
| Research, feedback, spec | 32,000 | 2,000 |
| Stories | 64,000 | 2,000 |
| Synthesis | 8,000 | 2,000 |
| Pre-step | 2,000 | 2,000 |
| Summaries (`summary` context mode) | 1,500 | 2,000 |

A ceiling is billed only for tokens produced and does not count toward the output-tokens-per-minute limit. The summary ceiling is a size limit (see [context-handling.md](context-handling.md)), so thinking leaves a summary shorter.

## Rate limits and caching

- **Rate limits:** each 5.5 model has its own limit, separate from the other models. At the Scale tier each has 10,000,000 input and 2,000,000 output tokens a minute, which matches the limits the API reported for this account on Sonnet 4.6. Cache reads do not count toward the input limit, and `max_tokens` does not count toward the output limit.
- **Caching:** the minimum cacheable prefix is 512 tokens on all three models (4,096 on Haiku 4.5), so the search steps of profile 2 can cache.

## How thinking shows up

A response can carry `thinking` blocks. They arrive with empty text, because the API omits the thinking text by default. The pipeline ignores them when it assembles a document and when it reads the quality score, sends them back unchanged when it resumes a paused search turn, and counts them in the output tokens.

## Changing a model or an effort

Edit `model` or `effort` for a step in `config.yaml`. A model that is not in `_RATES` in `observability.py` needs a rate first. Before its first request, a run checks every model of the chosen profile, plus Haiku 5.5 (the default of a step that names no model, and the model of the quality score). If any has no rate, the run stops with the unrated models listed and the command to resume with, whether it is new or resumed. A test also fails when `config.yaml` names an unrated model.

## Constraints and limitations

What this design does not guarantee, and what to do about it. Items marked "not measured" are not established facts.

1. **The effort values are not measured.** They follow the documentation's starting points. *What to do:* read the output tokens per step in `run-report.md` after a run, and lower the effort of a step that costs more than expected.
2. **Thinking tokens are not reported separately.** They are inside the output-token figure, so the report cannot say how much of a step was thinking.
3. **Token counts from runs on the older models are not comparable.** The pricing page says the newer tokenizer produces about 30% more tokens for the same text. Compare documents by characters. Whether the figure holds for this pipeline's text is not measured.
4. **Haiku 5.5 costs more beyond 100,000 tokens of prompt** ($0.50 input, $2.50 output). The cost estimate applies the lower rates. No step sends that much.
5. **The newer models can decline a request.** Opus 5.5 and Sonnet 5.5 run safety classifiers, and a declined request ends with the stop reason `refusal`. The run stops with the reason shown, as for any refusal. Server-side fallbacks, which the API offers for these models, are not enabled: they need the beta endpoint and change billing. *What to do:* if refusals appear, change the idea document and resume, or say so and the fallbacks can be added.
6. **A continuation after `max_tokens` edits the model's earlier turn.** It sends back only the text blocks, without the thinking and search blocks. An account that enforces the check on edited history may reject that with a 400. With the larger ceilings a continuation should be rare. Whether this account enforces the check is not verified.
7. **The basic search tool is used.** Dynamic filtering (`web_search_20260209` and later), which filters results before they enter the context, is not used. It changes how `max_uses` counts, the shape of the response, and zero-data-retention eligibility.
8. **The announcement before a search may change.** For Opus 5.5 and Sonnet 5.5 the API reference says text between tool calls comes back as progress-update thinking blocks, empty by default. Whether the reports still open with a line such as "I'll run all the research searches…" is not verified.
9. **Rates are fixed constants** dated by `RATES_UPDATED`. A price change needs an edit, and the tests pin each model's published rates.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Models | The latest of each family | Better and cheaper per token than the models they replace |
| Effort for main steps | `medium` | One step below Sonnet 5.5's default; the documented starting point for multi-step work |
| Effort for research and feedback on Haiku 5.5 | `high` | The documented level for knowledge work and longer agent tasks, at a small cost on a cheap model |
| Effort for small steps and the score | `low` | No reasoning needed |
| Effort in profile 4 research | `high` | The profile exists for depth |
| Ceilings | 32,000, 64,000 and the smaller ones above | Thinking and the newer tokenizer take room that the documents alone do not |
| Search tool | Basic version | Dynamic filtering changes several behaviours and needs its own measurement |
| Refusal fallbacks | Not enabled | A refusal already stops the run with its reason |

## Test plan

| File | Covers |
|---|---|
| `tests/test_observability.py` | The published rates of all six models, the cache-read multipliers, that `config.yaml` names only the latest models and every model has a rate, and the scorer's model and settings |
| `tests/test_effort.py` | Effort reaches the request on every round, for skill steps and direct calls, is left out when unset, and every value in `config.yaml` is a valid level |
| `tests/test_request_load.py` | The ceilings in `config.yaml` |
