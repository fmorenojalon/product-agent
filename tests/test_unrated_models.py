"""A model with no rate: the run stops before any request, and a cost that cannot be priced is
recorded as unknown. No API calls, no cost."""

import builtins
import json
import sys

import pytest

import agent
import orchestrator
from observability import QualityResult, RunTracker, StepMetrics, profile_models, unrated_models
from run_state import RunState

UNRATED = "claude-fable-5-1"
SPEC = "## Spec\n\n" + "x" * 600
USAGE = {"input_tokens": 20_000, "output_tokens": 8_000, "cache_write_tokens": 0, "cache_read_tokens": 0}


def _profile(**models: str) -> dict:
    """A profile whose steps use the given models, step name -> model."""
    return {
        "name": "p", "brief_mode": False, "context_mode": "full",
        "steps": {step: {"model": model, "max_tokens": 1000} for step, model in models.items()},
    }


# ── which models a profile can call ──────────────────────────────────────────

def test_a_profile_uses_the_models_its_steps_name_and_the_light_model():
    models = profile_models(_profile(research="claude-opus-5-5", spec="claude-sonnet-5-5"))
    assert models == {"claude-opus-5-5", "claude-sonnet-5-5", agent.LIGHT_MODEL}


def test_a_profile_that_names_no_model_still_uses_the_light_model():
    """A step with no model runs on it, and so does the quality score."""
    assert profile_models({}) == {agent.LIGHT_MODEL}
    assert profile_models({"steps": {"spec": {"max_tokens": 10}}}) == {agent.LIGHT_MODEL}


def test_unrated_models_are_listed_sorted_and_once():
    assert unrated_models(["b-new", "claude-haiku-5-5", "a-new", "b-new"]) == ["a-new", "b-new"]
    assert unrated_models(["claude-haiku-5-5"]) == []


def test_every_profile_in_config_has_only_rated_models():
    for key, profile in agent.CONFIG["profiles"].items():
        assert unrated_models(profile_models(profile)) == [], key


# ── a run with an unrated model stops before any request ─────────────────────

@pytest.fixture
def cli(monkeypatch, tmp_path, api):
    """Drives orchestrator.main() with the profile in `current`. `api` records every request."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "idea.md").write_text("# Idea\n\nA tool.")
    state = {"profile": _profile(research=UNRATED, spec=UNRATED)}
    monkeypatch.setattr(orchestrator, "load_profile", lambda key: dict(state["profile"]))
    monkeypatch.setattr(orchestrator, "select_profile", lambda: {**state["profile"], "key": "9"})
    monkeypatch.setattr(orchestrator, "choose_mode", lambda brief: False)
    monkeypatch.setattr(orchestrator, "choose_story_scope", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_: pytest.fail("no prompt expected"))
    started = []
    monkeypatch.setattr(orchestrator, "_run_pipeline", lambda st, profile, doc: started.append(st.folder))

    class Cli:
        requests = api.requests
        pipeline_started = started
        profile = state

        @staticmethod
        def run(*argv):
            monkeypatch.setattr(sys, "argv", ["orchestrator.py", *argv])
            orchestrator.main()

        @staticmethod
        def folder():
            (folder,) = (tmp_path / "output").iterdir()
            return folder

    return Cli


def test_a_new_run_with_an_unrated_model_stops_before_any_request(cli, capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.run("idea.md")
    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert UNRATED in out and "_RATES" in out and "Nothing was sent to the API" in out
    assert cli.requests == [] and cli.pipeline_started == []
    assert not (cli.folder() / "run-metrics.jsonl").exists()


def test_a_resume_with_an_unrated_model_stops_before_any_request(cli, capsys):
    with pytest.raises(SystemExit):
        cli.run("idea.md")
    capsys.readouterr()

    with pytest.raises(SystemExit) as stopped:
        cli.run("--resume", str(cli.folder()))
    assert stopped.value.code == 1
    assert UNRATED in capsys.readouterr().out
    assert cli.requests == [] and cli.pipeline_started == []


def test_the_run_goes_ahead_once_the_model_has_a_rate_or_is_replaced(cli, capsys):
    with pytest.raises(SystemExit):
        cli.run("idea.md")
    out = capsys.readouterr().out
    assert f"--resume output/{cli.folder().name}" in out, "the message names the command to resume with"

    cli.profile["profile"] = _profile(research="claude-sonnet-5-5", spec="claude-sonnet-5-5")
    cli.run("--resume", str(cli.folder()))
    assert cli.pipeline_started == [cli.folder()]


@pytest.mark.parametrize("step", ["pre_step", "compress", "research", "feedback", "synthesis", "spec", "stories"])
def test_any_step_with_an_unrated_model_stops_the_run(cli, capsys, step):
    cli.profile["profile"] = _profile(**{step: UNRATED})
    with pytest.raises(SystemExit):
        cli.run("idea.md")
    assert UNRATED in capsys.readouterr().out and cli.requests == []


def test_every_unrated_model_is_listed(cli, capsys):
    cli.profile["profile"] = _profile(research="claude-new-a", spec="claude-new-b", stories="claude-sonnet-5-5")
    with pytest.raises(SystemExit):
        cli.run("idea.md")
    out = capsys.readouterr().out
    assert "claude-new-a, claude-new-b" in out and "claude-sonnet-5-5" not in out


# ── a cost that cannot be priced is recorded as unknown ──────────────────────

def _run_unrated_step(tmp_path):
    state = RunState.create(tmp_path / "run")
    tracker = RunTracker("t", "ts")
    profile = {"key": "2", **_profile(spec=UNRATED)}
    output = orchestrator._run_step(state, tracker, profile, "spec", "product-spec.md", lambda: (SPEC, dict(USAGE)), "Spec")
    return state, tracker, output


def test_a_step_with_an_unrated_model_keeps_its_output_and_records_an_unknown_cost(tmp_path, capsys):
    state, tracker, output = _run_unrated_step(tmp_path)

    assert output == SPEC and (state.folder / "product-spec.md").read_text() == SPEC
    assert state.is_done("spec")
    (step,) = tracker._steps
    assert step.cost_usd is None and step.input_tokens == 20_000 and step.output_tokens == 8_000
    out = capsys.readouterr().out
    assert "Cost unknown for step 'spec'" in out and UNRATED in out


def test_the_unknown_cost_is_saved_as_null_and_survives_a_resume(tmp_path):
    state, tracker, _ = _run_unrated_step(tmp_path)

    (row,) = [json.loads(line) for line in (state.folder / "run-metrics.jsonl").read_text().splitlines()]
    assert row["cost_usd"] is None and row["input_tokens"] == 20_000
    (loaded,) = RunTracker.load(state.folder, "t", "ts")._steps
    assert loaded.cost_usd is None


# ── the totals and the outputs say what is unknown ───────────────────────────

def _metrics(step, cost, model="claude-sonnet-5-5"):
    return StepMetrics(
        step=step, model=model, input_tokens=1000, output_tokens=500, latency_s=2.0,
        cost_usd=cost, quality=QualityResult(heuristic_ok=True),
    )


def _mixed():
    tracker = RunTracker("idea", "2026-11-12 10:00")
    tracker.record(_metrics("research", 0.25))
    tracker.record(_metrics("spec", None, UNRATED))
    tracker.record(_metrics("stories", 0.5))
    return tracker


def test_the_total_adds_the_priced_steps_and_names_the_others():
    tracker = _mixed()
    assert tracker.total_cost == pytest.approx(0.75)
    assert tracker.unpriced_steps == ["spec"]


def test_the_terminal_summary_shows_unknown_and_says_the_total_leaves_it_out(capsys):
    _mixed().print_summary()
    out = capsys.readouterr().out
    spec_row = next(line for line in out.splitlines() if line.lstrip().startswith("spec"))
    assert "unknown" in spec_row and "$" not in spec_row
    assert "* cost unknown for spec: the model has no rate in _RATES" in out
    assert "The total leaves those steps out." in out
    assert "$ 0.7500" in out


def test_the_report_shows_unknown_and_says_the_total_leaves_it_out(tmp_path):
    _mixed().write(tmp_path)
    report = (tmp_path / "run-report.md").read_text()
    assert "| spec | " in report and "| unknown |" in report
    assert "Cost unknown: cost unknown for spec" in report
    assert "**$0.7500**" in report


def test_a_run_with_every_cost_known_has_no_unknown_note(tmp_path, capsys):
    tracker = RunTracker("idea", "now")
    tracker.record(_metrics("research", 0.25))
    tracker.print_summary()
    tracker.write(tmp_path)
    assert "unknown" not in capsys.readouterr().out
    assert "unknown" not in (tmp_path / "run-report.md").read_text()
