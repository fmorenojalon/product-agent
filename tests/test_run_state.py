"""Tests for run_state.py and the tracker's reload from a run folder. No API calls."""

import json

import pytest

import run_state
from observability import QualityResult, RunTracker, StepMetrics
from run_state import STATE_FILE, RunState, write_text_atomic


# ── RunState ─────────────────────────────────────────────────────────────────

def test_create_makes_the_folder_and_state_file(tmp_path):
    folder = tmp_path / "output" / "run"
    RunState.create(folder, title="idea")
    assert json.loads((folder / STATE_FILE).read_text())["values"] == {"title": "idea"}


def test_round_trip(tmp_path):
    state = RunState.create(tmp_path, title="idea", full_scope=True)
    state.complete("pre_step", competitors=["A", "B"], persona="project manager")
    state.complete("research")

    loaded = RunState.load(tmp_path)
    assert loaded.get("title") == "idea"
    assert loaded.get("competitors") == ["A", "B"]
    assert loaded.is_done("pre_step") and loaded.is_done("research")
    assert not loaded.is_done("feedback")
    assert loaded.finished == ["pre_step", "research"]


def test_complete_is_idempotent(tmp_path):
    state = RunState.create(tmp_path)
    state.complete("research")
    state.complete("research")
    assert state.finished == ["research"]


def test_set_saves_without_marking_a_step_done(tmp_path):
    state = RunState.create(tmp_path)
    state.set(input_sha256="abc")
    loaded = RunState.load(tmp_path)
    assert loaded.get("input_sha256") == "abc"
    assert loaded.finished == []


def test_get_returns_default_for_missing_key(tmp_path):
    state = RunState.create(tmp_path)
    assert state.get("chosen") is None
    assert state.get("interview_context", "") == ""


def test_empty_string_value_is_kept(tmp_path):
    """An empty answer at the human gate is still an answer, and must not read as 'not asked'."""
    state = RunState.create(tmp_path)
    state.complete("gate", chosen="")
    assert RunState.load(tmp_path).get("chosen") == ""


def test_non_ascii_values_round_trip(tmp_path):
    state = RunState.create(tmp_path)
    state.complete("pre_step", persona="diseñador — café")
    assert RunState.load(tmp_path).get("persona") == "diseñador — café"


def test_load_missing_state_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="nothing to resume"):
        RunState.load(tmp_path)


def test_load_corrupt_state_raises_value_error(tmp_path):
    (tmp_path / STATE_FILE).write_text("{not json")
    with pytest.raises(ValueError, match="unreadable"):
        RunState.load(tmp_path)


def test_load_state_without_expected_keys_raises_value_error(tmp_path):
    (tmp_path / STATE_FILE).write_text(json.dumps({"version": 1}))
    with pytest.raises(ValueError, match="unreadable"):
        RunState.load(tmp_path)


def test_load_wrong_version_raises_value_error(tmp_path):
    (tmp_path / STATE_FILE).write_text(json.dumps({"version": 99, "values": {}, "done": []}))
    with pytest.raises(ValueError, match="version"):
        RunState.load(tmp_path)


# ── write_text_atomic ────────────────────────────────────────────────────────

def test_write_text_atomic_replaces_content_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "out.md"
    write_text_atomic(target, "first")
    write_text_atomic(target, "second")
    assert target.read_text() == "second"
    assert [p.name for p in tmp_path.iterdir()] == ["out.md"]


def test_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "out.md"
    write_text_atomic(target, "good")

    def boom(*_):
        raise OSError("disk full")

    monkeypatch.setattr(run_state.os, "replace", boom)
    with pytest.raises(OSError):
        write_text_atomic(target, "half-written")
    assert target.read_text() == "good"


# ── RunTracker.load ──────────────────────────────────────────────────────────

def _metrics(step: str, **quality) -> StepMetrics:
    return StepMetrics(
        step=step,
        model="claude-sonnet-4-6",
        input_tokens=1200,
        output_tokens=300,
        latency_s=12.5,
        cost_usd=0.0405,
        quality=QualityResult(heuristic_ok=True, **quality),
        cache_write_tokens=10,
        cache_read_tokens=20,
        search_count=3,
    )


def test_tracker_load_round_trips_written_metrics(tmp_path):
    original = RunTracker("idea", "2026-11-06 10:00")
    original.record(_metrics("research", llm_score=4))
    original.record(_metrics("feedback", warning="output too short", user_continued=False))
    original.write(tmp_path)

    loaded = RunTracker.load(tmp_path, "idea", "2026-11-06 10:00")
    assert [s.step for s in loaded._steps] == ["research", "feedback"]
    assert loaded._steps[0].quality.llm_score == 4
    assert loaded._steps[1].quality.user_continued is False
    assert loaded.total_input_tokens == original.total_input_tokens
    assert loaded.total_searches == 6
    assert loaded.total_cost == pytest.approx(original.total_cost)


def test_tracker_load_without_metrics_file_is_empty(tmp_path):
    assert RunTracker.load(tmp_path, "idea", "now")._steps == []
