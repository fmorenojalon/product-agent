"""Resume tests: run the real orchestrator.main() against a fake API, stop it, resume it.

No API calls, no cost. The fake counts every model call, so these tests can show that a
resumed run repeats no step that already finished.
"""

import builtins
import json
import sys
from collections import Counter

import pytest

import orchestrator

IDEA = "# Idea\n\nA meeting-to-task tool for project managers."

RESEARCH = "## Research\n\n" + "competitor analysis " * 20
FEEDBACK = "## Feedback\n\n" + "user quotes " * 20
PROPOSALS = "## **Option 1 — Alpha**\n\ntext\n\n## **Option 2 — Beta**\n\ntext"
SPEC = "## Spec\n\n" + "requirement " * 60
STORIES = "## Epic 1: Epic\n\n### Story 1: Story\n\ntext"
BAD_STORIES = "no story headers in here"
USAGE = {
    "input_tokens": 100, "output_tokens": 50,
    "cache_write_tokens": 0, "cache_read_tokens": 0, "search_count": 0,
}

# Model calls one clean run makes, per step (compress runs once for research, once for feedback)
CLEAN_CALLS = {
    "pre_step": 1, "research": 1, "feedback": 1, "compress": 2,
    "synthesis": 1, "spec": 1, "stories": 1,
}
STEP_FILES = {
    "research": "research-brief.md", "feedback": "feedback-synthesis.md",
    "synthesis": "proposals.md", "spec": "product-spec.md", "stories": "user-stories.md",
}


class FakeApi:
    """Stands in for every model call, prompt and connector the pipeline touches."""

    def __init__(self, monkeypatch, tmp_path):
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.calls = Counter()
        self.fail_at: str | None = None
        self.stories_text = STORIES
        self.gate_prompts = 0
        self.pushed = 0
        self.quality_continue = False
        self.changed_doc_answer = "y"
        self.sleeps: list[float] = []

    # model calls
    def _step(self, step: str, text: str):
        self.calls[step] += 1
        if step == self.fail_at:
            raise RuntimeError(f"API down during {step}")
        return text, dict(USAGE)

    def run_skill(self, skill_path, user_message, extra_context="", profile=None, step=""):
        texts = {"research": RESEARCH, "feedback": FEEDBACK, "spec": SPEC, "stories": self.stories_text}
        return self._step(step, texts[step])

    def llm(self, messages, step="", profile=None):
        texts = {
            "pre_step": json.dumps({"competitors": ["A", "B", "C"], "persona": "project manager"}),
            "compress": "- dense summary",
            "synthesis": PROPOSALS,
        }
        return self._step(step, texts[step])

    # prompts and connectors
    def input(self, prompt=""):
        if "Which direction" in prompt:
            self.gate_prompts += 1
            return "2"
        if "changed document" in prompt:
            return self.changed_doc_answer
        raise AssertionError(f"unexpected prompt: {prompt!r}")

    def prompt_quality_failure(self, step, result, output_preview=""):
        return self.quality_continue

    def push_stories(self, stories, db_name):
        self.pushed += 1

    # driving the CLI
    def run(self, *argv):
        self.monkeypatch.setattr(sys, "argv", ["orchestrator.py", *argv])
        orchestrator.main()

    def run_folder(self):
        (folder,) = (self.tmp_path / "output").iterdir()
        return folder

    def metric_rows(self):
        lines = (self.run_folder() / "run-metrics.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "idea.md").write_text(IDEA)
    api = FakeApi(monkeypatch, tmp_path)
    monkeypatch.setattr(orchestrator, "run_skill", api.run_skill)
    monkeypatch.setattr(orchestrator, "_llm", api.llm)
    monkeypatch.setattr(orchestrator, "push_stories", api.push_stories)
    monkeypatch.setattr(orchestrator, "prompt_quality_failure", api.prompt_quality_failure)
    monkeypatch.setattr(orchestrator, "select_profile", lambda: {**orchestrator.load_profile("2"), "key": "2"})
    monkeypatch.setattr(orchestrator, "choose_mode", lambda brief: False)
    monkeypatch.setattr(orchestrator, "choose_story_scope", lambda: True)
    monkeypatch.setattr(builtins, "input", api.input)
    monkeypatch.setattr("time.sleep", api.sleeps.append)
    return api


# ── The requirement: kill at any step, resume repeats nothing finished ───────

@pytest.mark.parametrize("fail_at", list(CLEAN_CALLS))
def test_resume_repeats_no_finished_step(fake, fail_at):
    fake.fail_at = fail_at
    with pytest.raises(RuntimeError, match=fail_at):
        fake.run("idea.md")
    folder = fake.run_folder()

    # Everything finished before the failure is already on disk
    order = list(CLEAN_CALLS)
    for step, filename in STEP_FILES.items():
        finished_before = order.index(step) < order.index(fail_at)
        assert (folder / filename).exists() == finished_before, (step, filename)

    fake.fail_at = None
    fake.run("--resume", str(folder))

    for step, clean in CLEAN_CALLS.items():
        expected = clean + (1 if step == fail_at else 0)  # the failed attempt was paid once
        assert fake.calls[step] == expected, f"{step}: {fake.calls[step]} calls, expected {expected}"
    assert fake.gate_prompts == 1, "the direction choice must not be asked twice"
    assert fake.pushed == 1
    for filename in STEP_FILES.values():
        assert (folder / filename).exists()
    assert len(fake.metric_rows()) == 5, "one metrics row per tracked step, none lost or doubled"


def test_failure_prints_the_resume_command(fake, capsys):
    fake.fail_at = "spec"
    with pytest.raises(RuntimeError):
        fake.run("idea.md")
    out = capsys.readouterr().out
    assert f"--resume output/{fake.run_folder().name}" in out  # relative: pasteable from the repo root


def test_the_pipeline_never_pauses_between_steps(fake):
    """No fixed cooldown: waiting is left to the retry policy, which only waits when the API says so."""
    fake.run("idea.md")
    assert fake.sleeps == []


def test_metrics_of_finished_steps_survive_a_failure(fake):
    fake.fail_at = "stories"
    with pytest.raises(RuntimeError):
        fake.run("idea.md")
    assert [row["step"] for row in fake.metric_rows()] == ["research", "feedback", "synthesis", "spec"]
    assert "TOTAL" in (fake.run_folder() / "run-report.md").read_text()


def test_resume_of_a_completed_run_calls_nothing(fake):
    fake.run("idea.md")
    folder = fake.run_folder()
    calls_after_first_run = dict(fake.calls)

    fake.run("--resume", str(folder))

    assert dict(fake.calls) == calls_after_first_run
    assert fake.gate_prompts == 1
    assert fake.pushed == 1, "resuming must not create a second Notion database"


# ── Declining a quality check ────────────────────────────────────────────────

def test_declined_quality_check_saves_the_work_and_resume_reruns_the_step(fake):
    fake.stories_text = BAD_STORIES
    with pytest.raises(SystemExit) as exit_info:
        fake.run("idea.md")
    assert exit_info.value.code == 1
    folder = fake.run_folder()

    assert (folder / "stories.rejected.md").read_text() == BAD_STORIES
    assert not (folder / "user-stories.md").exists()
    for filename in ("research-brief.md", "feedback-synthesis.md", "proposals.md", "product-spec.md"):
        assert (folder / filename).exists()
    rows = fake.metric_rows()
    assert rows[-1]["step"] == "stories" and rows[-1]["quality"]["user_continued"] is False

    fake.stories_text = STORIES
    fake.run("--resume", str(folder))

    assert fake.calls["stories"] == 2 and fake.calls["spec"] == 1
    assert (folder / "user-stories.md").read_text() == STORIES
    rows = fake.metric_rows()
    assert [r["step"] for r in rows].count("stories") == 2, "both paid attempts are in the totals"
    assert "⚠" in (folder / "run-report.md").read_text()


# ── Resume inputs ────────────────────────────────────────────────────────────

def test_resume_unknown_folder_exits_cleanly(fake, capsys):
    with pytest.raises(SystemExit) as exit_info:
        fake.run("--resume", "output/does-not-exist")
    assert exit_info.value.code == 1
    assert "nothing to resume" in capsys.readouterr().out


def test_changed_idea_document_is_flagged_and_can_stop_the_resume(fake, tmp_path, capsys):
    fake.fail_at = "spec"
    with pytest.raises(RuntimeError):
        fake.run("idea.md")
    folder = fake.run_folder()
    calls_before = dict(fake.calls)

    (tmp_path / "idea.md").write_text(IDEA + "\nA new paragraph.")
    fake.fail_at = None
    fake.changed_doc_answer = "n"
    with pytest.raises(SystemExit):
        fake.run("--resume", str(folder))

    assert "has changed" in capsys.readouterr().out
    assert dict(fake.calls) == calls_before


def test_changed_idea_document_can_be_accepted(fake, tmp_path):
    fake.fail_at = "spec"
    with pytest.raises(RuntimeError):
        fake.run("idea.md")
    folder = fake.run_folder()

    (tmp_path / "idea.md").write_text(IDEA + "\nA new paragraph.")
    fake.fail_at = None
    fake.run("--resume", str(folder))  # answers "y"
    fake.run("--resume", str(folder))  # hash was refreshed: no second warning, so no prompt

    assert (folder / "user-stories.md").exists()


# ── Run folders ──────────────────────────────────────────────────────────────

def test_runs_started_in_the_same_minute_get_separate_folders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = orchestrator._new_run_folder("My Idea", "2026-11-06_10-00")
    first.mkdir(parents=True)
    second = orchestrator._new_run_folder("My Idea", "2026-11-06_10-00")
    assert first.name == "2026-11-06_10-00_my-idea"
    assert second.name == "2026-11-06_10-00_my-idea-2"
