#!/usr/bin/env python3
import sys
import json
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from agent import (
    client, CONFIG, load_profile,
    step_model, step_max_tokens,
    api_call_with_retry, run_skill,
)
from connectors.discord import fetch_feedback
from connectors.notion import push_stories
from observability import (
    RunTracker, StepMetrics, QualityResult,
    estimate_cost, check_quality, prompt_quality_failure,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    return json.loads(text)


def _divider(label: str = "") -> None:
    line = "─" * 70
    print(f"\n{line}")
    if label:
        print(label)
        print(line)


def compress(text: str, purpose: str, profile: dict) -> str:
    """Compress a large research/feedback/spec output to a dense summary using Haiku."""
    result, _ = _llm([{
        "role": "user",
        "content": (
            f"Compress the following {purpose} into 400–600 words of dense bullet-points. "
            "Preserve every specific fact, metric, competitor name, and actionable finding. "
            "Remove narrative prose, transitions, and duplicates only.\n\n"
            f"{text}"
        ),
    }], step="compress", profile=profile)
    return result


def _llm(messages: list, step: str = "", profile: dict | None = None) -> tuple[str, dict]:
    """Direct Claude API call using per-step model config from the active profile.

    Returns (text, usage) where usage = {"input_tokens": int, "output_tokens": int}.
    """
    if profile is None:
        profile = {}
    response = api_call_with_retry(
        lambda: client.messages.create(
            model=step_model(step, profile),
            max_tokens=step_max_tokens(step, profile),
            messages=messages,
        )
    )
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return response.content[0].text, usage


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
    document: str, research_ctx: str, feedback_ctx: str, chosen_direction: str, profile: dict
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
            f"## Chosen Product Direction\n\n{chosen_direction}\n\n"
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
    data = _parse_json(text)
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
    document: str, chosen_direction: str, research_ctx: str, feedback_ctx: str, profile: dict,
    interview_context: str = "",
) -> tuple[str, dict]:
    extra = (
        "PIPELINE CONTEXT — skip the interactive interview and generate the PRD "
        "directly using the information below as pre-filled answers.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"## Confirmed product direction\n\n{chosen_direction}\n\n"
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


_STORIES_FORMAT = """

OUTPUT FORMAT — follow exactly, no variation:
- Epics: `## Epic N: Title`
- Stories: `### Story N: Title`
- Story sub-sections (Background, Scope, Notes, Out of Scope, Views, Designs, \
Acceptance Criteria, Tracking / Metrics, Linked Stories / Dependencies): `#### Section Name`
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


def save_outputs(
    title: str, research: str, feedback: str, spec: str, stories: str, run_id: str,
    tracker: RunTracker | None = None,
) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    folder = Path("output") / f"{run_id}_{slug}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research-brief.md").write_text(research)
    (folder / "feedback-synthesis.md").write_text(feedback)
    (folder / "product-spec.md").write_text(spec)
    (folder / "user-stories.md").write_text(stories)
    if tracker is not None:
        tracker.write(folder)
    return folder


# ── Main ─────────────────────────────────────────────────────────────────────

def _track_step(
    step_name: str,
    fn,
    profile: dict,
    tracker: RunTracker,
    timestamp: str,
) -> str:
    """Call fn(), record metrics, run quality check, prompt on failure. Returns output text."""
    t0 = time.time()
    output, usage = fn()
    latency = time.time() - t0

    model = step_model(step_name, profile)
    cost = estimate_cost(model, usage["input_tokens"], usage["output_tokens"])
    quality = check_quality(step_name, output, profile)

    if not quality.passed:
        quality.user_continued = prompt_quality_failure(step_name, quality, output[:300])
        if not quality.user_continued:
            sys.exit(1)

    tracker.record(StepMetrics(
        step=step_name,
        model=model,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        latency_s=latency,
        cost_usd=cost,
        quality=quality,
    ))
    return output


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    input_path = Path(args[0]) if args else Path("idea.md")

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
    brief = profile.get("brief_mode", False)
    run_id = datetime.now().strftime('%Y-%m-%d_%H-%M')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    db_name = f"{title} — {timestamp}"

    tracker = RunTracker(title=title, timestamp=timestamp)

    label = f"[TEST RUN]  " if brief else ""
    print(f"Product Agent  ·  {label}{input_path.name}\n")

    # Pre-step
    print("[ Pre-step ] Identifying competitors and persona...")
    competitors, persona = extract_competitors_and_persona(document, profile)
    print(f"  Competitors : {', '.join(competitors)}")
    print(f"  Persona     : {persona}\n")

    # Phase A — research + feedback (tracked)
    print("[ Phase A ] Competitive research + user feedback...")
    phase_a_start = time.time()

    uc1_msg = (
        "Analyze the competitive landscape for the following product idea.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"Focus your analysis on these competitors: {', '.join(competitors)}"
    )
    research = _track_step(
        "research",
        lambda: run_skill("product-analysis", uc1_msg, "", profile, "research"),
        profile, tracker, timestamp,
    )
    print("  ✓ Competitive research complete")

    uc2_msg = (
        "Research user feedback relevant to the following product idea.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"Target persona: {persona}\n"
        f"Key products to find feedback on: {', '.join(competitors)}"
    )
    feedback = _track_step(
        "feedback",
        lambda: run_skill("product-user-feedback", uc2_msg, "", profile, "feedback"),
        profile, tracker, timestamp,
    )
    print("  ✓ User feedback synthesis complete\n")

    # Compress Phase A outputs — one Haiku call each produces a dense summary
    # used by all downstream steps instead of raw-truncating
    if not brief:
        print("[ Compress ] Summarizing research and feedback...")
        research_ctx = compress(research, "competitive research report", profile)
        feedback_ctx = compress(feedback, "user feedback synthesis", profile)
        print("  ✓ Summaries ready\n")
    else:
        research_ctx = research
        feedback_ctx = feedback

    # Smart cooldown — Phase B triggers a fresh Sonnet call; if Phase A finished
    # in under 65s the tokens-per-minute bucket may still be close to its limit.
    if not brief:
        elapsed = time.time() - phase_a_start
        remaining = int(65 - elapsed)
        if remaining > 0:
            print(f"[ Cooldown ] Waiting {remaining}s for rate limit window to reset...")
            time.sleep(remaining)
            print()

    # Synthesis (tracked)
    print("[ Synthesis ] Generating product direction proposals...")
    proposals = _track_step(
        "synthesis",
        lambda: generate_proposals(document, research_ctx, feedback_ctx, profile),
        profile, tracker, timestamp,
    )
    _divider()
    print(proposals)
    _divider()

    # Human gate
    chosen = input(
        "\nWhich direction do you want to pursue? (enter a number or describe your choice): "
    ).strip()
    print()

    # Optional interactive interview
    interview_context = ""
    if interactive:
        interview_context = run_interactive_interview(
            document, research_ctx, feedback_ctx, chosen, profile
        )

    # Phase B — spec + stories (tracked)
    print("[ Phase B ] Drafting product spec...")
    spec = _track_step(
        "spec",
        lambda: run_spec(document, chosen, research_ctx, feedback_ctx, profile, interview_context),
        profile, tracker, timestamp,
    )
    print("  ✓ Spec complete\n")

    print("[ Phase B ] Generating user stories...")
    stories = _track_step(
        "stories",
        lambda: run_stories(spec, profile, full_scope),
        profile, tracker, timestamp,
    )
    print("  ✓ User stories complete\n")

    push_stories(stories, db_name)

    output_folder = save_outputs(title, research, feedback, spec, stories, run_id, tracker)

    _divider("  Run summary")
    tracker.print_summary()
    _divider("  Run complete")
    print(f"  Profile       : {profile['name']}")
    print(f"  Output folder : {output_folder}/")
    print(  "  Files         : research-brief.md · feedback-synthesis.md")
    print(  "                  product-spec.md · user-stories.md")
    print(  "                  run-report.md · run-metrics.jsonl")
    _divider()
    print()


if __name__ == "__main__":
    main()
