import os
from anthropic import Anthropic

client = Anthropic()
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

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


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from SKILL.md files."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def run_skill(skill_path: str, user_message: str, extra_context: str = "") -> str:
    """Run a skill using its SKILL.md as system prompt with an agentic tool-use loop.

    Anthropic's web_search tool is executed server-side: results are embedded in the
    response content, so we just append each turn and loop until end_turn.
    """
    raw = open(f"{skill_path}/SKILL.md").read()
    system_prompt = _strip_frontmatter(raw) + _API_MODE_SUFFIX

    content = user_message if not extra_context else f"{user_message}\n\n{extra_context}"
    messages = [{"role": "user", "content": content}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8096,
            system=system_prompt,
            tools=[SEARCH_TOOL],
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )

        if response.stop_reason == "tool_use":
            # Search results are already in response.content (server-side execution).
            # Append the full turn and let Claude continue.
            messages.append({"role": "assistant", "content": response.content})
        else:
            break

    return ""
