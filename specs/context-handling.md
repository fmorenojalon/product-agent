# Context Handling — What Each Step Reads

## In short

- The research and feedback reports are long (about 6,000 and 4,500 tokens, estimated from their length in one run). Three later steps need their content: synthesis, the interview (interactive mode) and the spec.
- By default those steps read **both reports exactly as written**. Nothing is left out. This is `context_mode: full`.
- A second mode, `context_mode: summary`, gives them a short summary of each report instead. The summaries are saved as files you can open.
- The interview and the spec also receive the **proposals and your choice**, so they know which direction to specify.

Out of scope: choosing between the two modes automatically from the size of a request, a structured extract that replaces the free-text summary, summaries made after the human gate, and retrieval with embeddings. The reports are far smaller than the model's context window.

## What each step reads

| Step | Reads | Notes |
|---|---|---|
| Pre-step | The idea document | |
| Research | The idea document and the competitors | Searches the web |
| Feedback | The idea document, the persona and the competitors | Searches the web |
| Synthesis | The idea document and both reports | Reports as set by the context mode |
| Human gate | The proposals | You enter a number or describe a direction |
| Interview (interactive mode only) | The idea document, the proposals and your choice, both reports | Reports as set by the context mode |
| Spec | The idea document, the proposals and your choice, both reports, the interview answers | Reports as set by the context mode |
| Stories | The full spec | Always the full spec: every requirement must reach a story |

## The two context modes

Set `context_mode` in a profile in `config.yaml`. The default is `full`, and every shipped profile sets it explicitly.

| | `full` (default) | `summary` |
|---|---|---|
| What later steps read | Both reports, as written | A short summary of each report |
| Extra model calls | None | Two Haiku requests (the `compress` step), before synthesis |
| Extra files | None | `research-summary.md`, `feedback-summary.md` |
| Input to each reading step | Both reports: about 10,500 tokens (estimated from their length in one run) | At most about 3,000 tokens (the `compress` ceiling of 1,500 tokens, twice) |
| What is left out | Nothing | Figures, quotes and details beyond about 1,100 words per report |

The setting is read from `config.yaml` each time a run starts or resumes. A value other than `full` or `summary` stops the run before any model call.

### How `summary` mode works

1. After research and feedback finish, one Haiku request summarises each report. The prompt asks for 400 to 600 words of dense bullet points that keep every specific fact.
2. Each summary is **one request**. The `compress` step's `max_tokens` (1,500, about 1,100 words) is a size limit: if the model writes more, the summary ends where it reaches the limit and is not continued.
3. Both summaries are written to the output folder, then the step is marked done. The terminal prints the size of each, for example `Summaries ready: research 640 words (from 3,900), feedback 610 words (from 3,000)`.
4. Each step that reads a summary is told so: it begins with "This is a short summary of the full competitive research report. Figures, quotes and details beyond it were left out."

## The direction you choose

At the human gate you type a number or describe a direction in your own words. The interview and the spec receive:

- the whole proposals text, and
- your answer, with an instruction: a number means the option with that number, words are your own description, specify that direction, and a recommendation in the proposals for another option does not apply.

The whole text is sent instead of one parsed option because the option labels change from run to run. If you give no answer, the step is told to specify the direction the proposals recommend.

## Files

| File | Written | When |
|---|---|---|
| `research-brief.md`, `feedback-synthesis.md` | As each step finishes | Every run |
| `proposals.md` | When synthesis finishes | Every run |
| `research-summary.md`, `feedback-summary.md` | When both summaries are made | `summary` mode only |

## Resuming

| | `full` | `summary` |
|---|---|---|
| Reports | Read from their files on every start and resume, so an edit to `research-brief.md` before a resume reaches the later steps | Summaries are read from their files and not made again |
| A missing summary file | Not used | Both summaries are made again |
| An edited report | Reaches the later steps | Does **not** reach them. Delete the summary files to make them again |

Changing `context_mode` between an attempt and its resume changes what the steps that still have to run read. Steps already finished are not run again.

## Constraints and limitations

What this design does not guarantee, and what to do about it. Items marked "measured once" or "estimate" are not established facts.

1. **`full` mode sends more input than `summary`.** Synthesis, the spec and, in interactive mode, the interview each read both reports. At published rates this is roughly $0.03 more per run than summaries at the size the ceiling allows, and about $0.04 with the interview (estimate, not measured). *What to do:* nothing; this is the price of leaving nothing out.
2. **`summary` mode does not make a low rate-limit tier workable.** At a limit of 30,000 input tokens per minute, the research and feedback steps cannot pass (see limitation 2 in [rate-management.md](rate-management.md)), whatever the later steps read.
3. **A summary leaves out detail, and verbatim user quotes are the most at risk.** The prompt tells the model to remove narrative prose, and quotes are prose. In one measured run, summaries of about 6,000 and 4,400 words kept 3 of 21 verbatim quotes, 98 to 100% of the numbers and 79 to 84% of the capitalised names. A summary held to about 1,100 words keeps less; that has not been measured. *What to do:* use `full` unless you have a reason not to.
4. **A summary can be cut off.** When the model writes past the ceiling, the end of the summary is lost, and the end of a report holds its strategic conclusions. The prompt does not ask for the most important findings first.
5. **Summaries are not quality-checked, and their cost is not in the report.** The two Haiku requests belong to no tracked step (see limitation 6 in [rate-management.md](rate-management.md)).
6. **Both modes pass along only what the reports say.** The reports carry no source links (none in the measured run), because the search results are not kept, so a claim in the spec cannot be traced to a page. The spec skill is told to state an assumption when information is missing, so a fact absent from the context can come back as an assumption in the spec. This is likelier in `summary` mode.
7. **Summaries are made before the human gate**, so they cannot favour the direction you choose.
8. **A choice other than the recommended one is not verified with the real API.** The proposals text contains the model's own recommendation, and the instruction tells the spec to disregard it. Offline tests check that the proposals and your answer reach the spec and the interview. They cannot check that the spec follows them. *What to do:* choose a direction other than the recommended one in a real run and read the spec's positioning and pricing.
9. **A report edited after its summary was made does not reach the later steps** in `summary` mode (see Resuming).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Default mode | `full` | The spec is the main deliverable and should see all the research; the extra input costs about $0.03 per run |
| `summary` mode | Kept as an option | Lets a run read less input when that is wanted |
| Summary size | One request, cut at the ceiling | A summary that is continued grows past the size it should hold |
| Where summaries live | Files in the output folder | They can be opened and read; the state file stays small |
| Direction text | The whole proposals plus your answer | No parsing of option labels, which vary |
| Stories | Always read the full spec | Compressing the spec would drop requirements before they become stories |
| The test profile | Same default path as every other profile | A test run exercises the path a paid run takes |

## Test plan

| File | Covers |
|---|---|
| `tests/test_context.py` | Both reports reach synthesis and the spec unchanged in `full` mode; no summary is made; the proposals and the answer reach the interview and the spec; summaries are one request, saved as files, labelled, reused on resume and made again when a file is missing; the setting's default, values and error; every shipped profile sets a mode |
| `tests/test_resume.py` | Failing the pipeline at each step in each mode, then resuming: finished steps, summaries included, are not paid for again |
