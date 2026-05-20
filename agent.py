import os
import time
import yaml
import anthropic
from pathlib import Path
from anthropic import Anthropic

client = Anthropic()
DRY_RUN_MODEL = "claude-haiku-4-5-20251001"
DRY_RUN_MAX_TOKENS = 512
DRY_RUN_MAX_SEARCHES = 2

# Anthropic's hosted web search — executed server-side, no extra API key needed
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

# Appended to every skill system prompt when running via API
_API_MODE_SUFFIX = """

---
PIPELINE MODE — CRITICAL RULES (override all other instructions):
1. Output ONLY the requested deliverable as well-structured markdown. No PDF, no DOCX.
2. NEVER ask the user questions. NEVER request clarification. NEVER prompt for input.
   Questions written to output will never be read or answered — do not write them.
3. Skip every interactive, interview, or clarification step in your instructions.
4. If information is missing, make a reasonable assumption and state it inline.
5. Treat all context provided as complete input and generate the full output directly.
"""

_DRY_RUN_SUFFIX = """

DRY RUN MODE: This is a test run. Respond in 200 words or fewer. Do not perform
any web searches — use your training knowledge only. Skip all research steps and
produce a minimal placeholder output so the pipeline can be validated end-to-end.
"""


def _load_config() -> dict:
    path = Path(__file__).parent / "config.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


CONFIG = _load_config()


def step_model(step: str, dry_run: bool = False) -> str:
    if dry_run:
        return DRY_RUN_MODEL
    cfg = CONFIG.get("steps", {}).get(step, {})
    return cfg.get("model", "claude-sonnet-4-6")


def step_max_tokens(step: str, dry_run: bool = False) -> int:
    if dry_run:
        return DRY_RUN_MAX_TOKENS
    cfg = CONFIG.get("steps", {}).get(step, {})
    return cfg.get("max_tokens", 1500)


def step_max_searches(step: str, dry_run: bool = False) -> int:
    if dry_run:
        return DRY_RUN_MAX_SEARCHES
    cfg = CONFIG.get("steps", {}).get(step, {})
    return cfg.get("max_searches", 5)


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from SKILL.md files."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def api_call_with_retry(fn, max_retries: int = 3):
    """Retry an API call on rate limit errors with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except anthropic.RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait = 60 * (2 ** attempt)  # 60s, 120s, 240s
            print(f"\n  Rate limit hit — waiting {wait}s before retry ({attempt + 1}/{max_retries})...")
            time.sleep(wait)


def run_skill(
    skill_path: str,
    user_message: str,
    extra_context: str = "",
    dry_run: bool = False,
    step: str = "",
) -> str:
    """Run a skill using its SKILL.md as system prompt with an agentic tool-use loop.

    Web searches are capped at step_max_searches to control token accumulation:
    each search adds ~1k tokens to the message history re-sent on every iteration.
    """
    raw = open(f"{skill_path}/SKILL.md").read()
    suffix = _API_MODE_SUFFIX + (_DRY_RUN_SUFFIX if dry_run else "")
    system_prompt = _strip_frontmatter(raw) + suffix

    model = step_model(step, dry_run)
    max_tokens = step_max_tokens(step, dry_run)
    max_searches = step_max_searches(step, dry_run)

    content = user_message if not extra_context else f"{user_message}\n\n{extra_context}"
    messages = [{"role": "user", "content": content}]
    accumulated: list[str] = []
    search_count = 0

    for _ in range(50):  # hard cap on iterations
        # Stop offering the search tool once the limit is reached
        use_search = not dry_run and search_count < max_searches
        kwargs = dict(model=model, max_tokens=max_tokens, system=system_prompt, messages=messages)
        if use_search:
            kwargs["tools"] = [SEARCH_TOOL]

        response = api_call_with_retry(lambda: client.messages.create(**kwargs))

        # Count searches used in this response
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                search_count += 1

        # Collect any text produced in this iteration
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        if text:
            accumulated.append(text)

        if response.stop_reason in ("end_turn", "max_tokens"):
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
        else:
            break

    return "\n".join(accumulated)
