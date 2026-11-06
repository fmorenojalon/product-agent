import os
import time
import random
import yaml
import anthropic
from pathlib import Path
from anthropic import Anthropic

# Retries are owned by api_call_with_retry below. The SDK's own retries are off so every
# wait is visible and bounded, and behaves the same whichever SDK version is installed.
client = Anthropic(max_retries=0)

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


# Statuses a retry cannot fix: bad request, auth, billing, permissions, not found, too large.
_PERMANENT_STATUSES = {400, 401, 402, 403, 404, 413, 422}
_RETRYABLE_STATUSES = {408, 409, 429}
# A tier spend cap is a 429 with no retry-after, and retrying fails until the month rolls over.
_SPEND_CAP_CODE = "enforced_spend_limit_reached"
_BACKOFF_BASE_S = 2.0
_BACKOFF_CAP_S = 60.0
_VISIBLE_WAIT_S = 5


# An error event inside a stream arrives after the HTTP status (200) was sent, so the status
# cannot tell a transient failure from a permanent one; the error type can. Each type maps to
# the reason shown to the user and to the CallStats counter the retry is counted in.
_STREAM_ERRORS = {
    "overloaded_error": ("API overloaded", "server_errors"),
    "api_error": ("API error", "server_errors"),
    "rate_limit_error": ("Rate limited", "rate_limited"),
}


def _retry_reason(e: Exception) -> tuple[str, str] | None:
    """(reason shown, CallStats counter) when the error is worth retrying, else None."""
    if isinstance(e, anthropic.APIConnectionError):
        return "Connection error", "other_retries"
    if not isinstance(e, anthropic.APIStatusError):
        return None
    if getattr(e, "error_code", None) == _SPEND_CAP_CODE:
        return None
    if e.status_code < 300:
        reason, counter = _STREAM_ERRORS.get(getattr(e, "type", None), (None, None))
        return (f"{reason} (mid-stream)", counter) if reason else None
    if e.status_code in _PERMANENT_STATUSES:
        return None
    if e.status_code == 429:
        return "Rate limited (429)", "rate_limited"
    if e.status_code == 529:
        return "API overloaded (529)", "server_errors"
    if e.status_code >= 500:
        return f"API error ({e.status_code})", "server_errors"
    if e.status_code in _RETRYABLE_STATUSES:
        return f"API error ({e.status_code})", "other_retries"
    return None


def _retry_after_s(e: Exception) -> float | None:
    """Seconds the API asked us to wait, from its retry-after header, if it sent one."""
    headers = getattr(getattr(e, "response", None), "headers", None)
    if not headers:
        return None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        try:
            seconds = float(headers.get(name)) * scale
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return None


def _backoff_s(retry: int) -> float:
    """Exponential backoff for the nth retry (1-based), capped, with jitter."""
    delay = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (retry - 1))
    return delay / 2 + random.uniform(0, delay / 2)


def _header_int(headers, name: str) -> int | None:
    value = headers.get(name)
    if isinstance(value, (str, int)):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _lowest(current: int | None, new: int) -> int:
    return new if current is None else min(current, new)


class CallStats:
    """What one call waited for, and the allowance the API reported while it ran.

    api_call_with_retry fills in the waits and retries, _request the rate-limit headers, and
    complete() returns them in its usage. The remaining allowances are the headers' values:
    the API sends them when a response starts and rounds them to the nearest thousand.
    """

    def __init__(self) -> None:
        self.wait_s = 0.0
        self.rate_limited = 0
        self.server_errors = 0
        self.other_retries = 0
        self.min_input_tokens_remaining: int | None = None
        self.input_tokens_limit: int | None = None
        self.min_output_tokens_remaining: int | None = None
        self.output_tokens_limit: int | None = None

    def note_retry(self, counter: str, wait: float) -> None:
        setattr(self, counter, getattr(self, counter) + 1)
        self.wait_s += wait

    def note_headers(self, headers) -> None:
        """Record the rate-limit headers of a response, or of a failed attempt."""
        if not headers:
            return
        input_left = _header_int(headers, "anthropic-ratelimit-input-tokens-remaining")
        input_limit = _header_int(headers, "anthropic-ratelimit-input-tokens-limit")
        output_left = _header_int(headers, "anthropic-ratelimit-output-tokens-remaining")
        output_limit = _header_int(headers, "anthropic-ratelimit-output-tokens-limit")
        if input_left is not None:
            self.min_input_tokens_remaining = _lowest(self.min_input_tokens_remaining, input_left)
        if input_limit is not None:
            self.input_tokens_limit = input_limit
        if output_left is not None:
            self.min_output_tokens_remaining = _lowest(self.min_output_tokens_remaining, output_left)
        if output_limit is not None:
            self.output_tokens_limit = output_limit

    def as_usage(self) -> dict:
        return {
            "wait_s": self.wait_s,
            "rate_limited": self.rate_limited,
            "server_errors": self.server_errors,
            "other_retries": self.other_retries,
            "min_input_tokens_remaining": self.min_input_tokens_remaining,
            "input_tokens_limit": self.input_tokens_limit,
            "min_output_tokens_remaining": self.min_output_tokens_remaining,
            "output_tokens_limit": self.output_tokens_limit,
        }


def api_call_with_retry(fn, max_retries: int = 8, max_total_wait: float = 15 * 60, stats: CallStats | None = None):
    """Call fn(), retrying transient API errors. The only retry layer in the pipeline.

    Waits as long as the API's retry-after says, or backs off exponentially when it
    sends none. Errors a retry cannot fix (_retry_reason) are raised on the first
    attempt. So is any error whose wait would not fit in max_total_wait, so a call
    never sleeps silently or for longer than that budget. When given stats, it counts
    each retry and its wait there, and records the rate-limit headers of failed attempts.
    """
    waited = 0.0
    retry = 0
    while True:
        try:
            return fn()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            if stats is not None:
                stats.note_headers(getattr(getattr(e, "response", None), "headers", None))
            found = _retry_reason(e)
            if found is None:
                raise
            reason, counter = found
            retry += 1
            if retry > max_retries:
                print(f"\n  {reason} — giving up after {max_retries} retries.")
                raise
            asked = _retry_after_s(e)
            wait = asked + random.uniform(0, 1) if asked is not None else _backoff_s(retry)
            if waited + wait > max_total_wait:
                print(
                    f"\n  {reason} — not retrying: a {wait:.0f}s wait does not fit in the "
                    f"remaining {max_total_wait - waited:.0f}s budget."
                )
                raise
            if wait > _VISIBLE_WAIT_S:
                print(
                    f"\n  {reason} — waiting {wait:.0f}s before retry {retry}/{max_retries} "
                    f"({waited + wait:.0f}s of {max_total_wait:.0f}s budget)..."
                )
            time.sleep(wait)
            waited += wait
            if stats is not None:
                stats.note_retry(counter, wait)


class StopReasonError(RuntimeError):
    """The model stopped in a way that would leave the output incomplete or empty."""

    def __init__(self, step: str, stop_reason: str | None, detail: str = "") -> None:
        self.step = step
        self.stop_reason = stop_reason
        suffix = f": {detail}" if detail else ""
        super().__init__(f"Step '{step}' ended with stop_reason={stop_reason!r}{suffix}")


_MAX_ROUNDS = 50
_CONTINUE_PROMPT = "Continue exactly where you left off. No preamble."


def _refusal_detail(response) -> str:
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    explanation = getattr(details, "explanation", None)
    parts = [p for p in (f"category: {category}" if category else "", explanation) if p]
    return "the model declined to answer" + (f" ({'; '.join(parts)})" if parts else "")


def _request(kwargs: dict, stats: CallStats | None = None):
    """One streamed request, returned as the complete Message. Its rate-limit headers go to stats.

    Streaming lifts the SDK's size guard on non-streaming requests (which the larger
    max_tokens ceilings would hit) and avoids idle-connection timeouts on long search
    turns. An error that arrives mid-stream is raised from here, and the retry in the
    caller then restarts the whole request: the partial output is discarded.
    """
    with client.messages.stream(**kwargs) as stream:
        if stats is not None:
            stats.note_headers(getattr(getattr(stream, "response", None), "headers", None))
        return stream.get_final_message()


def _searches_run(response) -> int:
    """Searches the API ran in this response, as it reports them in usage.

    Counting search blocks is only the fallback for a response without that field: it
    also counts a search that failed, which the API does not bill.
    """
    reported = getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", None)
    if isinstance(reported, int):
        return reported
    return sum(1 for b in response.content if getattr(b, "type", None) in ("tool_use", "server_tool_use"))


def complete(
    messages: list,
    *,
    model: str,
    max_tokens: int,
    system: str | None = None,
    tools: list | None = None,
    cache: bool = False,
    step: str = "",
) -> tuple[str, dict]:
    """Run one request to a complete answer. Returns (text, usage), usage summed across rounds.
    The usage also carries the call's waits, retries and rate-limit headroom (see CallStats).

    Every stop reason is handled, so a partial answer is never returned silently:
      end_turn    done
      max_tokens  continue from where the model stopped
      pause_turn  the server-side search loop paused; send the turn back to resume it
      anything else (refusal, tool_use, stop_sequence, context window, ...) raises StopReasonError
    A blank answer, or no final answer after _MAX_ROUNDS rounds, also raises.

    tools are offered on the first round and on every resumed round, but not on a
    continuation after max_tokens (the search results are dropped from what is sent back).
    cache=True adds automatic prompt caching to the rounds that offer tools. It is not
    added to a continuation: dropping the tools changes the cached prefix, so it could
    not be read and would only cost the cache-write premium.
    """
    accumulated: list[str] = []
    search_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_write_tokens = 0
    total_cache_read_tokens = 0
    stats = CallStats()
    use_tools = bool(tools)

    for _ in range(_MAX_ROUNDS):
        kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        if use_tools:
            kwargs["tools"] = tools
            if cache:
                kwargs["cache_control"] = {"type": "ephemeral"}

        response = api_call_with_retry(lambda: _request(kwargs, stats), stats=stats)

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_write_tokens += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        search_count += _searches_run(response)

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        if text:
            accumulated.append(text)

        stop = response.stop_reason
        if stop == "end_turn":
            break
        elif stop == "max_tokens":
            # Output was cut off — continue generation from where it stopped.
            # Strip server_tool_use + web_search_tool_result blocks before storing:
            # each search result carries ~27k chars of encrypted_content that would
            # push the continuation request over the 30k token/min rate limit.
            # The model's partial text already incorporates the search findings.
            use_tools = False
            text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
            messages.append({"role": "assistant", "content": text_blocks or response.content})
            messages.append({"role": "user", "content": _CONTINUE_PROMPT})
        elif stop == "pause_turn":
            # The API paused a long search turn. Sending it back unchanged resumes it.
            # Nothing is stripped: the paused search has to stay intact.
            messages.append({"role": "assistant", "content": response.content})
        elif stop == "refusal":
            raise StopReasonError(step, stop, _refusal_detail(response))
        else:
            raise StopReasonError(step, stop)
    else:
        raise StopReasonError(step, None, f"no final answer after {_MAX_ROUNDS} rounds")

    text = "\n".join(accumulated)
    if not text.strip():
        raise StopReasonError(step, "end_turn", "the model returned no text")
    usage = {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_write_tokens": total_cache_write_tokens,
        "cache_read_tokens": total_cache_read_tokens,
        "search_count": search_count,
        **stats.as_usage(),
    }
    return text, usage


def run_skill(
    skill_path: str,
    user_message: str,
    extra_context: str = "",
    profile: dict | None = None,
    step: str = "",
) -> tuple[str, dict]:
    """Run a skill using its SKILL.md as system prompt, with Anthropic's hosted web search.

    Returns (output_text, usage) summed across all rounds (see complete()).

    Search is limited to step_max_searches searches per step, sent to the API as max_uses
    (0 turns search off). Prompt caching is on for steps that search, where the rounds of
    one turn re-send a large prefix; other steps are single-round, and caching them would
    only add the cache-write premium.
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

    content = user_message if not extra_context else f"{user_message}\n\n{extra_context}"
    max_searches = step_max_searches(step, profile)
    search = not brief and max_searches > 0
    return complete(
        [{"role": "user", "content": content}],
        model=step_model(step, profile),
        max_tokens=step_max_tokens(step, profile),
        system=system_prompt,
        tools=[{**SEARCH_TOOL, "max_uses": max_searches}] if search else None,
        cache=search,
        step=step,
    )
