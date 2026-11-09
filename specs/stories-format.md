# Story Format

## In short

- Stories are written **compactly**: one scope statement, a short optional background, at most 8 acceptance criteria, and a few optional one-liners. The target is about 3,000 characters a story, against about 9,000 for the long format the skill describes.
- The pipeline asks for this by adding rules to the stories request. The skill file itself is unchanged.
- Notion receives the epic, the story title, a description (everything before the acceptance criteria) and the acceptance criteria.

## What a story contains

| Part | Rule | Goes to Notion as |
|---|---|---|
| Title | `### Story N: Title` under `## Epic N: Title` | Name, and the Epic of the row |
| Scope statement | "As a [persona], I want [goal], So that [benefit]." A second one only for a different persona | Description |
| `#### Background` | Only when the reason for the story is not evident from the epic. At most 2 sentences | Description |
| `#### Out of Scope` | At most 3 bullets, only when needed | Description |
| `Depends on:` | One line naming the stories this one needs, only when there are any | Description |
| `Assumption:` | One line, only when the story rests on an unconfirmed assumption | Description |
| `#### Acceptance Criteria` | Last. At most 8 one-line Given/When/Then statements in at most 3 bold-named groups, covering the main flow, the key variants and the most important error case | Acceptance Criteria |

An epic has a summary of at most 3 sentences. The output starts with the first epic, with no overview, dependency map or closing summary.

The acceptance criteria come last because the Notion push takes everything before them as the description and stops them at the next heading.

## What is not written

| Left out | Its share of the long format | Where it can be found |
|---|---|---|
| Notes | 16% | Mostly in the spec |
| Linked stories and dependencies (long) | 9% | One `Depends on:` line |
| Designs | 7% | Placeholder text and lists of screen states; the spec may hold some |
| Tracking and metrics | 6% | The spec's tracking requirements |
| The intro table | up to 4% (measured with the title) | It repeated the scope statement |
| Views | 2% | Mostly in the spec |

The shares come from one measured run of the long format: 12 stories, 111,932 characters, about 8,900 a story. Acceptance criteria were 38% of it, with 172 scenarios, about 14 a story.

## Measuring a run

The measure is **characters per story**, because it does not depend on the tokenizer or on the number of stories:

```bash
RUN=$(ls -dt output/*/ | head -1)
grep -c "^### Story" "$RUN/user-stories.md"
wc -c "$RUN/user-stories.md"
```

Divide the characters by the number of stories. The long format averaged 8,900. The target is 3,500 or fewer, a cut of 60%, and ideally 2,700 or fewer, a cut of 70%.

## Trying a change cheaply

Running a whole profile to test a story format costs about $1. To run only the stories step on a finished run:

```bash
python orchestrator.py --resume output/<run folder> --redo stories
```

The step runs again from the saved spec. The earlier output stays beside it as `user-stories.previous.md`, so the two can be compared, and a second `--redo` replaces that copy. Both attempts stay in the cost totals, and the report lists the step twice. If `NOTION_TOKEN` is set, the push creates a new Notion database.

`--redo` also takes `research`, `feedback`, `synthesis` and `spec`. It runs that step and every step after it, because each is built from the ones before. Redoing `synthesis` or an earlier step asks for the direction again.

## Constraints and limitations

What this design does not guarantee, and what to do about it. Items marked "not measured" are not established facts.

1. **The caps are instructions, not checks.** Nothing verifies that a story has at most 8 criteria or that the model leaves out the sections it is told to. *What to do:* measure characters per story after a run.
2. **The size reduction is not measured.** The target comes from the section shares above. A real run is the only evidence.
3. **Edge cases beyond the cap are not in the stories.** The spec still holds them. A story with more behaviours than fit in 8 criteria has to be split by the model, or loses the least important ones.
4. **Tracking events, design states and implementation notes are not in the stories.** The spec holds most of them; whether it holds all of them is not checked.
5. **The skill describes the long format.** `product-user-story/SKILL.md` is unchanged and the pipeline's rules override it. Using the skill outside the pipeline gives the long format.
6. **The Notion push depends on the headings.** The epic header, the story headers and `#### Acceptance Criteria` must keep their form. The regression test `tests/test_uc4_parse.py` runs the real API to check this and is skipped unless `RUN_FORMAT_TESTS=1` is set.
7. **`--redo` keeps one earlier copy.** A second redo of the same step replaces `<name>.previous.md`.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the rules live | In the stories request, not in the skill | The skill stays usable on its own; the pipeline decides how long its stories are |
| What goes | Notes, designs, views, tracking, the intro table, long dependencies | Together about 44% of the long format, mostly text the spec already holds or placeholders |
| Criteria cap | 8 per story, in at most 3 groups | The criteria were 38% of the long format; halving them with the cuts above reaches about 60 to 70% |
| Tracking events | Left out | The spec holds them |
| Cheap re-runs | `--redo` | Changing the format means several tries, and a full run costs about $1 |

## Test plan

| File | Covers |
|---|---|
| `tests/test_stories_format.py` | The rules the request carries, that the acceptance criteria come last, that the request carries the format, and that a compact story parses into the epic, description and criteria Notion needs |
| `tests/test_redo.py` | `--redo` for each step: what runs again, what is kept, the direction asked again, both attempts in the totals, a failed redo that can be resumed, and what is refused |
