"""Gate 1 + Gate 3 unit tests for observability.py."""

import json
import re
import sys
import pytest
import yaml
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import agent
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

# Per million tokens: input, output, 5-minute cache write, cache read.
PUBLISHED = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-haiku-4-5-20251001": (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-opus-4-7": (5.00, 25.00, 6.25, 0.50),
}
# Cache reads cost 0.1 times the input price, except 0.05 times on these two
CACHE_READ_AT_HALF = {"claude-sonnet-5-5", "claude-opus-5-5"}


@pytest.mark.parametrize("model", list(PUBLISHED))
def test_estimate_cost_input_and_output(model):
    input_rate, output_rate, _, _ = PUBLISHED[model]
    assert estimate_cost(model, 1_000_000, 1_000_000) == pytest.approx(input_rate + output_rate)


@pytest.mark.parametrize("model", list(PUBLISHED))
def test_cache_and_search_charges_follow_the_input_price(model):
    """A 5-minute cache write costs 1.25 times the input price, a read 0.1 times (0.05 on
    Sonnet 5.5 and Opus 5.5), a search $0.01."""
    base = estimate_cost(model, 1_000_000, 0)
    read_multiplier = 0.05 if model in CACHE_READ_AT_HALF else 0.10
    assert estimate_cost(model, 0, 0, cache_write_tokens=1_000_000) == pytest.approx(base * 1.25)
    assert estimate_cost(model, 0, 0, cache_read_tokens=1_000_000) == pytest.approx(base * read_multiplier)
    assert estimate_cost(model, 0, 0, search_count=1_000) == pytest.approx(10.00)


def test_published_rates_of_each_model():
    for model, (input_rate, output_rate, write_rate, read_rate) in PUBLISHED.items():
        cost = estimate_cost(model, 1_000_000, 1_000_000, 1_000_000, 1_000_000)
        assert cost == pytest.approx(input_rate + output_rate + write_rate + read_rate), model


def _config_models() -> set[str]:
    config = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())
    return {
        step["model"]
        for profile in config["profiles"].values()
        for step in profile["steps"].values()
    }


def test_every_model_named_in_config_has_a_rate():
    """A model without a rate raises after its call is paid for, so config.yaml may only name rated models."""
    models = _config_models()
    assert models, "no models found in config.yaml"
    for model in models:
        estimate_cost(model, 1, 1)  # raises ValueError for an unrated model


def test_config_uses_the_latest_model_of_each_family():
    assert _config_models() == {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}


def test_the_default_and_scorer_models_have_rates():
    """Neither is named in config.yaml, so the test above does not cover them."""
    estimate_cost(agent.LIGHT_MODEL, 1, 1)
    assert agent.step_model("anything", {}) == agent.LIGHT_MODEL


def test_the_light_model_is_the_latest_haiku():
    assert agent.LIGHT_MODEL == "claude-haiku-5-5"


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
def test_the_scorer_reply_has_room_for_thinking_and_a_long_reason(mock_anthropic, mock_retry):
    """Thinking counts toward max_tokens, and a reply cut short is not valid JSON."""
    mock_retry.side_effect = lambda fn: fn()
    assert _scorer_request(mock_anthropic, "## H\n\ntext")["max_tokens"] >= 1000


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_the_scorer_uses_the_light_model_at_low_effort(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    request = _scorer_request(mock_anthropic, "## H\n\ntext")
    assert request["model"] == agent.LIGHT_MODEL
    assert request["output_config"] == {"effort": "low"}


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


# ── how the models write the proposals ───────────────────────────────────────

def test_heuristic_synthesis_pass_bold_option_lines():
    """Haiku 5.5 wrote its options as a bold line at the start of each paragraph."""
    output = (
        "**Option 1: Drop-in Draft Engine (Standalone, GitHub-first)**\nA focused tool that drafts.\n\n"
        "**Option 2: Publish-Once Changelog Hub with Approval Log**\nA place to approve.\n\n"
        "**Option 3: Issue-Tracker Add-on for Linear and Jira**\nA tracker feature."
    )
    ok, reason = heuristic_check("synthesis", output)
    assert ok, reason


@pytest.mark.parametrize("output", [
    "### Option 1 — First\n\ntext\n\n### Option 2 — Second",
    "Option 1: First\ntext\n\nOption 2: Second",
    "- **Option 1** First\n- **Option 2** Second",
    "## Option 1 — First\n\ntext\n\n## Option 2 — Second",
])
def test_heuristic_synthesis_pass_other_option_styles(output):
    ok, reason = heuristic_check("synthesis", output)
    assert ok, reason


def test_heuristic_synthesis_does_not_count_a_mention_inside_a_sentence():
    ok, _ = heuristic_check("synthesis", "**Option 1: Only one**\nIt is better than Option 2 in every way, unlike Option 3.")
    assert not ok


# ── the test profile's placeholder must pass its own checks ──────────────────

def test_the_test_profile_asks_for_a_placeholder_that_passes_the_spec_check():
    prompt = agent._BRIEF_SYSTEM_PROMPT
    assert "under 80 words" not in prompt and "about 120 words" in prompt and "'## ' sections" in prompt


def test_a_test_run_sends_that_prompt(api, tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n# Skill\n")
    from tests.fakes import make_response, text_block
    api.responses = [make_response("end_turn", text_block("## H\n\nok"))]
    agent.run_skill(str(tmp_path), "msg", profile={"brief_mode": True, "steps": {"spec": {"model": "m", "max_tokens": 100}}}, step="spec")
    assert api.requests[0]["system"] == agent._BRIEF_SYSTEM_PROMPT


@pytest.mark.parametrize("output", [
    # As Haiku 5.5 wrote them: a number, then the word Option, all inside bold
    "**1. Option 1: The Writing Layer (Integrate, Don't Publish)**\nThis direction builds only the drafting step.\n\n"
    "**2. Option 2: Release Governance**\nIt adds approval.\n\n**3. Option 3: Style Coach**\nIt teaches tone.",
    "**1. Option 1: First** This direction builds it.\n**2. Option 2: Second** This one adds approval.",
    "#### 1. Option 1 — First\n\ntext\n\n#### 2. Option 2 — Second",
    "> **Option 1** First\n> **Option 2** Second",
    "__Proposal 1__ First\n\n__Proposal 2__ Second",
    "1) First direction\n2) Second direction",
    "1: First direction\n2: Second direction",
])
def test_heuristic_synthesis_ignores_markdown_decoration(output):
    ok, reason = heuristic_check("synthesis", output)
    assert ok, reason


@pytest.mark.parametrize("output", [
    "Here is the only direction I would take.",
    "**Option 1: The only one**\nIt costs 3.5 million dollars and takes 10:30 hours.",
    "I cannot help with that.",
    # Figures at the start of a line are not list numbers: no space follows the first number
    "3.5 million users is the market size.\n10:30 is when the interview ran.\n2026: the year of the study.",
])
def test_heuristic_synthesis_still_fails_without_two_proposals(output):
    ok, reason = heuristic_check("synthesis", output)
    assert not ok and "proposal" in reason


# ── a model that thinks: the reply can start with a thinking block ───────────

def _thinking_block():
    from anthropic.types import ThinkingBlock
    block = ThinkingBlock(type="thinking", thinking="", signature="")  # the SDK's own class
    assert not hasattr(block, "text"), "the shape that broke the scorer: a block with no .text"
    return block


def _reply(*blocks):
    resp = MagicMock()
    resp.content = list(blocks)
    return resp


def _json_block(score: int, reason: str):
    from types import SimpleNamespace
    return SimpleNamespace(type="text", text=json.dumps({"score": score, "reason": reason}))


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_the_scorer_reads_the_text_after_a_thinking_block(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    mock_anthropic.return_value.messages.create.return_value = _reply(_thinking_block(), _json_block(5, "complete"))
    assert llm_quality_score("spec", "## H\n\ntext", {}) == (5, "complete")


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_check_quality_scores_through_a_thinking_block(mock_anthropic, mock_retry):
    mock_retry.side_effect = lambda fn: fn()
    mock_anthropic.return_value.messages.create.return_value = _reply(_thinking_block(), _json_block(4, "good"))
    result = check_quality("research", "## H\n\n" + "x" * 300, {"key": "3"})
    assert result.llm_score == 4 and not result.scorer_failed and result.warning is None


@patch("observability.api_call_with_retry")
@patch("observability.Anthropic")
def test_a_reply_with_no_text_is_a_scorer_failure_not_a_pass_with_a_score(mock_anthropic, mock_retry):
    """Thinking used the whole reply ceiling: there is nothing to read."""
    mock_retry.side_effect = lambda fn: fn()
    mock_anthropic.return_value.messages.create.return_value = _reply(_thinking_block())
    result = check_quality("research", "## H\n\n" + "x" * 300, {"key": "3"})
    assert result.scorer_failed and result.llm_score is None and result.passed


# ── a failed score is visible ────────────────────────────────────────────────

def _unscored(step="research"):
    q = QualityResult(heuristic_ok=True, warning="scorer error: boom")
    return StepMetrics(step=step, model="claude-sonnet-5-5", input_tokens=10, output_tokens=5,
                       latency_s=1.0, cost_usd=0.01, quality=q)


def test_scorer_failed_only_for_scorer_errors():
    assert QualityResult(heuristic_ok=True, warning="scorer error: boom").scorer_failed
    assert not QualityResult(heuristic_ok=True).scorer_failed
    assert not QualityResult(heuristic_ok=False, warning="output too short").scorer_failed
    assert not QualityResult(heuristic_ok=True, llm_score=2, warning="poor").scorer_failed


def test_the_report_cell_says_not_scored():
    from observability import _qstr
    assert _qstr(_unscored().quality) == "✓ (not scored)"
    assert _qstr(QualityResult(heuristic_ok=True)) == "✓", "profiles without a score are not 'not scored'"
    assert _qstr(QualityResult(heuristic_ok=True, llm_score=4)) == "✓ (4/5)"


def test_the_report_lists_a_failed_score_under_quality_warnings(tmp_path):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_unscored("research"))
    t.write(tmp_path)
    report = (tmp_path / "run-report.md").read_text()
    assert "✓ (not scored)" in report
    assert "- **research**: scorer error: boom" in report
    assert report.rstrip().endswith("scorer error: boom"), "not listed as 'None.'"


def test_the_terminal_summary_counts_the_steps_not_scored(capsys):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_unscored("research"))
    t.record(_unscored("spec"))
    t.print_summary()
    assert "2 step(s) not scored: the model quality score failed" in capsys.readouterr().out


def test_the_terminal_summary_is_quiet_when_every_step_is_scored_or_not_expected(capsys):
    t = RunTracker("test", "2026-01-01 00:00")
    t.record(_make_metrics("research"))
    t.print_summary()
    assert "not scored" not in capsys.readouterr().out
