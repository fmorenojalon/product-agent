"""The effort setting: read from config.yaml and sent to the API. No API calls."""

import pytest

import agent
import orchestrator
from agent import complete, run_skill, step_effort
from tests.fakes import make_response as _response, text_block as _text

LEVELS = {"low", "medium", "high", "xhigh", "max"}


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n# Skill\n")
    return str(tmp_path)


# ── what the request carries ─────────────────────────────────────────────────

def test_effort_is_sent_as_output_config(api):
    api.responses = [_response("end_turn", _text("done"))]
    complete([{"role": "user", "content": "x"}], model="m", max_tokens=100, effort="low")
    assert api.requests[0]["output_config"] == {"effort": "low"}


def test_no_effort_leaves_the_model_default(api):
    api.responses = [_response("end_turn", _text("done"))]
    complete([{"role": "user", "content": "x"}], model="m", max_tokens=100)
    assert "output_config" not in api.requests[0]


def test_every_round_of_a_continued_answer_carries_the_effort(api):
    api.responses = [
        _response("max_tokens", _text("part one")),
        _response("end_turn", _text("part two")),
    ]
    complete([{"role": "user", "content": "x"}], model="m", max_tokens=100, effort="medium")
    assert [r["output_config"] for r in api.requests] == [{"effort": "medium"}] * 2


def test_a_skill_step_sends_its_configured_effort(api, skill_dir):
    api.responses = [_response("end_turn", _text("done"))]
    profile = {"steps": {"research": {"model": "m", "max_tokens": 100, "max_searches": 0, "effort": "high"}}}
    run_skill(skill_dir, "msg", profile=profile, step="research")
    assert api.requests[0]["output_config"] == {"effort": "high"}


def test_a_direct_call_sends_its_configured_effort(api):
    api.responses = [_response("end_turn", _text("done"))]
    profile = {"steps": {"synthesis": {"model": "m", "max_tokens": 100, "effort": "medium"}}}
    orchestrator._llm([{"role": "user", "content": "x"}], step="synthesis", profile=profile)
    assert api.requests[0]["output_config"] == {"effort": "medium"}


def test_a_step_without_effort_sends_none(api):
    api.responses = [_response("end_turn", _text("done"))]
    profile = {"steps": {"synthesis": {"model": "m", "max_tokens": 100}}}
    orchestrator._llm([{"role": "user", "content": "x"}], step="synthesis", profile=profile)
    assert "output_config" not in api.requests[0]


def test_step_effort_reads_the_step():
    assert step_effort("spec", {"steps": {"spec": {"effort": "low"}}}) == "low"
    assert step_effort("spec", {"steps": {"spec": {}}}) is None
    assert step_effort("spec", {}) is None


# ── the values in config.yaml ────────────────────────────────────────────────

def test_every_effort_in_config_is_a_known_level():
    for key, profile in agent.CONFIG["profiles"].items():
        for step, cfg in profile["steps"].items():
            assert cfg.get("effort") in LEVELS, f"profile {key}, step {step}: {cfg.get('effort')!r}"


def test_the_test_profile_runs_at_low_effort():
    for step, cfg in agent.CONFIG["profiles"]["1"]["steps"].items():
        assert cfg["effort"] == "low", step


@pytest.mark.parametrize("key", ["2", "3", "4"])
def test_small_steps_run_at_low_effort(key):
    profile = agent.load_profile(key)
    for step in ("pre_step", "compress"):
        assert step_effort(step, profile) == "low", step


def test_balanced_profile_runs_its_main_steps_at_medium_effort():
    profile = agent.load_profile("3")
    for step in ("research", "feedback", "synthesis", "spec", "stories"):
        assert step_effort(step, profile) == "medium", step


def test_budget_profile_researches_at_high_effort_and_writes_at_medium():
    """Haiku 5.5 is cheap, and the documentation recommends high for knowledge work and
    longer agent tasks; the steps that do not search stay at medium."""
    profile = agent.load_profile("2")
    for step in ("research", "feedback"):
        assert step_effort(step, profile) == "high", step
    for step in ("synthesis", "spec", "stories"):
        assert step_effort(step, profile) == "medium", step


def test_the_deepest_profile_researches_at_high_effort():
    profile = agent.load_profile("4")
    assert step_effort("research", profile) == "high"
    assert step_effort("feedback", profile) == "high"
    assert step_effort("spec", profile) == "medium"
