"""--redo: run a step and the steps after it again on a saved run. No API calls, no cost.

Reuses the fake model of test_resume.py.
"""

import pytest

import orchestrator
from orchestrator import _STEP_ORDER, _redo
from run_state import RunState
from tests.test_resume import SPEC, STORIES, fake  # noqa: F401  (fixture)

NEW_STORIES = "## Epic 1: Core\n\n### Story 1: A shorter story\n\nAs a PM, I want x, So that y."


@pytest.fixture
def finished(fake):
    """A run that finished, with every step called once."""
    fake.run("idea.md")
    return fake


def _calls(fake):
    return dict(fake.calls)


# ── the steps that run again ─────────────────────────────────────────────────

def test_redo_stories_runs_only_the_stories_step_again(finished):
    before = _calls(finished)
    finished.stories_text = NEW_STORIES
    finished.run("--resume", str(finished.run_folder()), "--redo", "stories")

    after = _calls(finished)
    assert after["stories"] == before["stories"] + 1
    for step in before:
        if step != "stories":
            assert after[step] == before[step], step
    assert finished.gate_prompts == 1, "the direction is not asked again"


def test_redo_stories_replaces_the_output_and_keeps_the_old_one(finished):
    folder = finished.run_folder()
    finished.stories_text = NEW_STORIES
    finished.run("--resume", str(folder), "--redo", "stories")

    assert (folder / "user-stories.md").read_text() == NEW_STORIES
    assert (folder / "user-stories.previous.md").read_text() == STORIES
    assert (folder / "product-spec.md").read_text() == SPEC, "earlier steps are untouched"
    assert not (folder / "product-spec.previous.md").exists()


def test_a_second_redo_replaces_the_previous_copy(finished):
    folder = finished.run_folder()
    finished.stories_text = NEW_STORIES
    finished.run("--resume", str(folder), "--redo", "stories")
    finished.stories_text = STORIES
    finished.run("--resume", str(folder), "--redo", "stories")

    assert (folder / "user-stories.previous.md").read_text() == NEW_STORIES
    assert (folder / "user-stories.md").read_text() == STORIES


def test_redo_spec_runs_the_spec_and_the_stories_again(finished):
    before = _calls(finished)
    folder = finished.run_folder()
    finished.run("--resume", str(folder), "--redo", "spec")

    after = _calls(finished)
    assert after["spec"] == before["spec"] + 1 and after["stories"] == before["stories"] + 1
    assert after["synthesis"] == before["synthesis"]
    assert (folder / "product-spec.previous.md").exists() and (folder / "user-stories.previous.md").exists()
    assert finished.gate_prompts == 1


def test_redo_synthesis_asks_the_direction_again(finished):
    before = _calls(finished)
    finished.run("--resume", str(finished.run_folder()), "--redo", "synthesis")

    after = _calls(finished)
    for step in ("synthesis", "spec", "stories"):
        assert after[step] == before[step] + 1, step
    assert after["research"] == before["research"] and after["feedback"] == before["feedback"]
    assert finished.gate_prompts == 2, "new proposals need a new choice"


def test_redo_research_runs_everything_after_it_again(finished):
    before = _calls(finished)
    finished.run("--resume", str(finished.run_folder()), "--redo", "research")

    after = _calls(finished)
    for step in ("research", "feedback", "synthesis", "spec", "stories"):
        assert after[step] == before[step] + 1, step
    assert after["pre_step"] == before["pre_step"], "the competitors and persona are kept"


# ── cost and bookkeeping ─────────────────────────────────────────────────────

def test_both_attempts_stay_in_the_metrics(finished):
    finished.run("--resume", str(finished.run_folder()), "--redo", "stories")
    steps = [row["step"] for row in finished.metric_rows()]
    assert steps.count("stories") == 2 and len(steps) == 6


def test_redo_stories_pushes_a_new_notion_database(finished):
    finished.run("--resume", str(finished.run_folder()), "--redo", "stories")
    assert finished.pushed == 2


def test_the_run_prints_what_will_run_again(finished, capsys):
    capsys.readouterr()
    finished.run("--resume", str(finished.run_folder()), "--redo", "stories")
    out = capsys.readouterr().out
    assert "Redoing stories: stories, notion will run again" in out
    assert "previous" in out


def test_a_failed_redo_can_be_resumed(finished):
    folder = finished.run_folder()
    finished.fail_at = "stories"
    with pytest.raises(RuntimeError):
        finished.run("--resume", str(folder), "--redo", "stories")
    assert not (folder / "user-stories.md").exists()
    assert (folder / "user-stories.previous.md").read_text() == STORIES

    finished.fail_at = None
    finished.stories_text = NEW_STORIES
    finished.run("--resume", str(folder))
    assert (folder / "user-stories.md").read_text() == NEW_STORIES


# ── what is refused ──────────────────────────────────────────────────────────

def test_redo_needs_resume(fake, capsys):
    with pytest.raises(SystemExit) as exit_info:
        fake.run("idea.md", "--redo", "stories")
    assert exit_info.value.code == 1
    assert "--resume" in capsys.readouterr().out
    assert sum(fake.calls.values()) == 0


@pytest.mark.parametrize("step", ["pre_step", "compress", "gate", "notion", "nonsense"])
def test_only_steps_with_an_output_can_be_redone(finished, step):
    with pytest.raises(SystemExit) as exit_info:
        finished.run("--resume", str(finished.run_folder()), "--redo", step)
    assert exit_info.value.code == 2


# ── the pieces ───────────────────────────────────────────────────────────────

def test_redo_clears_a_step_and_every_later_one(tmp_path):
    state = RunState.create(tmp_path, title="t")
    for step in _STEP_ORDER:
        state.complete(step)
    cleared = _redo(state, "synthesis")
    assert cleared == ["synthesis", "gate", "interview", "spec", "stories", "notion"]
    assert RunState.load(tmp_path).finished == ["pre_step", "research", "feedback", "compress"]


def test_forget_is_saved_and_ignores_unknown_steps(tmp_path):
    state = RunState.create(tmp_path, title="t")
    state.complete("a")
    state.complete("b", kept="value")
    state.forget(["b", "never-ran"])
    loaded = RunState.load(tmp_path)
    assert loaded.finished == ["a"]
    assert loaded.get("kept") == "value", "values stay; only the done mark goes"


def test_the_step_order_covers_every_file_written():
    assert set(orchestrator._STEP_FILES) <= set(_STEP_ORDER)
