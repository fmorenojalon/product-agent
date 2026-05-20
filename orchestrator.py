#!/usr/bin/env python3
import sys
import json
import re
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


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[output truncated]"


def _llm(messages: list, step: str = "", profile: dict | None = None) -> str:
    """Direct Claude API call using per-step model config from the active profile."""
    if profile is None:
        profile = {}
    response = api_call_with_retry(
        lambda: client.messages.create(
            model=step_model(step, profile),
            max_tokens=step_max_tokens(step, profile),
            messages=messages,
        )
    )
    return response.content[0].text


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
            selected = profiles[choice]
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
    document: str, research: str, feedback: str, chosen_direction: str, profile: dict
) -> str:
    max_chars = 2000 if profile.get("brief_mode") else 3000
    questions_text = _llm([{
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
            f"## Competitive Research\n\n{_truncate(research, max_chars)}\n\n"
            f"## User Feedback\n\n{_truncate(feedback, max_chars)}"
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
    data = _parse_json(_llm([{
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
    }], step="pre_step", profile=profile))
    return data["competitors"], data["persona"]


def run_research(
    document: str, competitors: list[str], persona: str, profile: dict
) -> tuple[str, str]:
    uc1_msg = (
        "Analyze the competitive landscape for the following product idea.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"Focus your analysis on these competitors: {', '.join(competitors)}"
    )
    uc2_msg = (
        "Research user feedback relevant to the following product idea.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"Target persona: {persona}\n"
        f"Key products to find feedback on: {', '.join(competitors)}"
    )

    research = run_skill("product-analysis", uc1_msg, "", profile, "research")
    print("  ✓ Competitive research complete")

    feedback = run_skill("product-user-feedback", uc2_msg, "", profile, "feedback")
    print("  ✓ User feedback synthesis complete")

    return research, feedback


def generate_proposals(document: str, research: str, feedback: str, profile: dict) -> str:
    brief = profile.get("brief_mode", False)
    max_chars = 2000 if brief else 3000
    return _llm([{
        "role": "user",
        "content": (
            "## Product Idea Document\n\n"
            f"{document}\n\n"
            f"## Competitive Research\n\n{_truncate(research, max_chars)}\n\n"
            f"## User Feedback\n\n{_truncate(feedback, max_chars)}\n\n"
            "Based on the product idea and research above, generate 2-3 distinct "
            "product direction proposals.\n"
            "For each proposal include:\n"
            "- A short name (e.g. 'Option 1 — Contextual AI Suggestions')\n"
            "- 2-3 sentences describing the direction\n"
            "- 1-2 sentences grounding it in the research\n\n"
            "Format them clearly and number them so the user can pick one."
        ),
    }], step="synthesis", profile=profile)


def run_spec(
    document: str, chosen_direction: str, research: str, feedback: str, profile: dict,
    interview_context: str = "",
) -> str:
    brief = profile.get("brief_mode", False)
    max_chars = 2000 if brief else 3000
    extra = (
        "PIPELINE CONTEXT — skip the interactive interview and generate the PRD "
        "directly using the information below as pre-filled answers.\n\n"
        f"## Product Idea Document\n\n{document}\n\n"
        f"## Confirmed product direction\n\n{chosen_direction}\n\n"
        f"## Competitive research\n\n{_truncate(research, max_chars)}\n\n"
        f"## User feedback synthesis\n\n{_truncate(feedback, max_chars)}"
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


def run_stories(spec: str, profile: dict) -> str:
    return run_skill(
        "product-user-story",
        f"Generate epics and user stories for the following product specification:\n\n{spec}",
        profile=profile,
        step="stories",
    )


def save_outputs(
    title: str, research: str, feedback: str, spec: str, stories: str
) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    folder = Path("output") / f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{slug}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research-brief.md").write_text(research)
    (folder / "feedback-synthesis.md").write_text(feedback)
    (folder / "product-spec.md").write_text(spec)
    (folder / "user-stories.md").write_text(stories)
    return folder


# ── Main ─────────────────────────────────────────────────────────────────────

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

    document = input_path.read_text()
    title = input_path.stem
    brief = profile.get("brief_mode", False)

    label = f"[TEST RUN]  " if brief else ""
    print(f"Product Agent  ·  {label}{input_path.name}\n")

    # Pre-step
    print("[ Pre-step ] Identifying competitors and persona...")
    competitors, persona = extract_competitors_and_persona(document, profile)
    print(f"  Competitors : {', '.join(competitors)}")
    print(f"  Persona     : {persona}\n")

    # Phase A — parallel research
    print("[ Phase A ] Competitive research + user feedback...")
    research, feedback = run_research(document, competitors, persona, profile)
    print()

    # Synthesis
    print("[ Synthesis ] Generating product direction proposals...")
    proposals = generate_proposals(document, research, feedback, profile)
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
            document, research, feedback, chosen, profile
        )

    # Phase B — sequential
    print("[ Phase B ] Drafting product spec...")
    spec = run_spec(document, chosen, research, feedback, profile, interview_context)
    print("  ✓ Spec complete\n")

    print("[ Phase B ] Generating user stories...")
    stories = run_stories(spec, profile)
    print("  ✓ User stories complete\n")

    push_stories(stories)

    output_folder = save_outputs(title, research, feedback, spec, stories)

    _divider("  Run complete")
    print(f"  Profile       : {profile['name']}")
    print(f"  Output folder : {output_folder}/")
    print(  "  Files         : research-brief.md · feedback-synthesis.md")
    print(  "                  product-spec.md · user-stories.md")
    _divider()
    print()


if __name__ == "__main__":
    main()
