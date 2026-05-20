#!/usr/bin/env python3
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
load_dotenv()

from agent import client, step_model, step_max_tokens, api_call_with_retry, run_skill
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


def _truncate(text: str, max_chars: int) -> str:
    """Cap long outputs before passing as context to prevent rate limit errors."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[output truncated]"


def _llm(messages: list, step: str = "", dry_run: bool = False) -> str:
    """Direct Claude API call with retry, using per-step model config."""
    response = api_call_with_retry(
        lambda: client.messages.create(
            model=step_model(step, dry_run),
            max_tokens=step_max_tokens(step, dry_run),
            messages=messages,
        )
    )
    return response.content[0].text


# ── Pipeline steps ────────────────────────────────────────────────────────────

def extract_competitors_and_persona(document: str, dry_run: bool = False) -> tuple[list[str], str]:
    """Pre-step: identify key competitors and target persona from the input document."""
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
    }], step="pre_step", dry_run=dry_run))
    return data["competitors"], data["persona"]


def run_research(
    document: str, competitors: list[str], persona: str, dry_run: bool = False
) -> tuple[str, str]:
    """UC-1 and UC-2 run concurrently."""
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
            executor.submit(run_skill, "product-analysis", uc1_msg, "", dry_run, "research"): "research",
            executor.submit(run_skill, "product-user-feedback", uc2_msg, "", dry_run, "feedback"): "feedback",
        }
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
            label = "Competitive research" if key == "research" else "User feedback synthesis"
            print(f"  ✓ {label} complete")

    return results["research"], results["feedback"]


def generate_proposals(document: str, research: str, feedback: str, dry_run: bool = False) -> str:
    """Synthesize UC-1 + UC-2 outputs into 2-3 product direction proposals."""
    # Truncate to control downstream token cost (search results accumulate fast)
    max_chars = 2000 if dry_run else 3000
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
    }], step="synthesis", dry_run=dry_run)


def run_spec(
    document: str, chosen_direction: str, research: str, feedback: str, dry_run: bool = False
) -> str:
    """UC-3: product-specification in context-injection mode."""
    max_chars = 2000 if dry_run else 3000
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
        dry_run=dry_run,
        step="spec",
    )


def run_stories(spec: str, dry_run: bool = False) -> str:
    """UC-4: user story generation from the product spec."""
    return run_skill(
        "product-user-story",
        f"Generate epics and user stories for the following product specification:\n\n{spec}",
        dry_run=dry_run,
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
    dry_run = "--dry-run" in sys.argv

    input_path = Path(args[0]) if args else Path("idea.md")

    if not input_path.exists():
        print(f"Error: '{input_path}' not found.")
        print("Create an idea.md file with your product idea, or pass a file path:")
        print("  python orchestrator.py my-idea.md")
        sys.exit(1)

    document = input_path.read_text()
    title = input_path.stem

    if dry_run:
        print(f"\nProduct Agent  ·  {input_path.name}  [DRY RUN — Haiku, no search, minimal output]\n")
    else:
        print(f"\nProduct Agent  ·  {input_path.name}\n")

    # Pre-step
    print("[ Pre-step ] Identifying competitors and persona...")
    competitors, persona = extract_competitors_and_persona(document, dry_run)
    print(f"  Competitors : {', '.join(competitors)}")
    print(f"  Persona     : {persona}\n")

    # Phase A — parallel research
    print("[ Phase A ] Competitive research + user feedback running in parallel...")
    research, feedback = run_research(document, competitors, persona, dry_run)
    print()

    # Synthesis
    print("[ Synthesis ] Generating product direction proposals...")
    proposals = generate_proposals(document, research, feedback, dry_run)
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
    spec = run_spec(document, chosen, research, feedback, dry_run)
    print("  ✓ Spec complete\n")

    print("[ Phase B ] Generating user stories...")
    stories = run_stories(spec, dry_run)
    print("  ✓ User stories complete\n")

    # Notion (mock in Phase 1)
    push_stories(stories)

    # Save all outputs
    output_folder = save_outputs(title, research, feedback, spec, stories)

    _divider("  Run complete")
    print(f"  Output folder : {output_folder}/")
    print(  "  Files         : research-brief.md · feedback-synthesis.md")
    print(  "                  product-spec.md · user-stories.md")
    _divider()
    print()


if __name__ == "__main__":
    main()
