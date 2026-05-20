import os
import time
import anthropic
from anthropic import Anthropic

client = Anthropic()
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
DRY_RUN_MODEL = "claude-haiku-4-5-20251001"
DRY_RUN_MAX_TOKENS = 512

# Anthropic's hosted web search — executed server-side, no extra API key needed
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

# Appended to every skill system prompt when running via API
_API_MODE_SUFFIX = """

---
PIPELINE MODE: You are running via the Claude API inside an automated orchestrator.
- Output everything as well-structured markdown. Do NOT generate PDF or DOCX files.
- Skip interactive interview or clarification steps. Treat all provided context as
  complete input and generate the full output directly.
"""

_DRY_RUN_SUFFIX = """

DRY RUN MODE: This is a test run. Respond in 200 words or fewer. Do not perform
any web searches — use your training knowledge only. Skip all research steps and
produce a minimal placeholder output so the pipeline can be validated end-to-end.
"""


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


def run_skill(skill_path: str, user_message: str, extra_context: str = "", dry_run: bool = False) -> str:
    """Run a skill using its SKILL.md as system prompt with an agentic tool-use loop."""
    raw = open(f"{skill_path}/SKILL.md").read()
    suffix = _API_MODE_SUFFIX + (_DRY_RUN_SUFFIX if dry_run else "")
    system_prompt = _strip_frontmatter(raw) + suffix

    model = DRY_RUN_MODEL if dry_run else MODEL
    max_tokens = DRY_RUN_MAX_TOKENS if dry_run else 8096

    content = user_message if not extra_context else f"{user_message}\n\n{extra_context}"
    messages = [{"role": "user", "content": content}]

    while True:
        kwargs = dict(model=model, max_tokens=max_tokens, system=system_prompt, messages=messages)
        if not dry_run:
            # Web search only in full runs — it's expensive and slow
            kwargs["tools"] = [SEARCH_TOOL]

        response = api_call_with_retry(lambda: client.messages.create(**kwargs))

        if response.stop_reason == "end_turn":
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )

        if response.stop_reason == "tool_use":
            # Anthropic's web_search is server-side; append turn and continue loop
            messages.append({"role": "assistant", "content": response.content})
        else:
            break

    return ""
