#!/usr/bin/env python3
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
load_dotenv()

from agent import client, MODEL, run_skill
from connectors.discord import fetch_feedback
from connectors.notion import push_stories


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Parse JSON from a Claude response, stripping markdown code fences if present."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    return json.loads(text)


def _divider(label: str = "") -> None:
    line = "─" * 70
    print(f"\n{line}")
    if label:
        print(label)
        print(line)


# ── Pipeline steps ────────────────────────────────────────────────────────────

def extract_competitors_and_persona(idea: str) -> tuple[list[str], str]:
    """Pre-step: identify key competitors and target persona from the raw idea."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": (
                f'Product idea: "{idea}"\n\n'
                "Return a JSON object with exactly these keys:\n"
                '- "competitors": array of 3 existing product or company names '
                "most relevant to research for this idea\n"
                '- "persona": string describing the primary target user '
                '(e.g. "project manager", "indie developer")\n\n'
                "Return only valid JSON, no explanation."
            ),
        }],
    )
    data = _parse_json(response.content[0].text)
    return data["competitors"], data["persona"]


def run_research(
    idea: str, competitors: list[str], persona: str
) -> tuple[str, str]:
    """UC-1 and UC-2 run concurrently."""
    uc1_msg = (
        f'Analyze the competitive landscape for this product idea: "{idea}"\n\n'
        f"Focus your analysis on these competitors: {', '.join(competitors)}"
    )
    uc2_msg = (
        f'Research user feedback relevant to this product idea: "{idea}"\n\n'
        f"Target persona: {persona}\n"
        f"Key products to find feedback on: {', '.join(competitors)}"
    )

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(run_skill, "product-analysis", uc1_msg): "research",
            executor.submit(run_skill, "product-user-feedback", uc2_msg): "feedback",
        }
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
            label = "Competitive research" if key == "research" else "User feedback synthesis"
            print(f"  ✓ {label} complete")

    return results["research"], results["feedback"]


def generate_proposals(idea: str, research: str, feedback: str) -> str:
    """Synthesize UC-1 + UC-2 outputs into 2-3 product direction proposals."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": (
                f'Original idea: "{idea}"\n\n'
                f"## Competitive Research\n{research}\n\n"
                f"## User Feedback\n{feedback}\n\n"
                "Based on the research above, generate 2-3 distinct product direction proposals.\n"
                "For each proposal include:\n"
                "- A short name (e.g. 'Option 1 — Contextual AI Suggestions')\n"
                "- 2-3 sentences describing the direction\n"
                "- 1-2 sentences grounding it in the research\n\n"
                "Format them clearly and number them so the user can pick one."
            ),
        }],
    )
    return response.content[0].text


def run_spec(
    idea: str, chosen_direction: str, research: str, feedback: str
) -> str:
    """UC-3: product-specification in context-injection mode."""
    extra = (
        "PIPELINE CONTEXT — skip the interactive interview and generate the PRD "
        "directly using the information below as pre-filled answers.\n\n"
        f"## Original idea\n{idea}\n\n"
        f"## Confirmed product direction\n{chosen_direction}\n\n"
        f"## Competitive research\n{research}\n\n"
        f"## User feedback synthesis\n{feedback}"
    )
    return run_skill(
        "product-specification",
        f'Generate a PRD for: "{idea}"',
        extra_context=extra,
    )


def run_stories(spec: str) -> str:
    """UC-4: user story generation from the product spec."""
    return run_skill(
        "product-user-story",
        f"Generate epics and user stories for the following product specification:\n\n{spec}",
    )


def save_outputs(
    idea: str, research: str, feedback: str, spec: str, stories: str
) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", idea[:50].lower()).strip("-")
    folder = Path("output") / f"{datetime.now().strftime('%Y-%m-%d')}_{slug}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research-brief.md").write_text(research)
    (folder / "feedback-synthesis.md").write_text(feedback)
    (folder / "product-spec.md").write_text(spec)
    (folder / "user-stories.md").write_text(stories)
    return folder


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python orchestrator.py "your product idea"')
        sys.exit(1)

    idea = sys.argv[1]
    print(f'\nProduct Agent  ·  "{idea}"\n')

    # Pre-step
    print("[ Pre-step ] Identifying competitors and persona...")
    competitors, persona = extract_competitors_and_persona(idea)
    print(f"  Competitors : {', '.join(competitors)}")
    print(f"  Persona     : {persona}\n")

    # Phase A — parallel research
    print("[ Phase A ] Competitive research + user feedback running in parallel...")
    research, feedback = run_research(idea, competitors, persona)
    print()

    # Synthesis
    print("[ Synthesis ] Generating product direction proposals...")
    proposals = generate_proposals(idea, research, feedback)
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
    spec = run_spec(idea, chosen, research, feedback)
    print("  ✓ Spec complete\n")

    print("[ Phase B ] Generating user stories...")
    stories = run_stories(spec)
    print("  ✓ User stories complete\n")

    # Notion (mock in Phase 1)
    push_stories(stories)

    # Save all outputs
    output_folder = save_outputs(idea, research, feedback, spec, stories)

    _divider("  Run complete")
    print(f"  Output folder : {output_folder}/")
    print(  "  Files         : research-brief.md · feedback-synthesis.md")
    print(  "                  product-spec.md · user-stories.md")
    _divider()
    print()


if __name__ == "__main__":
    main()
