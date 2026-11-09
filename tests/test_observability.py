"""Gate 1 + Gate 3 unit tests for observability.py."""

import json
import re
import sys
import pytest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from observability import (
    QualityResult,
    RunTracker,
    StepMetrics,
    check_quality,
    estimate_cost,
    heuristic_check,
    llm_quality_score,
    prompt_quality_failure,
)


# ── estimate_cost ─────────────────────────────────────────────────────────────

def test_estimate_cost_haiku():
    cost = estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
    assert abs(cost - (1.00 + 5.00)) < 1e-9


def test_estimate_cost_sonnet():
    cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert abs(cost - (3.00 + 15.00)) < 1e-9


def test_estimate_cost_opus():
    cost = estimate_cost("claude-opus-4-7", 1_000_000, 1_000_000)
    assert abs(cost - (5.00 + 25.00)) < 1e-9


@pytest.mark.parametrize("model", ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-7"])
def test_cache_and_search_charges_follow_the_input_price(model):
    """A 5-minute cache write costs 1.25 times the input price, a read 0.1 times, a search $0.01."""
    base = estimate_cost(model, 1_000_000, 0)
    assert estimate_cost(model, 0, 0, cache_write_tokens=1_000_000) == pytest.approx(base * 1.25)
    assert estimate_cost(model, 0, 0, cache_read_tokens=1_000_000) == pytest.approx(base * 0.10)
    assert estimate_cost(model, 0, 0, search_count=1_000) == pytest.approx(10.00)


def test_published_rates_of_each_model():
    """Per million tokens: input, output, 5-minute cache write, cache read."""
    published = {
        "claude-haiku-4-5-20251001": (1.00, 5.00, 1.25, 0.10),
        "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
        "claude-opus-4-7": (5.00, 25.00, 6.25, 0.50),
    }
    for model, (input_rate, output_rate, write_rate, read_rate) in published.items():
        cost = estimate_cost(model, 1_000_000, 1_000_000, 1_000_000, 1_000_000)
        assert cost == pytest.approx(input_rate + output_rate + write_rate + read_rate), model


def test_every_model_named_in_config_has_a_rate():
    """A model without a rate raises after its call is paid for, so config.yaml may only name rated models."""
    config = (Path(__file__).parent.parent / "config.yaml").read_text()
    models = set(re.findall(r"claude-[a-z0-9.-]+", config))
    assert models, "no models found in config.yaml"
    for model in models:
        estimate_cost(model, 1, 1)  # raises ValueError for an unrated model


def test_estimate_cost_unknown_model():
    with pytest.raises(ValueError, match="unknown-model-xyz"):
        estimate_cost("unknown-model-xyz", 100, 100)


# ── heuristic_check ──────────────────────────────────────────────────────────

_HEADERS = "## Section\n\n" + "x" * 200


def test_heuristic_research_pass():
    ok, reason = heuristic_check("research", _HEADERS)
    assert ok
    assert reason == ""


def test_heuristic_research_fail_too_short():
    ok, reason = heuristic_check("research", "## Short\n\nhi")
    assert not ok
    assert "short" in reason.lower()


def test_heuristic_research_fail_no_headers():
    ok, reason = heuristic_check("research", "x" * 300)
    assert not ok
    assert "header" in reason.lower()


def test_heuristic_spec_fail_too_short():
    ok, reason = heuristic_check("spec", "## H\n\n" + "x" * 400)
    assert not ok
    assert "short" in reason.lower()


def test_heuristic_synthesis_fail_too_few_proposals():
    ok, reason = heuristic_check("synthesis", "1. Only one proposal here")
    assert not ok
    assert "proposal" in reason.lower()


def test_heuristic_synthesis_pass_numbered_list():
    ok, _ = heuristic_check("synthesis", "1. Option A\n2. Option B")
    assert ok


def test_heuristic_synthesis_pass_option_headers():
    output = "## **Option 1 — Community Platform**\n\nsome text\n\n## **Option 2 — Events First**\n\nmore text"
    ok, _ = heuristic_check("synthesis", output)
    assert ok


def test_heuristic_stories_fail_no_stories():
    ok, reason = heuristic_check("stories", "Some text without story headers")
    assert not ok
    assert "story" in reason.lower()


def test_heuristic_stories_pass():
    ok, reason = heuristic_check("stories", "## Story 1: My Feature\n\nSome content")
    assert ok
    assert reason == ""


# ── RunTracker ───────────────────────────────────────────────────────────────

def _make_metrics(step: str, cost: float = 0.01, latency: float = 1.0,
                  warning: str | None = None, user_continued: bool | None = None) -> StepMetrics:
    q = QualityResult(heuristic_ok=True, warning=warning, user_continued=user_continued)
    return StepMetrics(
        step=step,
        model="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=50,
        latency_s=latency,
        cost_usd=cost,
        quality=q,
    )


def test_run_tracker_accumulates_steps():
    t = RunTracker("test", "2026-01-01 00:00")
    for s in ["research", "feedback", "spec"]:
        t.record(_make_metrics(s))
    assert len(t._steps) == 3


def test_run_tracker_total_cost():
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research", cost=0.01))
    t.record(_make_metrics("feedback", cost=0.02))
    t.record(_make_metrics("spec", cost=0.03))
    assert abs(t.total_cost - 0.06) < 1e-9


def test_run_tracker_total_latency():
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research", latency=1.5))
    t.record(_make_metrics("feedback", latency=2.5))
    assert abs(t.total_latency - 4.0) < 1e-9


def test_run_tracker_writes_jsonl(tmp_path):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research"))
    t.record(_make_metrics("feedback"))
    t.write(tmp_path)
    lines = (tmp_path / "run-metrics.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "step" in obj and "cost_usd" in obj and "quality" in obj


def test_run_tracker_writes_report_md(tmp_path):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research"))
    t.write(tmp_path)
    content = (tmp_path / "run-report.md").read_text()
    assert "|" in content
    assert "research" in content


def test_run_tracker_report_contains_totals(tmp_path):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research", cost=0.01))
    t.record(_make_metrics("feedback", cost=0.02))
    t.write(tmp_path)
    content = (tmp_path / "run-report.md").read_text()
    assert "TOTAL" in content
    assert "0.0300" in content


def test_run_tracker_report_quality_warning(tmp_path):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research", warning="output too short", user_continued=True))
    t.write(tmp_path)
    content = (tmp_path / "run-report.md").read_text()
    assert "⚠" in content
    assert "output too short" in content


# ── llm_quality_score (mocked) ───────────────────────────────────────────────

def _mock_response(score: int, reason: str):
    block = MagicMock()
    block.text = json.dumps({"score": score, "reason": reason})
    resp = MagicMock()
    resp.content = [block]
    return resp


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_llm_quality_score_returns_score_and_reason(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    mock_anthropic.return_value.messages.create.return_value = _mock_response(4, "good output")
    score, reason = llm_quality_score("research", "some output", {})
    assert score == 4
    assert "good" in reason


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_llm_quality_score_low_triggers_warning(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    mock_anthropic.return_value.messages.create.return_value = _mock_response(2, "poor output")
    profile = {"key": "3"}
    result = check_quality("research", "## H\n\n" + "x" * 300, profile)
    assert result.llm_score == 2
    assert result.warning is not None


def _scorer_request(mock_anthropic, output):
    mock_anthropic.return_value.messages.create.return_value = _mock_response(4, "good output")
    llm_quality_score("feedback", output, {})
    return mock_anthropic.return_value.messages.create.call_args.kwargs


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_the_scorer_is_sent_the_whole_output(mock_anthropic, mock_retry):
    """A report of 20,000 characters must reach the scorer to its last line, not its first 3,000."""
    mock_retry.side_effect = lambda fn: fn()
    output = "## Start\n\n" + "body text. " * 1800 + "\n\n## Verdict\n\nTHE-LAST-LINE"
    prompt = _scorer_request(mock_anthropic, output)["messages"][0]["content"]
    assert output in prompt and prompt.endswith("THE-LAST-LINE")


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_the_scorer_is_told_the_output_is_complete(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    prompt = _scorer_request(mock_anthropic, "## H\n\ntext")["messages"][0]["content"]
    assert "The output below is complete" in prompt


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_the_scorer_reply_has_room_for_a_long_reason(mock_anthropic, mock_retry):
    """A reply cut short is not valid JSON, and the score in it would be lost."""
    mock_retry.side_effect = lambda fn: fn()
    assert _scorer_request(mock_anthropic, "## H\n\ntext")["max_tokens"] >= 200


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_llm_quality_score_not_called_on_profile_1(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    profile = {"key": "1"}
    result = check_quality("research", "## H\n\n" + "x" * 300, profile)
    mock_retry.assert_not_called()
    assert result.llm_score is None


# ── Failure interaction (Gate 3) ─────────────────────────────────────────────

def test_warn_and_continue_yes(capsys):
    result = QualityResult(heuristic_ok=False, warning="output too short")
    continued = prompt_quality_failure("research", result, "preview text", input_fn=lambda _: "y")
    assert continued is True


def test_warn_and_halt_no(capsys):
    result = QualityResult(heuristic_ok=False, warning="no headers")
    continued = prompt_quality_failure("spec", result, "", input_fn=lambda _: "n")
    assert continued is False


def test_failure_reason_printed(capsys):
    result = QualityResult(heuristic_ok=False, warning="only 1 proposal, need ≥ 2")
    prompt_quality_failure("synthesis", result, "", input_fn=lambda _: "y")
    captured = capsys.readouterr()
    assert "synthesis" in captured.out
    assert "only 1 proposal" in captured.out
