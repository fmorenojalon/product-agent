"""Pipeline observability — per-step cost, latency, and output quality tracking."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic
from agent import api_call_with_retry

# ── Pricing ───────────────────────────────────────────────────────────────────
# Verify against https://anthropic.com/pricing before each release.
RATES_UPDATED = "2026-05-22"
_RATES: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00},
}
_SHORT: dict[str, str] = {
    "claude-haiku-4-5-20251001": "haiku",
    "claude-sonnet-4-6":         "sonnet",
    "claude-opus-4-7":           "opus",
}

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

@dataclass
class QualityResult:
    heuristic_ok: bool
    llm_score: int | None = None
    warning: str | None = None
    user_continued: bool | None = None

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


# ── Cost estimation ───────────────────────────────────────────────────────────

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost. Raises ValueError for unknown models."""
    if model not in _RATES:
        raise ValueError(f"Unknown model: {model!r}. Add it to _RATES in observability.py.")
    r = _RATES[model]
    return (input_tokens / 1_000_000) * r["input"] + (output_tokens / 1_000_000) * r["output"]


# ── Heuristic quality check ───────────────────────────────────────────────────

def heuristic_check(step: str, output: str) -> tuple[bool, str]:
    """Return (passed, reason). reason is '' when passed."""
    cfg = _HEURISTICS.get(step, {})

    if "min_chars" in cfg and len(output) < cfg["min_chars"]:
        return False, f"output too short ({len(output)} chars, need ≥ {cfg['min_chars']})"

    if cfg.get("require_headers") and not re.search(r"^## ", output, re.MULTILINE):
        return False, "no '## ' section headers found"

    if "min_proposals" in cfg:
        n = len(re.findall(r"^\s*\d+[\.\)]\s+\S", output, re.MULTILINE))
        if n < cfg["min_proposals"]:
            return False, f"only {n} numbered proposal(s), need ≥ {cfg['min_proposals']}"

    if cfg.get("require_story_headers"):
        if not re.search(r"^#{2,4}\s+Story\s+\d+", output, re.MULTILINE):
            return False, "no story headers found (e.g. '## Story 1:' or '### Story 1:')"

    return True, ""


# ── LLM quality score (profiles 3 + 4 only) ──────────────────────────────────

def llm_quality_score(step: str, output: str, profile: dict) -> tuple[int, str]:
    """Haiku call that rates output 1–5. Called only when profile key is in _LLM_SCORE_PROFILES."""
    client = Anthropic()
    prompt = (
        f"Rate the quality of this {step} output on a 1–5 scale "
        "(1=broken/empty, 2=severely degraded, 3=acceptable, 4=good, 5=excellent).\n"
        "Return ONLY valid JSON: {\"score\": <int 1-5>, \"reason\": \"<one sentence>\"}\n\n"
        f"{output[:3000]}"
    )
    response = api_call_with_retry(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    raw = response.content[0].text.strip()
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
        return QualityResult(heuristic_ok=True, warning=f"scorer error: {e}")

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

    def print_summary(self) -> None:
        header = f"  {'Step':<12} {'Model':<8} {'In tok':>8} {'Out tok':>8} {'Cost':>9} {'Latency':>8}  Quality"
        sep = "  " + "─" * 72
        print(sep)
        print(header)
        print(sep)
        for s in self._steps:
            short = _SHORT.get(s.model, s.model[:8])
            print(
                f"  {s.step:<12} {short:<8} {s.input_tokens:>8,} {s.output_tokens:>8,}"
                f"  ${s.cost_usd:>7.4f}  {s.latency_s:>6.1f}s  {_qstr(s.quality)}"
            )
        print(sep)
        print(
            f"  {'TOTAL':<12} {'':8} {self.total_input_tokens:>8,} {self.total_output_tokens:>8,}"
            f"  ${self.total_cost:>7.4f}  {self.total_latency:>6.1f}s"
        )
        print(sep)

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
                    "latency_s": round(s.latency_s, 2),
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
            "| Step | Model | In tok | Out tok | Est. cost | Latency | Quality |",
            "|------|-------|-------:|--------:|----------:|--------:|---------|",
        ]
        warnings: list[str] = []
        for s in self._steps:
            short = _SHORT.get(s.model, s.model)
            qs = _qstr(s.quality)
            if s.quality.warning and s.quality.user_continued is not None:
                warnings.append(f"- **{s.step}**: {s.quality.warning}")
            lines.append(
                f"| {s.step} | {short} | {s.input_tokens:,} | {s.output_tokens:,} |"
                f" ${s.cost_usd:.4f} | {s.latency_s:.1f}s | {qs} |"
            )
        lines.append(
            f"| **TOTAL** | | {self.total_input_tokens:,} | {self.total_output_tokens:,} |"
            f" **${self.total_cost:.4f}** | {self.total_latency:.1f}s | |"
        )
        lines += ["", "### Quality warnings", "None." if not warnings else "\n".join(warnings)]
        (folder / "run-report.md").write_text("\n".join(lines) + "\n")


def _qstr(q: QualityResult) -> str:
    """Single-cell quality display string for tables."""
    if q.warning and q.user_continued is not None:
        return f"⚠ ({q.llm_score}/5)" if q.llm_score is not None else "⚠"
    if q.llm_score is not None:
        return f"✓ ({q.llm_score}/5)"
    return "✓"
