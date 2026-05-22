import os
import time
import random
import yaml
import anthropic
from pathlib import Path
from anthropic import Anthropic

client = Anthropic()

# Anthropic's hosted web search — executed server-side, no extra API key needed
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

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

_BRIEF_MODE_SUFFIX = """

BRIEF MODE: This is a test run. Respond in 200 words or fewer. Do not perform any
web searches — use your training knowledge only. Produce a minimal placeholder output
so the pipeline can be validated end-to-end.
"""


def _load_config() -> dict:
    path = Path(__file__).parent / "config.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


CONFIG = _load_config()


def load_profile(key: str) -> dict:
    return CONFIG.get("profiles", {}).get(key, {})


def _step_cfg(step: str, profile: dict) -> dict:
    return profile.get("steps", {}).get(step, {})


def step_model(step: str, profile: dict) -> str:
    return _step_cfg(step, profile).get("model", "claude-haiku-4-5-20251001")


def step_max_tokens(step: str, profile: dict) -> int:
    return _step_cfg(step, profile).get("max_tokens", 1500)


def step_max_searches(step: str, profile: dict) -> int:
    return _step_cfg(step, profile).get("max_searches", 5)


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def api_call_with_retry(fn, max_retries: int = 5):
    """Retry an API call on rate limit errors.

    Waits just past the 60-second rate limit window on each attempt.
    Jitter prevents simultaneous retries across continuation rounds.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except anthropic.RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait = 65 + random.randint(0, 20)
            print(f"\n  Rate limit hit — waiting {wait}s before retry ({attempt + 1}/{max_retries - 1})...")
            time.sleep(wait)


def run_skill(
    skill_path: str,
    user_message: str,
    extra_context: str = "",
    profile: dict | None = None,
    step: str = "",
) -> tuple[str, dict]:
    """Run a skill using its SKILL.md as system prompt with an agentic tool-use loop.

    Returns (output_text, usage) where usage = {"input_tokens": int, "output_tokens": int}
    summed across all continuation rounds.
    Web searches are capped at step_max_searches to control token accumulation.
    """
    if profile is None:
        profile = {}

    brief = profile.get("brief_mode", False)
    if brief:
        # Skip the full SKILL.md (3000–6000 tokens) — use a micro prompt instead.
        # Goal is pipeline validation, not quality output.
        system_prompt = (
            "Test mode. Output minimal placeholder markdown under 80 words. "
            "No preamble, no explanation."
        )
    else:
        raw = open(f"{skill_path}/SKILL.md").read()
        system_prompt = _strip_frontmatter(raw) + _API_MODE_SUFFIX

    model = step_model(step, profile)
    max_tokens = step_max_tokens(step, profile)
    max_searches = step_max_searches(step, profile)

    content = user_message if not extra_context else f"{user_message}\n\n{extra_context}"
    messages = [{"role": "user", "content": content}]
    accumulated: list[str] = []
    search_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_write_tokens = 0
    total_cache_read_tokens = 0

    continuing = False
    for _ in range(50):
        use_search = not brief and not continuing and max_searches > 0 and search_count < max_searches
        kwargs = dict(model=model, max_tokens=max_tokens, system=system_prompt, messages=messages)
        if use_search:
            kwargs["tools"] = [SEARCH_TOOL]

        response = api_call_with_retry(lambda: client.messages.create(**kwargs))

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_write_tokens += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0) or 0

        for block in response.content:
            if getattr(block, "type", None) in ("tool_use", "server_tool_use"):
                search_count += 1

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        if text:
            accumulated.append(text)

        if response.stop_reason == "end_turn":
            break
        elif response.stop_reason == "max_tokens":
            # Output was cut off — continue generation from where it stopped.
            # Strip server_tool_use + web_search_tool_result blocks before storing:
            # each search result carries ~27k chars of encrypted_content that would
            # push the continuation request over the 30k token/min rate limit.
            # The model's partial text already incorporates the search findings.
            continuing = True
            text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
            messages.append({"role": "assistant", "content": text_blocks or response.content})
            messages.append({"role": "user", "content": "Continue exactly where you left off. No preamble."})
        elif response.stop_reason == "tool_use":
            continuing = False
            messages.append({"role": "assistant", "content": response.content})
        else:
            break

    usage = {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_write_tokens": total_cache_write_tokens,
        "cache_read_tokens": total_cache_read_tokens,
        "search_count": search_count,
    }
    return "\n".join(accumulated), usage
