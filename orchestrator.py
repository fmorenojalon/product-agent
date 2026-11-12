#!/usr/bin/env python3
import argparse
import hashlib
import sys
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from agent import (
    CONFIG, load_profile,
    step_model, step_max_tokens, step_effort,
    complete, parse_json, run_skill,
)
from connectors.discord import fetch_feedback
from connectors.notion import push_stories
from observability import (
    RunTracker, StepMetrics, QualityResult,
    estimate_cost, check_quality, profile_models, prompt_quality_failure, telemetry_from_usage,
    unrated_models,
)
from run_state import RunState, write_text_atomic


# ── Helpers ──────────────────────────────────────────────────────────────────

def _divider(label: str = "") -> None:
    line = "─" * 70
    print(f"\n{line}")
    if label:
        print(label)
        print(line)


def compress(text: str, purpose: str, profile: dict) -> str:
    """Summarise a research or feedback report with Haiku, for the `summary` context mode.

    One request: the step's max_tokens is a size limit, so a summary that runs long is cut
    there and never continued.
    """
    result, _ = _llm([{
        "role": "user",
        "content": (
            f"Compress the following {purpose} into 400–600 words of dense bullet-points. "
            "Preserve every specific fact, metric, competitor name, and actionable finding. "
            "Remove narrative prose, transitions, and duplicates only.\n\n"
            f"{text}"
        ),
    }], step="compress", profile=profile, stop_at_ceiling=True)
    return result


def _llm(
    messages: list, step: str = "", profile: dict | None = None, stop_at_ceiling: bool = False,
) -> tuple[str, dict]:
    """Direct Claude API call using per-step model config from the active profile.

    Returns (text, usage) summed across rounds. Continues past max_tokens, unless
    stop_at_ceiling keeps the text cut there, and raises StopReasonError on any other
    incomplete ending (see agent.complete).
    """
    if profile is None:
        profile = {}
    return complete(
        messages,
        model=step_model(step, profile),
        max_tokens=step_max_tokens(step, profile),
        stop_at_ceiling=stop_at_ceiling,
        effort=step_effort(step, profile),
        step=step,
    )


# ── Context the later steps read ─────────────────────────────────────────────

_CONTEXT_MODES = ("full", "summary")
_SUMMARY_FILES = {"research": "research-summary.md", "feedback": "feedback-summary.md"}
_SUMMARY_NOTE = (
    "(This is a short summary of the full {what}. Figures, quotes and details "
    "beyond it were left out.)\n\n"
)


def _context_mode(profile: dict) -> str:
    mode = profile.get("context_mode", "full")
    if mode not in _CONTEXT_MODES:
        raise ValueError(
            f"context_mode must be one of {', '.join(_CONTEXT_MODES)}, not {mode!r}. "
            "Set it in the profile in config.yaml."
        )
    return mode


def _reports_context(state: RunState, profile: dict, research: str, feedback: str) -> tuple[str, str]:
    """The research and feedback text that synthesis, the interview and the spec read.

    `full` (the default) passes both reports as they are. `summary` passes a short summary of
    each, made once and saved next to the reports.
    """
    if _context_mode(profile) == "full":
        return research, feedback

    paths = {key: state.folder / name for key, name in _SUMMARY_FILES.items()}
    if not (state.is_done("compress") and all(path.exists() for path in paths.values())):
        print("[ Compress ] Summarizing research and feedback...")
        summaries = {
            "research": compress(research, "competitive research report", profile),
            "feedback": compress(feedback, "user feedback synthesis", profile),
        }
        for key, summary in summaries.items():
            write_text_atomic(paths[key], summary)
        state.complete("compress")
        print(
            f"  ✓ Summaries ready: research {len(summaries['research'].split()):,} words "
            f"(from {len(research.split()):,}), feedback {len(summaries['feedback'].split()):,} words "
            f"(from {len(feedback.split()):,})\n"
        )
    return (
        _SUMMARY_NOTE.format(what="competitive research report") + paths["research"].read_text(),
        _SUMMARY_NOTE.format(what="user feedback synthesis") + paths["feedback"].read_text(),
    )


def _direction_section(proposals: str, chosen: str) -> str:
    """What the interview and the spec are told about the direction the user picked."""
    answer = (
        f'The user chose: "{chosen}"\n'
        "A number refers to the option with that number above; words are the user's own "
        "description of the direction. Specify that direction. Any recommendation in the "
        "proposals for another option does not apply."
        if chosen else
        "The user gave no answer. Specify the direction the proposals recommend."
    )
    return f"## Product directions proposed\n\n{proposals}\n\n## Confirmed product direction\n\n{answer}"


# ── Profile + mode selection ──────────────────────────────────────────────────

def select_profile() -> dict:
    profiles = CONFIG.get("profiles", {})
    print("Select a run profile:\n")
    for key in sorted(profiles):
        p = profiles[key]
        print(f"  {key}  {p['name']}")
        print(f"       {p['description']}")
        print(f"       Estimated cost: {p['estimated_cost']}")
        print()

    while True:
        choice = input(f"Enter profile number ({'/'.join(sorted(profiles))}): ").strip()
        if choice in profiles:
            selected = dict(profiles[choice])
            selected["key"] = choice
            print(f"\n  → {selected['name']}\n")
            return selected
        print(f"  Please enter one of: {', '.join(sorted(profiles))}")


def choose_mode(brief: bool) -> bool:
    """Returns True for interactive mode. Skipped in brief/test profiles."""
    if brief:
        return False
    print("Run mode:\n")
    print("  A  Autonomous    Work with the idea document as-is. No extra questions.")
    print("  I  Interactive   I'll ask a few focused questions before the spec.")
    print("                   Better output, ~3 extra minutes.\n")
    while True:
        choice = input("Mode (A/I): ").strip().upper()
        if choice in ("A", "I"):
            label = "Interactive" if choice == "I" else "Autonomous"
            print(f"\n  → {label}\n")
            return choice == "I"
        print("  Please enter A or I.")


def choose_story_scope() -> bool:
    """Returns True for full story generation, False to limit to 1 epic."""
    print("Story scope:\n")
    print("  F  Full      All epics and user stories  (production run).")
    print("  1  One epic  Most important epic only     (faster, useful for testing).\n")
    while True:
        choice = input("Scope (F/1): ").strip().upper()
        if choice in ("F", "1"):
            label = "Full" if choice == "F" else "One epic only"
            print(f"\n  → {label}\n")
            return choice == "F"
        print("  Please enter F or 1.")


# ── Interactive interview ─────────────────────────────────────────────────────

def _parse_questions(text: str) -> list[str]:
    questions = []
    for line in text.strip().splitlines():
        line = line.strip()
        if re.match(r"^\d+[\.\)]\s+", line):
            q = re.sub(r"^\d+[\.\)]\s+", "", line).strip()
            if q:
                questions.append(q)
    return questions


def run_interactive_interview(
    document: str, research_ctx: str, feedback_ctx: str, proposals: str, chosen: str, profile: dict
) -> str:
    questions_text, _ = _llm([{
        "role": "user",
        "content": (
            "You are about to generate a product spec (PRD). Review the inputs below and "
            "identify the 4–5 most impactful questions that are NOT yet answered by the documents. "
            "Focus on gaps that would materially improve the spec: success metrics, business case, "
            "MVP scope, delivery phases, target platforms or views, risks, or prioritisation.\n\n"
            "Rules:\n"
            "- Only ask about information genuinely missing from the idea document\n"
            "- Be specific and actionable — not 'tell me more' but "
            "'What is the target monthly active user goal within 6 months of launch?'\n"
            "- Do NOT ask about anything the idea document already addresses\n"
            "- Output numbered questions only — no preamble, no explanation\n\n"
            f"## Product Idea Document\n\n{document}\n\n"
            f"{_direction_section(proposals, chosen)}\n\n"
            f"## Competitive Research\n\n{research_ctx}\n\n"
            f"## User Feedback\n\n{feedback_ctx}"
        ),
    }], step="pre_step", profile=profile)

    questions = _parse_questions(questions_text)
    if not questions:
        return ""

    print("[ Interactive ] A few questions before the spec — press Enter to skip any:\n")
    qa_pairs = []
    for q in questions:
        answer = input(f"  {q}\n  > ").strip()
        print()
        if answer:
            qa_pairs.append(f"Q: {q}\nA: {answer}")

    if not qa_pairs:
        return ""
    return "## Additional context from pre-spec interview\n\n" + "\n\n".join(qa_pairs)


# ── Pipeline steps ────────────────────────────────────────────────────────────

def extract_competitors_and_persona(document: str, profile: dict) -> tuple[list[str], str]:
    text, _ = _llm([{
        "role": "user",
        "content": (
            "Read the following product idea document and extract:\n"
            '- "competitors": array of 3 existing product or company names '
            "most relevant to research for this idea\n"
            '- "persona": string describing the primary target user '
            '(e.g. "project manager", "indie developer")\n\n'
            "Return only valid JSON, no explanation.\n\n"
            f"## Product Idea Document\n\n{document}"
        ),
    }], step="pre_step", profile=profile)
    data = parse_json(text)
    if not isinstance(data.get("competitors"), list) or not isinstance(data.get("persona"), str):
        raise ValueError(f'The model\'s reply lacks "competitors" (a list) or "persona" (text):\n{text}')
    return data["competitors"], data["persona"]



def generate_proposals(document: str, research_ctx: str, feedback_ctx: str, profile: dict) -> tuple[str, dict]:
    return _llm([{
        "role": "user",
        "content": (
            "## Product Idea Document\n\n"
            f"{document}\n\n"
            f"## Competitive Research\n\n{research_ctx}\n\n"
            f"## User Feedback\n\n{feedback_ctx}\n\n"
            "Based on the product idea and research above, generate 2-3 distinct "
            "product direction proposals.\n"
            "For each proposal include:\n"
            "- A short name (e.g. 'Option 1 — Contextual AI Suggestions')\n"
            "- 2-3 sentences describing the direction\n"
            "- 1-2 sentences grounding it in the research\n\n"
            "Format them clearly and number them so the user can pick one.\n"
            "Use only prose and bullet points — no markdown tables."
        ),
    }], step="synthesis", profile=profile)


def run_spec(
    document: str, proposals: str, chosen: str, research_ctx: str, feedback_ctx: str, profile: dict,
    interview_context: str = "",
) -> tuple[str, dict]:
    extra = (
        "PIPELINE CONTEXT — skip the interactive interview and generate the PRD "
        "directly using the information below as pre-filled answers.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"{_direction_section(proposals, chosen)}\n\n"
        f"## Competitive research\n\n{research_ctx}\n\n"
        f"## User feedback synthesis\n\n{feedback_ctx}"
    )
    if interview_context:
        extra += f"\n\n{interview_context}"
    return run_skill(
        "product-specification",
        "Generate a PRD based on the product idea document and research context provided.",
        extra_context=extra,
        profile=profile,
        step="spec",
    )


# Stories are written compactly: the skill's own format runs to about 9,000 characters a story.
# These rules override the skill's length and section rules. Everything before the acceptance
# criteria becomes the Notion description, so the acceptance criteria come last (see
# connectors.notion.parse_stories).
_STORIES_FORMAT = """

OUTPUT FORMAT — follow exactly, no variation. These rules override the skill's own length and \
section rules: write compact stories.
- Start directly with the first epic: no overview, no dependency map, no closing summary.
- Epics: `## Epic N: Title`, then a summary of at most 3 sentences.
- Stories: `### Story N: Title`
- Each story has only the parts below, in this order, and nothing else:
  1. One scope statement: "As a [persona], I want [goal], So that [benefit]." Add a second \
statement only for a different persona.
  2. `#### Background` — only when the reason for the story is not evident from the epic. At most \
2 sentences. Otherwise leave the heading out.
  3. `#### Out of Scope` — at most 3 bullets, only when needed.
  4. `Depends on:` — one line naming the stories this one needs, only when there are any.
  5. `Assumption:` — one line, only when the story rests on an unconfirmed assumption.
  6. `#### Acceptance Criteria` — last. At most 8 statements, each on one line, in Given/When/Then \
form, in at most 3 named groups (the group name in bold). Cover the main flow, the key variants and \
the single most important error case. Merge statements that test the same behavior.
- Do not write an intro table, Notes, Views, Designs, Tracking / Metrics or Linked Stories sections.
"""


_STORIES_BRIEF = """
Output exactly this structure and nothing else:

## Epic 1: Placeholder Epic

## Story 1: Placeholder Story

| User Story | Files and Documentation |
|------------|------------------------|
| As a test user, I want to validate the pipeline. | Designs: TBD |

#### Background
Placeholder background.

#### Acceptance Criteria

## Test AC
- Given the pipeline runs, When stories are generated, Then Notion receives rows.
"""


def run_stories(spec: str, profile: dict, full_scope: bool = True) -> tuple[str, dict]:
    brief = profile.get("brief_mode", False)
    if brief:
        # In test mode skip the spec entirely — return a hardcoded stub so
        # parse_stories always finds stories and Notion write is exercised.
        return run_skill(
            "product-user-story",
            _STORIES_BRIEF,
            profile=profile,
            step="stories",
        )
    scope_note = (
        "" if full_scope else
        "\n\nIMPORTANT: Generate stories for ONE epic only — the single most critical epic "
        "for an MVP. Do not generate stories for any other epic."
    )
    return run_skill(
        "product-user-story",
        f"Generate epics and user stories for the following product specification:"
        f"\n\n{spec}{scope_note}{_STORIES_FORMAT}",
        profile=profile,
        step="stories",
    )


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _new_run_folder(title: str, run_id: str) -> Path:
    """output/<run_id>_<slug>, with -2, -3 ... appended if an earlier run already used the name."""
    base = Path("output") / f"{run_id}_{_slug(title)}"
    folder, n = base, 1
    while folder.exists():
        n += 1
        folder = base.with_name(f"{base.name}-{n}")
    return folder


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Main ─────────────────────────────────────────────────────────────────────

def _price(step_name: str, model: str, usage: dict) -> float | None:
    """The cost of a step's usage, or None (with a warning) when its model has no rate."""
    try:
        return estimate_cost(
            model,
            usage["input_tokens"],
            usage["output_tokens"],
            usage.get("cache_write_tokens", 0),
            usage.get("cache_read_tokens", 0),
            usage.get("search_count", 0),
        )
    except ValueError:
        # The step was paid for and its output must be kept: record the cost as unknown.
        print(f"\n  ⚠  Cost unknown for step '{step_name}': {model!r} has no rate in _RATES (observability.py).")
        return None


def _step_metrics(
    step_name: str, profile: dict, usage: dict, latency: float, quality: QualityResult, failed: str | None = None,
) -> StepMetrics:
    model = step_model(step_name, profile)
    return StepMetrics(
        step=step_name,
        model=model,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        latency_s=latency,
        cost_usd=_price(step_name, model, usage),
        quality=quality,
        cache_write_tokens=usage.get("cache_write_tokens", 0),
        cache_read_tokens=usage.get("cache_read_tokens", 0),
        search_count=usage.get("search_count", 0),
        failed=failed,
        **telemetry_from_usage(usage),
    )


def _failure_reason(error: BaseException) -> str:
    """One line saying why a step ended without an output."""
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    return " ".join(f"{type(error).__name__}: {error}".split())[:200]


def _track_step(
    step_name: str,
    fn,
    profile: dict,
    tracker: RunTracker,
    reject_dir: Path | None = None,
) -> str:
    """Call fn(), record metrics, run quality check, prompt on failure. Returns output text.

    If fn() fails after paid requests (see agent.complete), a row marked failed records what
    they cost, and the metrics are saved to reject_dir before the error goes on.

    If the user declines to continue past a failed check, the step's metrics and output are
    saved to reject_dir before the run exits — the step was paid for.
    """
    t0 = time.time()
    try:
        output, usage = fn()
    except BaseException as error:
        paid = getattr(error, "paid_usage", None)
        if paid:
            failed = _step_metrics(
                step_name, profile, paid, time.time() - t0, QualityResult(heuristic_ok=False), _failure_reason(error),
            )
            tracker.record(failed)
            spent = "cost unknown" if failed.cost_usd is None else f"${failed.cost_usd:.4f}"
            print(f"\n  ⚠  Step '{step_name}' failed after paid requests ({spent}); recorded in run-report.md.")
            if reject_dir is not None:
                tracker.write(reject_dir)
        raise
    latency = time.time() - t0

    quality = check_quality(step_name, output, profile)

    declined = False
    if not quality.passed:
        quality.user_continued = prompt_quality_failure(step_name, quality, output[:300])
        declined = not quality.user_continued

    tracker.record(_step_metrics(step_name, profile, usage, latency, quality))
    if declined:
        if reject_dir is not None:
            write_text_atomic(reject_dir / f"{step_name}.rejected.md", output)
            tracker.write(reject_dir)
        sys.exit(1)
    return output


def _run_step(
    state: RunState,
    tracker: RunTracker,
    profile: dict,
    step: str,
    filename: str,
    fn,
    label: str | None = None,
) -> str:
    """Run one tracked step, saving its output and metrics at once.

    A step finished in an earlier attempt is loaded from disk instead of being run again.
    """
    path = state.folder / filename
    if state.is_done(step):
        print(f"  ↺ {label or step} — loaded from {filename}")
        return path.read_text()
    output = _track_step(step, fn, profile, tracker, reject_dir=state.folder)
    write_text_atomic(path, output)
    tracker.write(state.folder)
    state.complete(step)
    if label:
        print(f"  ✓ {label} complete")
    return output


# The order a run goes through its steps, and the file each step writes. --redo clears a step
# and every step after it, because each later step is built from the ones before.
_STEP_ORDER = [
    "pre_step", "research", "feedback", "compress", "synthesis", "gate", "interview",
    "spec", "stories", "notion",
]
_STEP_FILES = {
    "research": "research-brief.md",
    "feedback": "feedback-synthesis.md",
    "synthesis": "proposals.md",
    "spec": "product-spec.md",
    "stories": "user-stories.md",
}


def _redo(state: RunState, step: str) -> list[str]:
    """Make `step` and every step after it run again. Returns the steps cleared.

    The earlier output of each is kept as <name>.previous<ext> (a second redo replaces it), so
    the old and new versions can be compared. Costs already paid stay in the metrics.
    """
    cleared = _STEP_ORDER[_STEP_ORDER.index(step):]
    for name in cleared:
        if name in _STEP_FILES:
            path = state.folder / _STEP_FILES[name]
            if path.exists():
                path.replace(path.with_name(f"{path.stem}.previous{path.suffix}"))
    state.forget(cleared)
    return cleared


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Product Agent — product idea to Notion-ready user stories.")
    parser.add_argument(
        "input", nargs="?",
        help="idea document (default: idea.md; with --resume, the one the run started with)",
    )
    parser.add_argument("--resume", metavar="RUN_DIR", help="continue a stopped run from its output folder")
    parser.add_argument(
        "--redo", metavar="STEP", choices=list(_STEP_FILES),
        help=(
            "with --resume: run STEP and every step after it again, for example stories to try "
            "a new story format without paying for the research again. Choices: "
            + ", ".join(_STEP_FILES) + ". The earlier outputs are kept as <name>.previous.md. "
            "Redoing stories pushes a new Notion database."
        ),
    )
    return parser.parse_args(argv)


def _load_document(state: RunState, override: str | None) -> tuple[Path, str]:
    """The idea document of a run being resumed. Warns if it changed since the run began."""
    input_path = Path(override or state.get("input_path"))
    if not input_path.exists():
        print(f"Error: '{input_path}' not found. Pass the idea document explicitly:")
        print(f"  python orchestrator.py my-idea.md --resume {state.folder}")
        sys.exit(1)
    document = input_path.read_text()
    if _sha256(document) != state.get("input_sha256"):
        print(f"Warning: '{input_path}' has changed since this run started.")
        if input("Continue with the changed document? (y/n): ").strip().lower() != "y":
            sys.exit(1)
        state.set(input_sha256=_sha256(document))
    return input_path, document


def _print_resume_hint(folder: Path) -> None:
    print(f"\n  Run stopped. Finished steps are saved in {folder}/")
    print(f"  Resume with: python orchestrator.py --resume {folder}\n")


def _run_pipeline(state: RunState, profile: dict, document: str) -> None:
    folder = state.folder
    title = state.get("title")
    timestamp = state.get("timestamp")
    _context_mode(profile)  # fail on a bad setting before any paid call
    tracker = RunTracker.load(folder, title, timestamp)
    db_name = f"{title} — {timestamp}"

    # Pre-step
    if state.is_done("pre_step"):
        print("[ Pre-step ] Competitors and persona loaded from earlier run")
    else:
        print("[ Pre-step ] Identifying competitors and persona...")
        competitors, persona = extract_competitors_and_persona(document, profile)
        state.complete("pre_step", competitors=competitors, persona=persona)
    competitors, persona = state.get("competitors"), state.get("persona")
    print(f"  Competitors : {', '.join(competitors)}")
    print(f"  Persona     : {persona}\n")

    # Phase A — research + feedback (tracked)
    print("[ Phase A ] Competitive research + user feedback...")

    uc1_msg = (
        "Analyze the competitive landscape for the following product idea.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"Focus your analysis on these competitors: {', '.join(competitors)}"
    )
    research = _run_step(
        state, tracker, profile, "research", _STEP_FILES["research"],
        lambda: run_skill("product-analysis", uc1_msg, "", profile, "research"),
        "Competitive research",
    )

    uc2_msg = (
        "Research user feedback relevant to the following product idea.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"Target persona: {persona}\n"
        f"Key products to find feedback on: {', '.join(competitors)}"
    )
    feedback = _run_step(
        state, tracker, profile, "feedback", _STEP_FILES["feedback"],
        lambda: run_skill("product-user-feedback", uc2_msg, "", profile, "feedback"),
        "User feedback synthesis",
    )
    print()

    # What synthesis, the interview and the spec read of the two reports (see context_mode)
    research_ctx, feedback_ctx = _reports_context(state, profile, research, feedback)

    # Synthesis (tracked)
    print("[ Synthesis ] Generating product direction proposals...")
    proposals = _run_step(
        state, tracker, profile, "synthesis", _STEP_FILES["synthesis"],
        lambda: generate_proposals(document, research_ctx, feedback_ctx, profile),
    )

    # Human gate — the answer is saved at once so it is never asked twice
    if not state.is_done("gate"):
        _divider()
        print(proposals)
        _divider()
        chosen = input(
            "\nWhich direction do you want to pursue? (enter a number or describe your choice): "
        ).strip()
        print()
        state.complete("gate", chosen=chosen)
    chosen = state.get("chosen")

    # Optional interactive interview
    if state.get("interactive") and not state.is_done("interview"):
        state.complete("interview", interview_context=run_interactive_interview(
            document, research_ctx, feedback_ctx, proposals, chosen, profile
        ))
    interview_context = state.get("interview_context", "")

    # Phase B — spec + stories (tracked)
    print("[ Phase B ] Drafting product spec...")
    spec = _run_step(
        state, tracker, profile, "spec", _STEP_FILES["spec"],
        lambda: run_spec(document, proposals, chosen, research_ctx, feedback_ctx, profile, interview_context),
        "Spec",
    )
    print()

    print("[ Phase B ] Generating user stories...")
    stories = _run_step(
        state, tracker, profile, "stories", _STEP_FILES["stories"],
        lambda: run_stories(spec, profile, state.get("full_scope")),
        "User stories",
    )
    print()

    if not state.is_done("notion"):
        push_stories(stories, db_name)
        state.complete("notion")

    _divider("  Run summary")
    tracker.print_summary()
    _divider("  Run complete")
    print(f"  Profile       : {profile['name']}")
    print(f"  Output folder : {folder}/")
    print(  "  Files         : research-brief.md · feedback-synthesis.md")
    print(  "                  proposals.md · product-spec.md · user-stories.md")
    print(  "                  run-report.md · run-metrics.jsonl · run-state.json")
    _divider()
    print()


def main() -> None:
    args = _parse_args(sys.argv[1:])

    if args.redo and not args.resume:
        print("Error: --redo works on an existing run: add --resume <run folder>.")
        sys.exit(1)

    if args.resume:
        try:
            state = RunState.load(Path(args.resume))
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}")
            sys.exit(1)
        input_path, document = _load_document(state, args.input)
        if args.redo:
            cleared = _redo(state, args.redo)
            print(f"Redoing {args.redo}: {', '.join(cleared)} will run again. "
                  "Earlier outputs are kept as <name>.previous.md.\n")
    else:
        input_path = Path(args.input or "idea.md")
        if not input_path.exists():
            print(f"Error: '{input_path}' not found.")
            print("Create an idea.md file with your product idea, or pass a file path:")
            print("  python orchestrator.py my-idea.md")
            sys.exit(1)

        # Profile + mode selection
        profile = select_profile()
        interactive = choose_mode(profile.get("brief_mode", False))
        full_scope = choose_story_scope()

        document = input_path.read_text()
        title = input_path.stem
        now = datetime.now()
        state = RunState.create(
            _new_run_folder(title, now.strftime('%Y-%m-%d_%H-%M')),
            input_path=str(input_path),
            input_sha256=_sha256(document),
            title=title,
            timestamp=now.strftime('%Y-%m-%d %H:%M'),
            profile_key=profile["key"],
            interactive=interactive,
            full_scope=full_scope,
        )

    key = state.get("profile_key")
    profile = dict(load_profile(key))
    if not profile:
        print(f"Error: profile '{key}' is not in config.yaml.")
        sys.exit(1)
    profile["key"] = key

    # Before any request: a model without a rate would be paid for and then priced as unknown.
    unrated = unrated_models(profile_models(profile))
    if unrated:
        print(f"Error: profile '{key}' uses {', '.join(unrated)}, which has no rate in _RATES (observability.py).")
        print("Add its prices there (pricing page: https://platform.claude.com/docs/en/about-claude/pricing)")
        print("or change the model in config.yaml. Nothing was sent to the API.")
        print(f"Then resume with: python orchestrator.py --resume {state.folder}")
        sys.exit(1)

    label ="[TEST RUN]  " if profile.get("brief_mode", False) else ""
    print(f"Product Agent  ·  {label}{input_path.name}\n")
    if args.resume:
        print(f"Resuming {state.folder}/ — finished: {', '.join(state.finished) or 'nothing yet'}\n")

    try:
        _run_pipeline(state, profile, document)
    except BaseException:
        _print_resume_hint(state.folder)
        raise


if __name__ == "__main__":
    main()
