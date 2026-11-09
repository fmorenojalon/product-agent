"""Pipeline observability — per-step cost, latency, and output quality tracking."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic
from agent import LIGHT_MODEL, api_call_with_retry

# ── Pricing ───────────────────────────────────────────────────────────────────
# Verify against https://platform.claude.com/docs/en/about-claude/pricing before each release.
# cache_write: tokens newly written to the 5-minute prompt cache (1.25 times the input price)
# cache_read:  tokens read from the prompt cache (0.1 times the input price, but 0.05 times on
#              Claude Opus 5.5 and Claude Sonnet 5.5)
# All per-million-token rates except _SEARCH_RATE which is per-1k-queries.
# Claude Haiku 5.5 is priced here for prompts up to 100,000 tokens; a longer prompt is billed
# higher by the API and is under-reported. Models that config.yaml does not name keep their
# rates, so old runs and edited configs still price correctly.
RATES_UPDATED = "2026-11-09"
_RATES: dict[str, dict[str, float]] = {
    "claude-haiku-5-5":          {"input": 0.10,  "output": 0.50,  "cache_write": 0.125, "cache_read": 0.01},
    "claude-sonnet-5-5":         {"input": 2.00,  "output": 10.00, "cache_write": 2.50,  "cache_read": 0.10},
    "claude-opus-5-5":           {"input": 4.00,  "output": 20.00, "cache_write": 5.00,  "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"input": 1.00,  "output": 5.00,  "cache_write": 1.25,  "cache_read": 0.10},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-opus-4-7":           {"input": 5.00,  "output": 25.00, "cache_write": 6.25,  "cache_read": 0.50},
}
_SEARCH_RATE = 10.00  # USD per 1,000 web searches
_SHORT: dict[str, str] = {
    "claude-haiku-5-5":          "haiku",
    "claude-sonnet-5-5":         "sonnet",
    "claude-opus-5-5":           "opus",
    "claude-haiku-4-5-20251001": "haiku",
    "claude-sonnet-4-6":         "sonnet",
    "claude-opus-4-7":           "opus",
}

# A line that starts a proposal: after any markdown decoration (heading marks, bold, bullets, quote
# marks), a number ("1." / "1)" / "1:") or the word Option or Proposal with a number. A mention in the
# middle of a sentence does not count.
_PROPOSAL_LINE = re.compile(r"^[\s>#*_+-]*(?:\d+[.):]\s+\S|(?:option|proposal)\s+\d+)", re.IGNORECASE)

# Heuristic rules keyed by step name
_HEURISTICS: dict[str, dict] = {
    "research":  {"min_chars": 200, "require_headers": True},
    "feedback":  {"min_chars": 200, "require_headers": True},
    "synthesis": {"min_proposals": 2},
    "spec":      {"min_chars": 500, "require_headers": True},
    "stories":   {"require_story_headers": True},
}

# Profile keys that get the extra Haiku quality-score call
_LLM_SCORE_PROFILES = {"3", "4"}


# ── Data classes ──────────────────────────────────────────────────────────────

_SCORER_ERROR = "scorer error: "


@dataclass
class QualityResult:
    heuristic_ok: bool
    llm_score: int | None = None
    warning: str | None = None
    user_continued: bool | None = None

    @property
    def scorer_failed(self) -> bool:
        """The model score could not be had. The step is not blocked, but it was not scored."""
        return bool(self.warning) and self.warning.startswith(_SCORER_ERROR)

    @property
    def passed(self) -> bool:
        if not self.heuristic_ok:
            return False
        if self.llm_score is not None and self.llm_score <= 2:
            return False
        return True


@dataclass
class StepMetrics:
    step: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    quality: QualityResult
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    search_count: int = 0
    wait_s: float = 0.0
    rate_limited: int = 0
    server_errors: int = 0
    other_retries: int = 0
    min_input_tokens_remaining: int | None = None
    input_tokens_limit: int | None = None
    min_output_tokens_remaining: int | None = None
    output_tokens_limit: int | None = None

    @property
    def active_s(self) -> float:
        """Latency without the time spent waiting to retry."""
        return max(self.latency_s - self.wait_s, 0.0)


# The wait, retry and rate-limit fields that agent.complete() returns in its usage.
_TELEMETRY_FIELDS = (
    "wait_s", "rate_limited", "server_errors", "other_retries",
    "min_input_tokens_remaining", "input_tokens_limit",
    "min_output_tokens_remaining", "output_tokens_limit",
)


def telemetry_from_usage(usage: dict) -> dict:
    """Those fields of a call's usage, as StepMetrics keyword arguments (absent ones keep their defaults)."""
    return {name: usage[name] for name in _TELEMETRY_FIELDS if name in usage}


# ── Cost estimation ───────────────────────────────────────────────────────────

def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    search_count: int = 0,
) -> float:
    """Return estimated USD cost including cache and search charges. Raises ValueError for unknown models."""
    if model not in _RATES:
        raise ValueError(f"Unknown model: {model!r}. Add it to _RATES in observability.py.")
    r = _RATES[model]
    return (
        (input_tokens       / 1_000_000) * r["input"]
        + (output_tokens    / 1_000_000) * r["output"]
        + (cache_write_tokens / 1_000_000) * r["cache_write"]
        + (cache_read_tokens  / 1_000_000) * r["cache_read"]
        + (search_count       / 1_000)     * _SEARCH_RATE
    )


# ── Heuristic quality check ───────────────────────────────────────────────────

def heuristic_check(step: str, output: str) -> tuple[bool, str]:
    """Return (passed, reason). reason is '' when passed."""
    cfg = _HEURISTICS.get(step, {})

    if "min_chars" in cfg and len(output) < cfg["min_chars"]:
        return False, f"output too short ({len(output)} chars, need ≥ {cfg['min_chars']})"

    if cfg.get("require_headers") and not re.search(r"^## ", output, re.MULTILINE):
        return False, "no '## ' section headers found"

    if "min_proposals" in cfg:
        n = sum(1 for line in output.splitlines() if _PROPOSAL_LINE.match(line))
        if n < cfg["min_proposals"]:
            return False, f"only {n} numbered proposal(s), need ≥ {cfg['min_proposals']}"

    if cfg.get("require_story_headers"):
        if not re.search(r"^#{2,4}\s+Story\s+\d+", output, re.MULTILINE):
            return False, "no story headers found (e.g. '## Story 1:' or '### Story 1:')"

    return True, ""


# ── LLM quality score (profiles 3 + 4 only) ──────────────────────────────────

def llm_quality_score(step: str, output: str, profile: dict) -> tuple[int, str]:
    """Haiku call that rates output 1–5. Called only when profile key is in _LLM_SCORE_PROFILES."""
    client = Anthropic(max_retries=0)  # retries are owned by api_call_with_retry
    prompt = (
        f"Rate the quality of this {step} output on a 1–5 scale "
        "(1=broken/empty, 2=severely degraded, 3=acceptable, 4=good, 5=excellent).\n"
        "The output below is complete: judge it as a whole, including how it ends.\n"
        "Return ONLY valid JSON: {\"score\": <int 1-5>, \"reason\": \"<one sentence>\"}\n\n"
        f"{output}"
    )
    response = api_call_with_retry(
        lambda: client.messages.create(
            model=LIGHT_MODEL,
            # Thinking counts toward max_tokens, so leave room for it and for the whole JSON:
            # a reply cut short loses the score.
            max_tokens=1000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
    )
    # The reply can start with a thinking block, which has no text: join the text blocks.
    raw = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)
    return int(data["score"]), str(data.get("reason", ""))


# ── Composite quality check ───────────────────────────────────────────────────

def check_quality(step: str, output: str, profile: dict) -> QualityResult:
    """Run heuristic check (always) then optional LLM score (profiles 3 and 4)."""
    ok, reason = heuristic_check(step, output)
    if not ok:
        return QualityResult(heuristic_ok=False, warning=reason)

    if profile.get("key") not in _LLM_SCORE_PROFILES:
        return QualityResult(heuristic_ok=True)

    try:
        score, reason = llm_quality_score(step, output, profile)
    except Exception as e:
        # Scorer errors are non-fatal — log but don't block the pipeline
        return QualityResult(heuristic_ok=True, warning=f"{_SCORER_ERROR}{e}")

    warning = reason if score <= 2 else None
    return QualityResult(heuristic_ok=True, llm_score=score, warning=warning)


# ── Interactive failure prompt ────────────────────────────────────────────────

def prompt_quality_failure(
    step: str,
    result: QualityResult,
    output_preview: str = "",
    input_fn=input,
) -> bool:
    """Print warning and ask user whether to continue. Returns True to continue."""
    print(f"\n  ⚠  Quality check FAILED — step '{step}'")
    print(f"     Reason : {result.warning}")
    if output_preview:
        preview = output_preview[:300].replace("\n", " ")
        print(f"     Preview: {preview!r}")
    while True:
        choice = input_fn("\n  Continue anyway? (y/n): ").strip().lower()
        if choice in ("y", "n"):
            break
    return choice == "y"


# ── Run tracker ───────────────────────────────────────────────────────────────

class RunTracker:
    def __init__(self, title: str, timestamp: str) -> None:
        self.title = title
        self.timestamp = timestamp
        self._steps: list[StepMetrics] = []

    @classmethod
    def load(cls, folder: Path, title: str, timestamp: str) -> RunTracker:
        """Rebuild a tracker from a run folder's run-metrics.jsonl (empty when the folder has no metrics file)."""
        tracker = cls(title, timestamp)
        path = folder / "run-metrics.jsonl"
        if not path.exists():
            return tracker
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            tracker.record(StepMetrics(
                step=d["step"],
                model=d["model"],
                input_tokens=d["input_tokens"],
                output_tokens=d["output_tokens"],
                latency_s=d["latency_s"],
                cost_usd=d["cost_usd"],
                quality=QualityResult(**d["quality"]),
                cache_write_tokens=d.get("cache_write_tokens", 0),
                cache_read_tokens=d.get("cache_read_tokens", 0),
                search_count=d.get("search_count", 0),
                **{name: d[name] for name in _TELEMETRY_FIELDS if name in d},
            ))
        return tracker

    def record(self, metrics: StepMetrics) -> None:
        self._steps.append(metrics)

    @property
    def total_cost(self) -> float:
        return sum(s.cost_usd for s in self._steps)

    @property
    def total_latency(self) -> float:
        return sum(s.latency_s for s in self._steps)

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self._steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self._steps)

    @property
    def total_cache_write_tokens(self) -> int:
        return sum(s.cache_write_tokens for s in self._steps)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(s.cache_read_tokens for s in self._steps)

    @property
    def total_searches(self) -> int:
        return sum(s.search_count for s in self._steps)

    @property
    def total_wait_s(self) -> float:
        return sum(s.wait_s for s in self._steps)

    @property
    def total_active_s(self) -> float:
        return sum(s.active_s for s in self._steps)

    @property
    def total_rate_limited(self) -> int:
        return sum(s.rate_limited for s in self._steps)

    @property
    def total_server_errors(self) -> int:
        return sum(s.server_errors for s in self._steps)

    @property
    def total_other_retries(self) -> int:
        return sum(s.other_retries for s in self._steps)

    def _lowest_allowance(self, kind: str) -> tuple[str, int, int | None] | None:
        """(step, tokens left, limit) for the step that saw the least input or output allowance left."""
        seen = [
            (getattr(s, f"min_{kind}_tokens_remaining"), s)
            for s in self._steps
            if getattr(s, f"min_{kind}_tokens_remaining") is not None
        ]
        if not seen:
            return None
        left, step = min(seen, key=lambda pair: pair[0])
        return step.step, left, getattr(step, f"{kind}_tokens_limit")

    def print_summary(self) -> None:
        header = (
            f"  {'Step':<12} {'Model':<8} {'In tok':>8} {'Out tok':>8} {'Srch':>5} {'Cost':>9}"
            f" {'Latency':>8} {'Wait':>7}  Quality"
        )
        sep = "  " + "─" * 86
        print(sep)
        print(header)
        print(sep)
        for s in self._steps:
            short = _SHORT.get(s.model, s.model[:8])
            srch = str(s.search_count) if s.search_count else "-"
            print(
                f"  {s.step:<12} {short:<8} {s.input_tokens:>8,} {s.output_tokens:>8,}"
                f"  {srch:>4}  ${s.cost_usd:>7.4f}  {s.latency_s:>6.1f}s {_wait_cell(s.wait_s)}  {_qstr(s.quality)}"
            )
        print(sep)
        print(
            f"  {'TOTAL':<12} {'':8} {self.total_input_tokens:>8,} {self.total_output_tokens:>8,}"
            f"  {self.total_searches:>4}  ${self.total_cost:>7.4f}  {self.total_latency:>6.1f}s"
            f" {_wait_cell(self.total_wait_s)}"
        )
        print(sep)
        if self.total_cache_write_tokens or self.total_cache_read_tokens or self.total_searches:
            print(
                f"  * cost includes cache write ({self.total_cache_write_tokens:,} tok)"
                f" + cache read ({self.total_cache_read_tokens:,} tok)"
                f" + {self.total_searches} search(es)"
            )
        unscored = sum(1 for s in self._steps if s.quality.scorer_failed)
        if unscored:
            print(f"  * {unscored} step(s) not scored: the model quality score failed (see run-report.md)")
        retries = self.total_rate_limited + self.total_server_errors + self.total_other_retries
        if retries:
            print(
                f"  * {retries} {'retry' if retries == 1 else 'retries'}, {self.total_wait_s:.0f}s waiting: {self.total_rate_limited} rate-limited, "
                f"{self.total_server_errors} server errors, {self.total_other_retries} other"
            )
        for kind in ("input", "output"):
            lowest = self._lowest_allowance(kind)
            if lowest:
                step, left, limit = lowest
                print(f"  * lowest {kind}-token allowance left: {left:,}{_of(limit)} ({step})")

    def write(self, folder: Path) -> None:
        self._write_jsonl(folder)
        self._write_report(folder)

    def _write_jsonl(self, folder: Path) -> None:
        with open(folder / "run-metrics.jsonl", "w") as f:
            for s in self._steps:
                f.write(json.dumps({
                    "step": s.step,
                    "model": s.model,
                    "input_tokens": s.input_tokens,
                    "output_tokens": s.output_tokens,
                    "cache_write_tokens": s.cache_write_tokens,
                    "cache_read_tokens": s.cache_read_tokens,
                    "search_count": s.search_count,
                    "latency_s": round(s.latency_s, 2),
                    "active_s": round(s.active_s, 2),
                    "wait_s": round(s.wait_s, 2),
                    "rate_limited": s.rate_limited,
                    "server_errors": s.server_errors,
                    "other_retries": s.other_retries,
                    "min_input_tokens_remaining": s.min_input_tokens_remaining,
                    "input_tokens_limit": s.input_tokens_limit,
                    "min_output_tokens_remaining": s.min_output_tokens_remaining,
                    "output_tokens_limit": s.output_tokens_limit,
                    "cost_usd": round(s.cost_usd, 6),
                    "quality": {
                        "heuristic_ok": s.quality.heuristic_ok,
                        "llm_score": s.quality.llm_score,
                        "warning": s.quality.warning,
                        "user_continued": s.quality.user_continued,
                    },
                }) + "\n")

    def _write_report(self, folder: Path) -> None:
        lines = [
            f"## Run Report — {self.title} — {self.timestamp}",
            "",
            "| Step | Model | In tok | Cache wr | Cache rd | Searches | Out tok | Est. cost | Latency | Active | Wait | Retries 429/5xx/other | Quality |",
            "|------|-------|-------:|---------:|---------:|---------:|--------:|----------:|--------:|-------:|-----:|----------------------:|---------|",
        ]
        warnings: list[str] = []
        for s in self._steps:
            short = _SHORT.get(s.model, s.model)
            qs = _qstr(s.quality)
            if s.quality.scorer_failed or (s.quality.warning and s.quality.user_continued is not None):
                warnings.append(f"- **{s.step}**: {s.quality.warning}")
            lines.append(
                f"| {s.step} | {short} | {s.input_tokens:,} | {s.cache_write_tokens:,} |"
                f" {s.cache_read_tokens:,} | {s.search_count} | {s.output_tokens:,} |"
                f" ${s.cost_usd:.4f} | {s.latency_s:.1f}s | {s.active_s:.1f}s | {s.wait_s:.1f}s |"
                f" {s.rate_limited}/{s.server_errors}/{s.other_retries} | {qs} |"
            )
        lines.append(
            f"| **TOTAL** | | {self.total_input_tokens:,} | {self.total_cache_write_tokens:,} |"
            f" {self.total_cache_read_tokens:,} | {self.total_searches} | {self.total_output_tokens:,} |"
            f" **${self.total_cost:.4f}** | {self.total_latency:.1f}s | {self.total_active_s:.1f}s |"
            f" {self.total_wait_s:.1f}s | {self.total_rate_limited}/{self.total_server_errors}/{self.total_other_retries} | |"
        )
        headroom = [s for s in self._steps if s.min_input_tokens_remaining is not None or s.min_output_tokens_remaining is not None]
        if headroom:
            lines += [
                "",
                "### Rate-limit headroom",
                "",
                "The least allowance the API reported as left during each step. The API sends these values when a response starts and rounds them to the nearest thousand.",
                "",
                "| Step | Input tokens left | Input limit | Output tokens left | Output limit |",
                "|------|------------------:|------------:|-------------------:|-------------:|",
            ]
            for s in headroom:
                lines.append(
                    f"| {s.step} | {_num(s.min_input_tokens_remaining)} | {_num(s.input_tokens_limit)} |"
                    f" {_num(s.min_output_tokens_remaining)} | {_num(s.output_tokens_limit)} |"
                )
        lines += ["", "### Quality warnings", "None." if not warnings else "\n".join(warnings)]
        (folder / "run-report.md").write_text("\n".join(lines) + "\n")


def _wait_cell(wait_s: float) -> str:
    """Seven-character cell for the Wait column of the terminal summary."""
    return f"{wait_s:>6.1f}s" if wait_s else f"{'-':>7}"


def _num(value: int | None) -> str:
    return f"{value:,}" if value is not None else "–"


def _of(limit: int | None) -> str:
    return f" of {limit:,}" if limit else ""


def _qstr(q: QualityResult) -> str:
    """Single-cell quality display string for tables."""
    if q.scorer_failed:
        return "✓ (not scored)"
    if q.warning and q.user_continued is not None:
        return f"⚠ ({q.llm_score}/5)" if q.llm_score is not None else "⚠"
    if q.llm_score is not None:
        return f"✓ ({q.llm_score}/5)"
    return "✓"
