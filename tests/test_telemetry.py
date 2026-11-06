"""Waits, retries and rate-limit headroom recorded per step. No API calls, no cost."""

import json
from itertools import chain, repeat
from types import SimpleNamespace

import anthropic
import pytest

import orchestrator
from agent import CallStats, api_call_with_retry, complete
from observability import QualityResult, RunTracker, StepMetrics
from tests.fakes import (
    make_response as _response, rate_limit_headers as _headers, results_block as _results,
    search_block as _search, status_error, stream_error, text_block as _text,
)

TOOLS = [{"type": "web_search_20250305", "name": "web_search"}]


def call(**kwargs):
    return complete([{"role": "user", "content": "go"}], model="m", max_tokens=100, step="research", **kwargs)


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr("time.sleep", recorded.append)
    return recorded


# ── waits and retries ────────────────────────────────────────────────────────

def test_a_call_with_no_retries_reports_none(api):
    api.responses = [_response("end_turn", _text("done"))]
    _, usage = call()
    assert (usage["wait_s"], usage["rate_limited"], usage["server_errors"], usage["other_retries"]) == (0.0, 0, 0, 0)


def test_waits_are_summed_and_retries_counted_by_class(api, sleeps):
    api.responses = [
        stream_error("overloaded_error"),
        status_error(429, {"retry-after": "7"}),
        anthropic.APIConnectionError(request=SimpleNamespace()),
        _response("end_turn", _text("done")),
    ]
    _, usage = call()
    assert (usage["rate_limited"], usage["server_errors"], usage["other_retries"]) == (1, 1, 1)
    assert len(sleeps) == 3
    assert usage["wait_s"] == pytest.approx(sum(sleeps)) and usage["wait_s"] >= 7


@pytest.mark.parametrize("error, counter", [
    (lambda: status_error(429), "rate_limited"),
    (lambda: status_error(503), "server_errors"),
    (lambda: status_error(529), "server_errors"),
    (lambda: status_error(408), "other_retries"),
    (lambda: status_error(409), "other_retries"),
    (lambda: stream_error("rate_limit_error"), "rate_limited"),
    (lambda: stream_error("overloaded_error"), "server_errors"),
    (lambda: stream_error("api_error"), "server_errors"),
])
def test_each_kind_of_retry_has_its_own_counter(api, sleeps, error, counter):
    api.responses = [error(), _response("end_turn", _text("done"))]
    _, usage = call()
    counts = {name: usage[name] for name in ("rate_limited", "server_errors", "other_retries")}
    assert counts == {name: int(name == counter) for name in counts}


def test_an_error_that_is_not_retried_leaves_the_counters_alone():
    stats = CallStats()
    def rejected():
        raise status_error(400)

    with pytest.raises(anthropic.APIStatusError):
        api_call_with_retry(rejected, stats=stats)
    assert stats.as_usage()["wait_s"] == 0 and stats.rate_limited == 0


# ── rate-limit headroom, read from the headers ───────────────────────────────

def test_the_lowest_allowance_is_kept_across_rounds(api):
    api.responses = [
        _response("pause_turn", _search(), _results(), headers=_headers(1_990_000, 2_000_000, 399_000, 400_000)),
        _response("end_turn", _text("done"), headers=_headers(1_975_000, 2_000_000, 399_500, 400_000)),
    ]
    _, usage = call(tools=TOOLS)
    assert usage["min_input_tokens_remaining"] == 1_975_000
    assert usage["min_output_tokens_remaining"] == 399_000
    assert usage["input_tokens_limit"] == 2_000_000 and usage["output_tokens_limit"] == 400_000


def test_headers_of_a_failed_attempt_count_too(api, sleeps):
    api.responses = [
        status_error(429, {"retry-after": "1", **_headers(0, 2_000_000, 0, 400_000)}),
        _response("end_turn", _text("done"), headers=_headers(1_000_000, 2_000_000, 300_000, 400_000)),
    ]
    _, usage = call()
    assert usage["min_input_tokens_remaining"] == 0 and usage["min_output_tokens_remaining"] == 0


def test_a_mid_stream_failure_still_records_its_headers(api, sleeps):
    failed = stream_error("overloaded_error")
    failed.response.headers.update(_headers(1_960_000, 2_000_000))
    api.responses = [failed, _response("end_turn", _text("done"), headers=_headers(1_990_000, 2_000_000))]
    _, usage = call()
    assert usage["min_input_tokens_remaining"] == 1_960_000


@pytest.mark.parametrize("limit", [30_000, 2_000_000])
def test_the_recorded_limits_follow_the_headers_with_no_config_change(api, limit):
    """The pipeline holds no limits of its own: a different tier shows up in what it records."""
    api.responses = [_response("end_turn", _text("done"), headers=_headers(limit - 1_000, limit, 5_000, limit // 5))]
    _, usage = call()
    assert usage["input_tokens_limit"] == limit and usage["output_tokens_limit"] == limit // 5


def test_without_the_headers_the_fields_are_empty(api):
    api.responses = [_response("end_turn", _text("done"))]
    _, usage = call()
    assert usage["min_input_tokens_remaining"] is None and usage["input_tokens_limit"] is None
    assert usage["min_output_tokens_remaining"] is None and usage["output_tokens_limit"] is None


def test_unreadable_header_values_are_ignored(api):
    api.responses = [_response("end_turn", _text("done"), headers={
        "anthropic-ratelimit-input-tokens-remaining": "n/a",
        "anthropic-ratelimit-input-tokens-limit": "",
    })]
    _, usage = call()
    assert usage["min_input_tokens_remaining"] is None and usage["input_tokens_limit"] is None


# ── a step's active time excludes its waits ──────────────────────────────────

PROFILE = {"key": "2", "steps": {"research": {"model": "claude-haiku-4-5-20251001"}}}
OUTPUT = "## Heading\n\n" + "x" * 300


def _track(monkeypatch, usage, seconds=10.0):
    tracker = RunTracker("t", "now")
    clock = chain([100.0, 100.0 + seconds], repeat(100.0 + seconds))
    monkeypatch.setattr(orchestrator.time, "time", lambda: next(clock))
    orchestrator._track_step("research", lambda: (OUTPUT, usage), PROFILE, tracker)
    return tracker._steps[0]


def test_active_time_is_latency_minus_waiting(monkeypatch):
    usage = {
        "input_tokens": 1, "output_tokens": 1, "wait_s": 4.0, "rate_limited": 2, "server_errors": 0,
        "other_retries": 1, "min_input_tokens_remaining": 5_000, "input_tokens_limit": 30_000,
        "min_output_tokens_remaining": 1_000, "output_tokens_limit": 8_000,
    }
    step = _track(monkeypatch, usage)
    assert (step.latency_s, step.wait_s, step.active_s) == (10.0, 4.0, 6.0)
    assert (step.rate_limited, step.server_errors, step.other_retries) == (2, 0, 1)
    assert (step.min_input_tokens_remaining, step.input_tokens_limit) == (5_000, 30_000)
    assert (step.min_output_tokens_remaining, step.output_tokens_limit) == (1_000, 8_000)


def test_a_step_without_telemetry_gets_defaults(monkeypatch):
    step = _track(monkeypatch, {"input_tokens": 1, "output_tokens": 1})
    assert step.wait_s == 0 and step.active_s == 10.0 and step.min_input_tokens_remaining is None


def test_active_time_is_never_negative():
    assert _metrics("research", latency_s=1.0, wait_s=5.0).active_s == 0.0


# ── what the outputs show ────────────────────────────────────────────────────

def _metrics(step="research", **extra) -> StepMetrics:
    fields = dict(
        step=step, model="claude-sonnet-4-6", input_tokens=1200, output_tokens=300, latency_s=10.0,
        cost_usd=0.04, quality=QualityResult(heuristic_ok=True),
    )
    return StepMetrics(**{**fields, **extra})


WAITED = dict(
    wait_s=4.0, rate_limited=2, server_errors=0, other_retries=1,
    min_input_tokens_remaining=5_000, input_tokens_limit=30_000,
    min_output_tokens_remaining=1_000, output_tokens_limit=8_000,
)


def _tracker(*metrics):
    tracker = RunTracker("idea", "2026-11-06 10:00")
    for m in metrics:
        tracker.record(m)
    return tracker


def test_jsonl_separates_work_from_waiting(tmp_path):
    _tracker(_metrics(**WAITED)).write(tmp_path)
    row = json.loads((tmp_path / "run-metrics.jsonl").read_text())
    assert (row["latency_s"], row["active_s"], row["wait_s"]) == (10.0, 6.0, 4.0)
    assert (row["rate_limited"], row["server_errors"], row["other_retries"]) == (2, 0, 1)
    assert row["min_input_tokens_remaining"] == 5_000 and row["input_tokens_limit"] == 30_000
    assert row["min_output_tokens_remaining"] == 1_000 and row["output_tokens_limit"] == 8_000


def test_report_has_active_wait_and_retry_columns(tmp_path):
    _tracker(_metrics(**WAITED)).write(tmp_path)
    report = (tmp_path / "run-report.md").read_text()
    assert "| Latency | Active | Wait | Retries 429/5xx/other |" in report
    assert "| 10.0s | 6.0s | 4.0s | 2/0/1 |" in report
    assert "| **TOTAL** |" in report and "| 6.0s | 4.0s | 2/0/1 |" in report


def test_report_lists_rate_limit_headroom_per_step(tmp_path):
    _tracker(_metrics(**WAITED), _metrics("spec")).write(tmp_path)
    report = (tmp_path / "run-report.md").read_text()
    assert "### Rate-limit headroom" in report
    assert "| research | 5,000 | 30,000 | 1,000 | 8,000 |" in report
    assert "| spec |" not in report.split("### Rate-limit headroom")[1], "a step without headers has no row"


def test_report_has_no_headroom_section_without_headers(tmp_path):
    _tracker(_metrics()).write(tmp_path)
    assert "Rate-limit headroom" not in (tmp_path / "run-report.md").read_text()


def test_summary_has_a_wait_column_and_footnotes(capsys):
    _tracker(_metrics(**WAITED), _metrics("spec", min_input_tokens_remaining=9_000, input_tokens_limit=30_000)).print_summary()
    out = capsys.readouterr().out
    assert "Latency    Wait" in out and "4.0s" in out
    assert "* 3 retries, 4s waiting: 2 rate-limited, 0 server errors, 1 other" in out
    assert "* lowest input-token allowance left: 5,000 of 30,000 (research)" in out
    assert "* lowest output-token allowance left: 1,000 of 8,000 (research)" in out


def test_summary_footnote_uses_the_singular_for_one_retry(capsys):
    _tracker(_metrics(wait_s=8.2, rate_limited=1)).print_summary()
    assert "* 1 retry, 8s waiting: 1 rate-limited, 0 server errors, 0 other" in capsys.readouterr().out


def test_summary_without_retries_or_headers_has_no_extra_footnotes(capsys):
    _tracker(_metrics()).print_summary()
    out = capsys.readouterr().out
    assert "retries" not in out and "allowance" not in out
    assert "10.0s       -  ✓" in out, "the Wait column shows a dash when nothing waited"


def test_metrics_written_before_these_fields_still_load(tmp_path):
    old = {
        "step": "research", "model": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5,
        "cache_write_tokens": 0, "cache_read_tokens": 0, "search_count": 1, "latency_s": 12.5,
        "cost_usd": 0.01,
        "quality": {"heuristic_ok": True, "llm_score": None, "warning": None, "user_continued": None},
    }
    (tmp_path / "run-metrics.jsonl").write_text(json.dumps(old) + "\n")
    (step,) = RunTracker.load(tmp_path, "idea", "now")._steps
    assert step.latency_s == 12.5 and step.wait_s == 0.0 and step.active_s == 12.5
    assert step.min_input_tokens_remaining is None


def test_the_new_fields_survive_a_write_and_load(tmp_path):
    _tracker(_metrics(**WAITED)).write(tmp_path)
    (step,) = RunTracker.load(tmp_path, "idea", "now")._steps
    assert (step.wait_s, step.rate_limited, step.other_retries) == (4.0, 2, 1)
    assert (step.min_input_tokens_remaining, step.output_tokens_limit) == (5_000, 8_000)
