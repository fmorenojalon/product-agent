"""A step that fails after paid requests still has its spend recorded. No API calls, no cost."""

import json
from types import SimpleNamespace

import anthropic
import pytest

import agent
import orchestrator
from agent import StopReasonError, complete
from observability import QualityResult, RunTracker, StepMetrics, estimate_cost
from run_state import RunState
from tests.fakes import make_response as _response, make_usage as _usage, status_error, text_block as _text

MODEL = "claude-sonnet-5-5"
ROUND = dict(input_tokens=15_000, output_tokens=32_000)  # what one paid round of the stories step uses
PROFILE = {"key": "3", "steps": {"stories": {"model": MODEL, "max_tokens": 64_000}}}
STORIES = "## Epic 1: E\n\n### Story 1: S\n\ntext"


def _cut_off(text="part"):
    return _response("max_tokens", _text(text), usage=_usage(**ROUND))


def _refusal():
    return _response(
        "refusal", usage=_usage(**ROUND), stop_details=SimpleNamespace(category="cyber", explanation="blocked"),
    )


def stories_call():
    return complete([{"role": "user", "content": "go"}], model=MODEL, max_tokens=100, step="stories")


def paid(error) -> dict:
    return error.value.paid_usage


# ── complete() carries the usage of the rounds it paid for ───────────────────

def test_a_refusal_after_two_continuations_carries_all_three_paid_rounds(api):
    api.responses = [_cut_off(), _cut_off(), _refusal()]
    with pytest.raises(StopReasonError) as raised:
        stories_call()
    assert paid(raised)["input_tokens"] == 3 * 15_000 and paid(raised)["output_tokens"] == 3 * 32_000


def test_an_api_error_after_two_rounds_carries_those_two(api):
    api.responses = [_cut_off(), _cut_off(), status_error(400)]
    with pytest.raises(anthropic.APIStatusError) as raised:
        stories_call()
    assert paid(raised)["input_tokens"] == 2 * 15_000 and paid(raised)["output_tokens"] == 2 * 32_000


def test_the_usage_has_the_form_of_a_normal_return_with_cache_search_and_waits(api):
    api.responses = [
        _response("pause_turn", usage=_usage(100, 20, written=30, read=40, searches=2)),
        _refusal(),
    ]
    with pytest.raises(StopReasonError) as raised:
        stories_call()
    usage = paid(raised)
    assert (usage["cache_write_tokens"], usage["cache_read_tokens"], usage["search_count"]) == (30, 40, 2)
    assert usage["wait_s"] == 0 and usage["rate_limited"] == 0


def test_a_blank_answer_carries_its_round(api):
    api.responses = [_response("end_turn", usage=_usage(**ROUND))]
    with pytest.raises(StopReasonError, match="no text") as raised:
        stories_call()
    assert paid(raised)["output_tokens"] == 32_000


def test_ctrl_c_after_a_round_carries_that_round(monkeypatch):
    def interrupted(kwargs, stats=None):
        raise KeyboardInterrupt

    script = [lambda kwargs, stats=None: _cut_off(), interrupted]
    monkeypatch.setattr(agent, "_request", lambda kwargs, stats=None: script.pop(0)(kwargs, stats))
    with pytest.raises(KeyboardInterrupt) as raised:
        stories_call()
    assert paid(raised)["output_tokens"] == 32_000


def test_an_error_before_any_round_came_back_carries_nothing(api):
    api.responses = [status_error(400)]
    with pytest.raises(anthropic.APIStatusError) as raised:
        stories_call()
    assert not hasattr(raised.value, "paid_usage")


def test_a_failed_attempt_that_is_retried_is_not_counted(api, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    api.responses = [status_error(429, {"retry-after": "1"}), _cut_off(), _refusal()]
    with pytest.raises(StopReasonError) as raised:
        stories_call()
    assert paid(raised)["output_tokens"] == 2 * 32_000 and paid(raised)["rate_limited"] == 1


# ── the step's row ───────────────────────────────────────────────────────────

def _run_stories(tmp_path, tracker=None, fn=stories_call, profile=PROFILE):
    state = RunState.create(tmp_path / "run") if not (tmp_path / "run").exists() else RunState.load(tmp_path / "run")
    tracker = tracker or RunTracker("t", "ts")
    return state, tracker, lambda: orchestrator._run_step(
        state, tracker, profile, "stories", "user-stories.md", fn, "Stories",
    )


def _rows(folder):
    return [json.loads(line) for line in (folder / "run-metrics.jsonl").read_text().splitlines()]


def test_stories_failing_after_two_rounds_are_recorded_as_two_rounds(api, tmp_path, capsys):
    """The step fails on a permanent error after two paid rounds: the metrics show those two."""
    api.responses = [_cut_off(), _cut_off(), status_error(400)]
    state, tracker, run = _run_stories(tmp_path)
    with pytest.raises(anthropic.APIStatusError):
        run()

    (row,) = _rows(state.folder)
    assert row["step"] == "stories" and row["model"] == MODEL
    assert (row["input_tokens"], row["output_tokens"]) == (2 * 15_000, 2 * 32_000)
    assert row["cost_usd"] == pytest.approx(estimate_cost(MODEL, 2 * 15_000, 2 * 32_000), abs=1e-6)
    assert "APIStatusError" in row["failed"] and "\n" not in row["failed"]
    assert tracker.total_cost == pytest.approx(row["cost_usd"])
    assert "failed after paid requests ($0.7000)" in capsys.readouterr().out
    assert not state.is_done("stories") and not (state.folder / "user-stories.md").exists()


def test_a_refusal_is_recorded_with_its_reason(api, tmp_path):
    api.responses = [_cut_off(), _cut_off(), _refusal()]
    state, tracker, run = _run_stories(tmp_path)
    with pytest.raises(StopReasonError):
        run()
    (row,) = _rows(state.folder)
    assert row["output_tokens"] == 3 * 32_000
    assert "StopReasonError" in row["failed"] and "refusal" in row["failed"]


def test_ctrl_c_is_recorded_as_interrupted(monkeypatch, tmp_path):
    script = [lambda: _cut_off(), lambda: (_ for _ in ()).throw(KeyboardInterrupt)]
    monkeypatch.setattr(agent, "_request", lambda kwargs, stats=None: script.pop(0)())
    state, tracker, run = _run_stories(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run()
    (row,) = _rows(state.folder)
    assert row["failed"] == "interrupted" and row["output_tokens"] == 32_000


def test_a_step_that_failed_before_any_spend_has_no_row(api, tmp_path):
    api.responses = [status_error(400)]
    state, tracker, run = _run_stories(tmp_path)
    with pytest.raises(anthropic.APIStatusError):
        run()
    assert tracker._steps == [] and not (state.folder / "run-metrics.jsonl").exists()


def test_a_failure_with_no_paid_usage_to_report_is_not_recorded(tmp_path):
    """A failure that did not come from complete(), such as a bug in a step, has no usage to record."""
    def broken():
        raise RuntimeError("bug")

    state, tracker, run = _run_stories(tmp_path, fn=broken)
    with pytest.raises(RuntimeError, match="bug"):
        run()
    assert tracker._steps == []


def test_the_original_error_is_the_one_that_propagates(api, tmp_path):
    api.responses = [_cut_off(), _refusal()]
    state, tracker, run = _run_stories(tmp_path)
    with pytest.raises(StopReasonError) as raised:
        run()
    assert raised.value.stop_reason == "refusal"


def test_a_failed_step_with_an_unrated_model_is_recorded_with_an_unknown_cost(api, tmp_path):
    api.responses = [_cut_off(), _refusal()]
    profile = {"key": "3", "steps": {"stories": {"model": "claude-fable-5-1"}}}
    state, tracker, run = _run_stories(tmp_path, profile=profile)
    with pytest.raises(StopReasonError):
        run()
    (row,) = _rows(state.folder)
    assert row["cost_usd"] is None and row["output_tokens"] == 2 * 32_000 and row["failed"]


def test_a_resumed_step_has_a_second_row_and_both_count_in_the_total(api, tmp_path):
    api.responses = [_cut_off(), _refusal()]
    state, tracker, run = _run_stories(tmp_path)
    with pytest.raises(StopReasonError):
        run()

    api.responses = [_response("end_turn", _text(STORIES), usage=_usage(**ROUND))]
    resumed = RunTracker.load(state.folder, "t", "ts")
    resumed_state, _, run_again = _run_stories(tmp_path, tracker=resumed)
    run_again()

    failed_row, ok_row = _rows(state.folder)
    assert failed_row["failed"] and ok_row["failed"] is None
    assert ok_row["output_tokens"] == 32_000
    assert resumed.total_cost == pytest.approx(estimate_cost(MODEL, 3 * 15_000, 3 * 32_000))
    assert resumed_state.is_done("stories")


# ── what the outputs show ────────────────────────────────────────────────────

def _metrics(step="stories", failed=None) -> StepMetrics:
    return StepMetrics(
        step=step, model=MODEL, input_tokens=30_000, output_tokens=64_000, latency_s=5.0, cost_usd=0.7,
        quality=QualityResult(heuristic_ok=failed is None), failed=failed,
    )


def test_the_report_and_summary_mark_the_failed_step(tmp_path, capsys):
    tracker = RunTracker("idea", "now")
    tracker.record(_metrics("spec"))
    tracker.record(_metrics("stories", failed="StopReasonError: Step 'stories' ended with stop_reason='refusal'"))
    tracker.write(tmp_path)
    tracker.print_summary()

    report = (tmp_path / "run-report.md").read_text()
    assert "| stories |" in report and "✗ failed" in report
    assert "### Failed steps" in report
    assert "- **stories**: StopReasonError: Step 'stories' ended with stop_reason='refusal'" in report
    assert report.index("### Failed steps") < report.index("### Quality warnings")
    out = capsys.readouterr().out
    assert "✗ failed" in out and "* failed after being paid for: stories." in out


def test_a_run_with_no_failed_step_shows_none_of_it(tmp_path, capsys):
    tracker = RunTracker("idea", "now")
    tracker.record(_metrics("spec"))
    tracker.write(tmp_path)
    tracker.print_summary()
    assert "Failed steps" not in (tmp_path / "run-report.md").read_text()
    assert "failed" not in capsys.readouterr().out


def test_failed_survives_a_write_and_load_and_older_files_still_load(tmp_path):
    tracker = RunTracker("idea", "now")
    tracker.record(_metrics("stories", failed="interrupted"))
    tracker.write(tmp_path)
    (loaded,) = RunTracker.load(tmp_path, "idea", "now")._steps
    assert loaded.failed == "interrupted"

    row = _rows(tmp_path)[0]
    del row["failed"]
    (tmp_path / "run-metrics.jsonl").write_text(json.dumps(row) + "\n")
    (older,) = RunTracker.load(tmp_path, "idea", "now")._steps
    assert older.failed is None
