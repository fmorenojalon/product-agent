#!/usr/bin/env python3
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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


# ── Profile selection ─────────────────────────────────────────────────────────

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

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(run_skill, "product-analysis", uc1_msg, "", profile, "research"): "research",
            executor.submit(run_skill, "product-user-feedback", uc2_msg, "", profile, "feedback"): "feedback",
        }
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
            label = "Competitive research" if key == "research" else "User feedback synthesis"
            print(f"  ✓ {label} complete")

    return results["research"], results["feedback"]


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
    document: str, chosen_direction: str, research: str, feedback: str, profile: dict
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
    folder = Path("output") / f"{datetime.now().strftime('%Y-%m-%d')}_{slug}"
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

    # Profile selection
    profile = select_profile()

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
    print("[ Phase A ] Competitive research + user feedback running in parallel...")
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

    # Phase B — sequential
    print("[ Phase B ] Drafting product spec...")
    spec = run_spec(document, chosen, research, feedback, profile)
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
