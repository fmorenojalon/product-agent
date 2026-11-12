# Rate Management and Run Resilience — Requirements and Design

## Scope

How the pipeline survives API throttling and faults: what it saves, when it retries, when it stops, and what it tells the user while it waits. No API fault loses finished work, and no wait is silent or unbounded.

What the later steps read of the reports (full or summarised) is described in [context-handling.md](context-handling.md), the models, prices and effort in [models-and-effort.md](models-and-effort.md), and the length of the stories in [stories-format.md](stories-format.md).

Out of scope: a limiter shared across machines or runs, Priority Tier, the Batch API for the whole pipeline (the human gate needs an answer in the same session), predictive or learned scheduling.

## API facts this design relies on

| Fact | Consequence |
|---|---|
| Rate limits use a token bucket, replenished continuously — not a fixed 60-second window | A fixed wait is a guess; `retry-after` is the only authoritative wait |
| `retry-after` is the number of seconds to wait; earlier retries fail. Not every 429 carries it | Obey it when present; back off exponentially when absent |
| A tier spend-cap 429 has `error.details.error_code = enforced_spend_limit_reached` and no `retry-after`; retrying fails until the next month | Fail fast |
| A spend limit set by the user returns HTTP 400, not 429. Billing problems return 402 | Fail fast |
| `max_tokens` does not count toward the output-tokens-per-minute limit | A low `max_tokens` buys no rate headroom and forces continuations that re-send the input |
| Cache reads do not count toward the input-tokens-per-minute limit; cache writes do | Caching is a rate lever |
| SDK retry behaviour differs by version: 0.103.1 honours `retry-after` only up to 60s; 2.6.0 honours any value, silently | The SDK's own retries are off and its version is pinned |
| 5xx and 529 (overloaded) are transient | Retry with backoff |
| A paused search turn, sent back as the SDK serialises it (an assistant message ending at the search result, same tools), is accepted and the model finishes the answer. Checked once on Haiku 4.5, with the pause simulated by cutting a finished turn | Resume as designed. Sonnet and Opus are not checked |
| `max_uses` caps the searches in one turn, including across a `pause_turn` resume. A search that fails still counts against it but is not billed | The cap is sent to the API and relied on. Searches are counted from `usage`, not from search blocks |
| Search results are counted as input tokens. A request with one search used about 12,000 input tokens and a request with two used about 18,000 (Haiku 4.5, pricing queries: two measurements) | Each search adds a large block of input, so the search cap is also an input-rate lever |
| With caching on, the API also writes a 5-minute cache entry after each web search result (per the API reference) | Later rounds of the same turn can read them at the cache-read price. The saving is not measured |
| Cache writes cost 1.25 times the input price and count toward the input-tokens-per-minute limit; cache reads do not count toward it and cost a tenth (a twentieth on Claude Sonnet 5.5 and Claude Opus 5.5). A prefix below the model's minimum (512 tokens on Claude Haiku 5.5, Sonnet 5.5 and Opus 5.5; 4,096 on Haiku 4.5) is silently not cached | Caching pays only where a prefix is read again; below the minimum it does nothing |
| An error event inside a stream reaches the SDK as a plain `APIStatusError` whose status is 200 | Such errors can only be classified by error type, never by status |

## Requirements

| Requirement | How it is checked |
|---|---|
| Each finished step is written to disk at once, and a stopped run resumes without repeating finished steps | Kill the run at any step; resuming makes no repeat calls for finished steps |
| One retry layer: the SDK's own retries are off, `retry-after` is obeyed, backoff applies when it is absent, and total waiting is limited (15 minutes by default) | Fake-API tests for each error type |
| Errors a retry cannot fix fail fast: spend cap, 400, 401, 402, 403, 404, 413, 422 | Exactly one request; finished steps stay on disk |
| Every wait over 5 seconds is printed with its reason | Fake-API tests |
| Waiting is separated from working: each step records its active time, wait time, retries by kind and the least allowance left, read from the API's rate-limit headers | Tests with fake waits and headers; changing the headers changes what is recorded, with no configuration change |
| Every stop reason is handled, and no partial output is accepted silently | One test per stop reason |
| Load per request is cut at the source: the search cap is sent to the API, search steps use caching, requests are streamed, and output ceilings sit above the expected output | Request-shape tests offline; a real run for the search count and for single-request completion (see limitation 17) |
| The SDK version is pinned | `requirements.txt` |

## Design: persistence and resume

### What is saved, and when

The output folder is created when the run starts. Each step writes its output the moment it finishes, then records itself as done:

| Step | Saved to | Notes |
|---|---|---|
| `pre_step` | `run-state.json` (`competitors`, `persona`) | |
| `research` | `research-brief.md` | |
| `feedback` | `feedback-synthesis.md` | |
| `compress` | `research-summary.md`, `feedback-summary.md` | `summary` context mode only; in the default `full` mode there is no such step |
| `synthesis` | `proposals.md` | |
| human gate | `run-state.json` (`chosen`) | The user's answer is never asked twice |
| `interview` | `run-state.json` (`interview_context`) | Interactive mode only |
| `spec` | `product-spec.md` | |
| `stories` | `user-stories.md` | |
| Notion push | `run-state.json` (`notion` marked done) | Skipped on resume once done, so a resume does not create a duplicate database |

After every tracked step, `run-metrics.jsonl` and `run-report.md` are rewritten, so the cost and latency of finished steps survive a crash.

A step that fails after some of its requests came back was paid for. `complete()` attaches the usage of those requests to the error it raises (`paid_usage`, in the form of a normal return), whatever the error is: a refusal, an API error after the retries, or Ctrl-C. The tracker then records a row for the step, marked failed, with the cost of those requests and the time until the failure, and rewrites the metrics before the error goes on. The row shows `✗ failed` in the Quality column, its reason is in the `failed` field of `run-metrics.jsonl`, and `run-report.md` lists it under Failed steps. A failure before any request came back has no row, because nothing was spent. When a failed step runs again on resume, it has a second row, and both rows count in the totals.

Files are written atomically (temp file, then rename), so a kill mid-write never leaves a half-written output that looks finished. A step is marked done only after its file exists.

### `run-state.json`

```json
{
  "version": 1,
  "values": {
    "input_path": "idea.md", "input_sha256": "…", "title": "idea",
    "timestamp": "2026-11-06 14:03", "profile_key": "3",
    "interactive": false, "full_scope": true,
    "competitors": ["…"], "persona": "…",
    "chosen": "2", "interview_context": ""
  },
  "done": ["pre_step", "research", "feedback", "synthesis", "gate"]
}
```

### Resume

```
python orchestrator.py --resume output/2026-11-06_14-03_idea
```

- Profile, mode, story scope and the idea document path come from the saved state; nothing is asked again. If the idea document changed since the run began, the user is warned and asked whether to continue.
- A step marked done is loaded from its file and not called. The first step not marked done runs again, in full: a half-finished step is never partially reused.
- Metrics of finished steps are loaded from `run-metrics.jsonl`, so totals include everything already paid.
- Resuming a completed run is a no-op that prints the summary again.
- `--resume <run folder> --redo <step>` runs a step and every step after it again (`research`, `feedback`, `synthesis`, `spec` or `stories`), keeping each earlier output as `<name>.previous.md`. Redoing `synthesis` or an earlier step asks for the direction again. Both attempts stay in the metrics, and redoing `stories` pushes a new Notion database. See [stories-format.md](stories-format.md).

### When the run stops

| Event | Saved | What the user sees |
|---|---|---|
| Uncaught API error after retries (or a fail-fast error) | Every finished step, metrics (including a row for a failed step that had paid requests), state | The error, then the exact `--resume` command |
| User answers `n` at a quality prompt | Finished steps, plus the rejected output as `<step>.rejected.md`, plus the step's metrics with `user_continued=false` | The resume command. Resuming re-runs that step |
| Ctrl-C | Finished steps, metrics (including a row for the interrupted step if some of its requests came back), state | The resume command |

All outputs written before the stop are preserved.

## Design: retry policy

One function, `api_call_with_retry` in `agent.py`, owns all retrying. Every Anthropic client in the pipeline is built with `max_retries=0`, so the SDK never retries underneath it.

### Classification

| Error | Action |
|---|---|
| HTTP 400, 401, 402, 403, 404, 413, 422 | Raise at once. One request |
| HTTP 429 with `error_code = enforced_spend_limit_reached` | Raise at once. One request |
| HTTP 429 (any other) | Retry |
| HTTP 408, 409, 5xx including 529 | Retry |
| Connection errors and timeouts | Retry |
| An error event inside a stream, of type `overloaded_error`, `api_error` or `rate_limit_error` (the HTTP status is already 200) | Retry. The whole request restarts and the partial output is discarded |
| An error event inside a stream, of any other type | Raise at once |
| Anything else | Raise at once |

### Waiting

- With a `retry-after` header: wait that long, plus up to 1s of jitter.
- Without one: exponential backoff, 2s doubling to a 60s ceiling, with jitter.
- Total waiting per call is limited to 15 minutes, and retries to 8. If the next wait would exceed what is left of the budget, the error is raised immediately rather than sleeping. A call never freezes silently for longer than the budget.
- Every wait over 5s is printed with its reason, the retry number and how much of the budget is used.

### Why the limits exist

The bucket refills continuously, so a short wait often works, and a fixed 65–85s wait is usually too long. But a single request larger than the bucket can never pass, so both a retry count and a total budget are needed to stop a call that cannot succeed.

## Design: stop reasons

One function, `complete` in `agent.py`, runs every model call: skills (`run_skill`) and direct calls (`_llm`). It returns an answer only when the model finished it:

| stop_reason | Action |
|---|---|
| `end_turn` | Done. A blank answer raises |
| `max_tokens` | Continue from where the model stopped. Search results are not sent back (they would re-send tens of thousands of tokens), and no tools are offered on continuation rounds |
| `pause_turn` | The API paused a long search turn. Send the paused message back unchanged, with the same tools, to resume it |
| `refusal` | Raise `StopReasonError` with the refusal category and explanation |
| `tool_use`, `stop_sequence`, `model_context_window_exceeded`, anything else | Raise `StopReasonError`: the pipeline offers no client tools or stop sequences, so these mean something is wrong |
| 50 rounds without a final answer | Raise |

A raise stops the run like any other error: finished steps stay saved and `--resume` re-runs only the interrupted step. After a refusal, change the idea document before resuming, or the step will be refused again.

Direct calls (pre-step, proposals, interview questions) use the same loop, so an answer that reaches its `max_tokens` is completed instead of silently cut off. The one exception is a summary (`summary` context mode): its `max_tokens` is a size limit, so it ends there and is not continued.

A resumed search turn is sent with the same tools, because a paused turn cannot continue without them.

### Text of a response

A response is a list of blocks, and the text is assembled in order. Text blocks that follow one another are joined as they are, because web-search citations split a sentence across blocks. Text separated by a search or any other non-text block is separated by one blank line, so what the model says before it searches does not run into what it writes after. The text of successive rounds is joined with nothing after a `max_tokens` cut, because the cut can fall inside a word or a table row, and with a newline after a resumed pause.

## Design: request load

Four settings reduce what each request asks of the API. They are applied in `agent.py` and `config.yaml`.

| Setting | What is sent | Where it is set |
|---|---|---|
| Search cap | `max_uses` on the search tool, from the step's `max_searches` (0 means no search tool at all). The API enforces it across all requests of one turn | `config.yaml`, per step |
| Prompt caching | Top-level `cache_control` (automatic caching) on every round that offers the search tool, for steps that search | `run_skill` |
| Streaming | Every request is streamed and returned as one complete message | `_request` in `agent.py` |
| Output ceiling | `max_tokens` set above the expected output | `config.yaml`, per step |

### Output ceilings

| Step | Profiles 2–4 | Profile 1 (test) |
|---|---|---|
| `research`, `feedback`, `spec` | 32,000 | 2,000 |
| `stories` | 64,000 | 2,000 |
| `compress` (`summary` mode only) | 1,500 | 2,000 |
| `synthesis` | 8,000 | 2,000 |
| `pre_step` | 2,000 | 2,000 |

A ceiling is not a budget. It is billed only for tokens produced and does not count toward the output-tokens-per-minute limit. The values are set above the expected output plus thinking, which counts toward the ceiling, and above the allowance for the newer tokenizer (about 30% more tokens for the same text), so a normal document is finished in one request. A step that still exceeds its ceiling is completed by continuation. Profile 1 keeps small ceilings on purpose, so test runs stay cheap; they are 2,000 and not smaller because thinking counts toward them.

### Caching scope

Caching is on only for steps that search (`research`, `feedback`), and only while the search tool is offered. Direct calls, the spec and the stories are single-round, so caching them would only add the cache-write premium. A continuation after `max_tokens` drops the tools, which changes the cached prefix, so it is not cached either.

### Other design points

- The search count in the metrics comes from the usage the API reports. Counting search blocks is only a fallback, because it also counts searches that failed and were not billed.
- Research and feedback run one after the other. There is no fixed pause between steps: waiting is left to the retry policy, which waits only when the API says so.
- The search tool is `web_search_20250305`, the basic version.
- A continuation after `max_tokens` drops the search results from what it sends back, and keeps the model's text blocks.

## Design: wait and limit telemetry

Each tracked step records how long it waited, what it retried, and how much allowance the API said was left. The figures are collected by `CallStats` in `agent.py` and returned in the usage of `complete`.

| Field | Meaning |
|---|---|
| `wait_s` | Total time the step slept between retries |
| `active_s` | `latency_s` minus `wait_s`: the time the step spent working |
| `rate_limited` | Retries after a 429, or after a rate-limit error inside a stream |
| `server_errors` | Retries after a 5xx or 529, or after an overloaded or API error inside a stream |
| `other_retries` | Retries after a connection error, a timeout, a 408 or a 409 |
| `min_input_tokens_remaining`, `min_output_tokens_remaining` | The least input and output allowance left, in any response header of the step |
| `input_tokens_limit`, `output_tokens_limit` | The limits those headers reported |

The remaining allowance is read from the `anthropic-ratelimit-input-tokens-*` and `anthropic-ratelimit-output-tokens-*` headers of every response, including the headers of an attempt that failed. The pipeline holds no limits of its own: a different account tier shows up in the figures with no configuration change. A field is empty when the API sent no such header.

The fields appear in `run-metrics.jsonl`; as Active, Wait and Retries columns, plus a rate-limit headroom table, in `run-report.md`; and as a Wait column and two footnotes (retries, lowest allowance left) in the terminal summary. A metrics file without these fields still loads.

## Constraints and limitations

What this design does not guarantee, and what to do about it. Items marked "measured once" or "estimate" are not established facts.

1. **A search cap narrows the research.** The feedback skill's own query plan asks for more searches than the configured cap (5 in profiles 2 and 3, 8 in profile 4), so a step ends with fewer sources than it would uncapped. In a check with a cap of 2 and four topics requested, the model searched two, said it had reached its search limit, and answered for those two only (measured once). The effect on quality is not measured. *What to do:* compare a run with an uncapped one; raise `max_searches` per profile in `config.yaml`, or shorten the skill's query plan.
2. **Each search is large.** A request with one search used about 12,000 input tokens and a request with two used about 18,000 (measured twice: Haiku 4.5, pricing queries), so roughly 9,000 to 12,000 per search (tokens per search on the 5.5 models are not measured). Five searches is therefore roughly 45,000 to 60,000 input tokens or more in one step, and eight roughly 72,000 to 96,000 or more. A request larger than the whole input allowance of the account's tier can never pass; a limit of 30,000 input tokens per minute, for example, is below this. *What to do:* check the tier on the console's rate-limits page, and lower `max_searches` if it is low.
3. **The pipeline records the account's limits but does not act on them.** Its waits follow `retry-after` only, and it does not know the account's tier in advance. Whether exceeding a limit also adds a debt that lengthens the wait is not documented. *What to do:* check the tier on the console's rate-limits page.
4. **Remaining allowance is an indication, not a guarantee.** The API sends the allowance when a response starts and rounds it to the nearest thousand. A long search turn can use much more afterwards, so the lowest figure recorded for a step shows the headroom at the start of its responses, not at the end.
5. **The header figures are only partly confirmed against the real API.** They were checked against a local server that imitates it, and in real runs on Haiku 4.5 and Sonnet 4.6, in which all four headers arrived with sensible values. The 5.5 models and Opus are not checked. An account may not receive every header, and the fields are then empty. *What to do:* compare a real run's headroom table with the console's rate-limit charts.
6. **Waits in calls that are not tracked steps are not recorded.** The pre-step, compress (`summary` mode), interview-question and quality-score calls retry and print their waits like any other call, but their waits and retries belong to no step and are not in the metrics. Neither is what they cost, whether they succeed or fail.
7. **Caching covers search steps only.** Direct calls, the spec and the stories are not cached (single round), and neither is a continuation after `max_tokens`. *What to do:* nothing, unless the spec or stories start needing several rounds.
8. **The caching saving is not measured.** The API reference says searches write cache entries after each result when caching is on, so later rounds of a turn can read them at a tenth of the input price. On Sonnet 4.6, caching engaged on both search steps of a profile 3 run (cache writes of about 34,000 to 36,000 tokens and reads of about 4,600 to 56,000 per step across three runs, one idea) and saved about 9% of the first run's cost, worked out from its tokens and the rates. On Haiku 4.5, in one real request with two searches, no cache tokens were written or read, probably because the prefix was below that model's 4,096-token minimum. Whether caching engages on the 5.5 models is not measured. A cache write costs 25% more than plain input and counts toward the input-per-minute limit, so with nothing re-read, caching adds cost and rate use. *What to do:* watch the cache columns and cost in `run-report.md` over a few runs.
9. **A short prefix is not cached.** Below the model's minimum (512 tokens on Claude Haiku 5.5, Sonnet 5.5 and Opus 5.5; 4,096 on Haiku 4.5) caching silently does nothing: no error and no write. *What to do:* nothing; the cache columns show whether it happened.
10. **Rates are hardcoded.** `_RATES` in `observability.py` holds the per-model prices (input, output, 5-minute cache write at 1.25 times the input price, cache read at 0.1 times) and web search at $10 per 1,000, dated by `RATES_UPDATED`. A price change needs an edit. A run checks every model of its profile, and the quality-score model, against the table before its first request. A model missing from it stops the run there, on a new run and on a resume, with the unrated models listed. A step that is paid for with an unrated model anyway keeps its output, and its cost is recorded as unknown: `null` in `run-metrics.jsonl`, "unknown" in the summary and the report, and left out of the total. A test fails when a model named in `config.yaml` has no rate. *What to do:* re-check the rates against the pricing page when prices change, and add a rate whenever a model is added to `config.yaml`.
11. **Streamed usage is not confirmed against the real API.** Token counts and the search count come from the SDK's accumulation of stream events. They were checked only against a local server that imitates the stream. *What to do:* compare a real run's usage columns with the console's usage page.
12. **A failed stream restarts from the beginning.** The partial output is discarded. Error types other than overloaded, API and rate-limit errors are raised, not retried. The API reports a request's usage when its stream finishes, so a request cut off by Ctrl-C or by an error inside the stream has no usage to record: the metrics count the requests that came back, and whether the API bills the output generated before the cut is not verified. *What to do:* if a failure or an interruption matters, compare the run's total with the console's usage page.
13. **The output ceilings are set from measurements on other models.** On Sonnet 4.6, without thinking, the outputs were about 6,700 to 7,500 tokens for research, 5,000 to 6,000 for feedback, 7,200 to 8,200 for the spec and 11,000 to 25,900 for the stories in the long format. The ceilings add room for thinking and the newer tokenizer, and are not measured on the 5.5 models. A step that exceeds its ceiling is completed by continuation, at the price of re-sending its input, and the metrics do not record how many rounds a step took. *What to do:* if a real run shows continued steps, raise that ceiling.
14. **Cost estimates are rough.** `estimated_cost` in `config.yaml` and the profile table in the README are worked out from the published prices and earlier token counts. They do not account for thinking and have not been measured on the 5.5 models. Two profile 3 runs on Sonnet 4.6 cost $0.99 and $1.17 as reported.
15. **The search tool is the basic version.** Dynamic filtering (`web_search_20260209` and later) needs Claude 4.6 or later and is not eligible for zero data retention. `web_search_20260318` only adds control over what appears in the response and does not reduce token use. *What to do:* judge on a real run whether filtering is worth it.
16. **Dropping search results from a continuation is unverified.** The continuation keeps the model's text blocks, including their citations, without the search results they point to. The thinking blocks are dropped as well (see [models-and-effort.md](models-and-effort.md)). Whether the API accepts that is not verified. With the larger ceilings continuations should be rare.
17. **The search cap and single-request completion are checked offline only.** "Search count never exceeds the cap" and "normal documents need no continuation" can only be established by a real run. The offline tests check the shape of each request, not the API's behaviour.
18. **No fixed pause between steps.** At a low tier a rate-limit response appears as a visible wait from the retry policy, not as a pause before the call. If one step needs more input than the tier allows in a minute, it fails (see 2).
19. **Research and feedback never run in parallel**, whatever the account's limits would allow. This costs wall-clock time.
20. **A failed Notion push is not retried on resume.** The push reports its own failures and does not raise, so the run records it as done. The stories are in `user-stories.md`.
21. **Only the SDK is pinned.** The other dependencies are not pinned and there is no lockfile.
22. **A report can open with a line that is not part of it.** Before searching, the model often announces the searches ("I'll run all the research searches…") or writes a preface ("Here is the full report…"), and the pipeline keeps that text. Removing everything before the first heading would also remove real content, such as a note on missing data. *What to do:* delete the line by hand if it matters.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Who retries | The wrapper only; SDK `max_retries=0` | The SDK's waits are silent and version-dependent; one owner makes every wait visible and bounded |
| Wait source | `retry-after`, else backoff | The API reports the real wait; there is no fixed 60s window |
| Wait limit | 15 minutes total, 8 retries | Longer than any normal refill, short enough to surface a real outage |
| Spend limits | Fail fast | Retrying cannot fix them |
| Persistence | One file per step plus `run-state.json` | Reuses the output files; resume needs only a small JSON for what the files do not hold |
| Rejected output | Saved as `<step>.rejected.md` | It was paid for; the user may want to read it |
| SDK version | Pinned (`anthropic==2.6.0`) | An unpinned range lets an SDK update change retry behaviour without any code change |
| Incomplete answers | Continue or raise, never return; a summary is cut by design | A partial brief or spec passes the quality heuristics unnoticed and feeds every later step |
| One loop for skills and direct calls | `complete` in `agent.py` | Two copies of a continuation loop drift apart; one loop keeps every call path identical |
| Search cap | `max_uses` from `max_searches` (5, 5, 8) | The API enforces it; a client-side count cannot |
| Caching scope | Steps that search, while the tools are offered | The other steps are single-round: caching would only add the write premium |
| Streaming | Every request | Needed once `max_tokens` can exceed the SDK's non-streaming size guard, and avoids idle-connection timeouts |
| Output ceilings | 32,000 / 64,000 and the smaller ones above | Above the expected output plus thinking so documents finish in one request; they do not count toward the output limit |
| Fixed pause between steps | None | The retry policy waits when the API says so; a fixed pause is a guess |

## Test plan

| File | Covers |
|---|---|
| `tests/test_retry.py` | Each error class from the table: retried or raised, wait source, budget, visible waits, exactly one request on fail-fast errors |
| `tests/test_run_state.py` | Round-trip, atomic writes, completion marking, load errors |
| `tests/test_resume.py` | Failing the pipeline at each step in each context mode, then resuming: finished steps are not called again, the human gate is not asked twice, the final outputs are complete, no fixed pause between steps |
| `tests/test_context.py` | Context modes, the direction passed to the spec, and the bounded summary request (see [context-handling.md](context-handling.md)) |
| `tests/test_text_assembly.py` | How text blocks become one text: citation-split sentences stay whole, text around a search is separated once |
| `tests/test_effort.py` | The effort setting reaching every request (see [models-and-effort.md](models-and-effort.md)) |
| `tests/test_redo.py` | `--redo`: what runs again, what is kept and what is refused (see [stories-format.md](stories-format.md)) |
| `tests/test_stop_reasons.py` | One test per stop reason for `complete`, and `run_skill` and `_llm` going through it |
| `tests/test_request_load.py` | The search cap, caching scope, streaming restart, search count source and the ceilings in `config.yaml` |
| `tests/test_failed_steps.py` | The usage of paid rounds carried on a refusal, an API error, a blank answer and Ctrl-C; a failed step's row (stories failing after two rounds), its cost, reason and totals; no row when nothing was paid; a second row on resume; how the summary, report and jsonl show it |
| `tests/test_unrated_models.py` | A new run and a resume with an unrated model stop before any request, for any step; an unrated step keeps its output and records an unknown cost, which the totals, the summary, the report and a reload show |
| `tests/test_telemetry.py` | Waits and retries by kind, rate-limit headers (including failed attempts and a different tier), active time, and how the fields appear in the jsonl, report and terminal summary |
