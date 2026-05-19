import os
import json
import httpx
from anthropic import Anthropic

client = Anthropic()
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for current information about products, companies, "
        "user feedback, market data, and competitors."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query to execute"}
        },
        "required": ["query"],
    },
}

# Appended to every skill system prompt when running via API
_API_MODE_SUFFIX = """

---
PIPELINE MODE: You are running via the Claude API inside an automated orchestrator.
- Output everything as well-structured markdown. Do NOT generate PDF or DOCX files.
- Skip interactive interview or clarification steps. Treat all provided context as
  complete input and generate the full output directly.
"""


def brave_search(query: str) -> str:
    api_key = os.environ["BRAVE_API_KEY"]
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": 10},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        return json.dumps(
            [
                {
                    "title": r["title"],
                    "url": r["url"],
                    "description": r.get("description", ""),
                }
                for r in results[:10]
            ],
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from SKILL.md files."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def run_skill(skill_path: str, user_message: str, extra_context: str = "") -> str:
    """Run a skill using its SKILL.md as system prompt with an agentic tool-use loop."""
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
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "web_search":
                    result = brave_search(block.input["query"])
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            else:
                break
        else:
            break

    return ""
