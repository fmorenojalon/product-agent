"""What the later steps read: the full reports (default) or summaries, and the direction the user chose.

Pipeline tests reuse the fake model of test_resume.py, which records what every step is sent.
No API calls, no cost.
"""

import pytest

import agent
import orchestrator
from agent import complete
from orchestrator import _context_mode, _direction_section, compress
from tests.fakes import make_response as _response, text_block as _text
from tests.test_resume import FEEDBACK, PROPOSALS, RESEARCH, fake  # noqa: F401  (fixture)


def _sent(fake, step):
    (text,) = [text for name, text in fake.sent if name == step]
    return text


# ── full mode: both reports reach every step that reads them ─────────────────

def test_full_mode_sends_both_reports_unchanged(fake):
    fake.run("idea.md")
    for step in ("synthesis", "spec"):
        text = _sent(fake, step)
        assert RESEARCH in text and FEEDBACK in text, step


def test_full_mode_makes_no_summary(fake):
    fake.run("idea.md")
    folder = fake.run_folder()
    assert fake.calls["compress"] == 0
    assert not (folder / "research-summary.md").exists()
    assert not (folder / "feedback-summary.md").exists()


def test_full_mode_reads_the_reports_from_disk_on_resume(fake):
    """An edited report reaches the spec when the run is resumed."""
    fake.fail_at = "spec"
    with pytest.raises(RuntimeError):
        fake.run("idea.md")
    folder = fake.run_folder()
    (folder / "research-brief.md").write_text("## Research\n\nEdited by hand: a new competitor.")

    fake.fail_at = None
    fake.run("--resume", str(folder))

    (spec_text,) = [text for step, text in fake.sent if step == "spec"][-1:]
    assert "Edited by hand: a new competitor." in spec_text


def test_the_test_profile_takes_the_same_path(fake, monkeypatch):
    """Profile 1 reads the reports as they are, like every profile with the default mode."""
    monkeypatch.setattr(orchestrator, "select_profile", lambda: {**orchestrator.load_profile("1"), "key": "1"})
    fake.run("idea.md")
    assert fake.calls["compress"] == 0
    assert RESEARCH in _sent(fake, "spec")


# ── the direction the user chose ─────────────────────────────────────────────

def test_the_spec_is_sent_the_proposals_and_the_choice(fake):
    fake.run("idea.md")  # the fake user answers "2" at the gate
    text = _sent(fake, "spec")
    assert PROPOSALS in text
    assert 'The user chose: "2"' in text


def test_the_choice_is_not_only_a_bare_number(fake):
    fake.run("idea.md")
    text = _sent(fake, "spec")
    assert "option with that number" in text
    assert "recommendation in the proposals for another option does not apply" in text


def test_a_described_choice_is_passed_as_written():
    section = _direction_section(PROPOSALS, "Option 2 but priced lower")
    assert 'The user chose: "Option 2 but priced lower"' in section
    assert PROPOSALS in section


def test_no_answer_falls_back_to_the_recommended_direction():
    section = _direction_section(PROPOSALS, "")
    assert "The user gave no answer" in section
    assert "The user chose" not in section


def test_the_interview_is_sent_the_proposals_and_the_choice(monkeypatch):
    sent = []

    def llm(messages, step="", profile=None, stop_at_ceiling=False):
        sent.append(messages[0]["content"])
        return "1. What is the monthly active user goal?", {}

    monkeypatch.setattr(orchestrator, "_llm", llm)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    orchestrator.run_interactive_interview("idea", "RESEARCH", "FEEDBACK", PROPOSALS, "2", {})

    assert PROPOSALS in sent[0] and 'The user chose: "2"' in sent[0]
    assert "RESEARCH" in sent[0] and "FEEDBACK" in sent[0]


# ── summary mode ─────────────────────────────────────────────────────────────

@pytest.fixture
def summary(fake):
    fake.context_mode = "summary"
    return fake


def test_summary_mode_sends_summaries_not_the_reports(summary):
    summary.run("idea.md")
    for step in ("synthesis", "spec"):
        text = _sent(summary, step)
        assert "- dense summary" in text, step
        assert RESEARCH not in text and FEEDBACK not in text, step


def test_summary_mode_tells_the_step_it_reads_a_summary(summary):
    summary.run("idea.md")
    text = _sent(summary, "spec")
    assert "short summary of the full competitive research report" in text
    assert "short summary of the full user feedback synthesis" in text


def test_summaries_are_saved_as_files_and_not_in_the_run_state(summary):
    summary.run("idea.md")
    folder = summary.run_folder()
    assert (folder / "research-summary.md").read_text() == "- dense summary"
    assert (folder / "feedback-summary.md").read_text() == "- dense summary"
    assert "dense summary" not in (folder / "run-state.json").read_text()


def test_summary_mode_prints_the_size_of_each_summary(summary, capsys):
    summary.run("idea.md")
    out = capsys.readouterr().out
    assert "Summaries ready: research 3 words" in out and "feedback 3 words" in out


def test_summary_mode_makes_one_request_per_summary(summary):
    summary.run("idea.md")
    assert summary.calls["compress"] == 2


def test_a_resumed_run_reuses_the_saved_summaries(summary):
    summary.fail_at = "spec"
    with pytest.raises(RuntimeError):
        summary.run("idea.md")
    folder = summary.run_folder()
    summary.fail_at = None

    summary.run("--resume", str(folder))

    assert summary.calls["compress"] == 2, "summaries are not paid for twice"
    (spec_text,) = [text for step, text in summary.sent if step == "spec"][-1:]
    assert "- dense summary" in spec_text


def test_missing_summary_files_are_made_again(summary):
    summary.fail_at = "spec"
    with pytest.raises(RuntimeError):
        summary.run("idea.md")
    folder = summary.run_folder()
    (folder / "feedback-summary.md").unlink()
    summary.fail_at = None

    summary.run("--resume", str(folder))

    assert summary.calls["compress"] == 4
    assert (folder / "feedback-summary.md").exists()


def test_the_test_profile_summarises_in_summary_mode(summary, monkeypatch):
    monkeypatch.setattr(orchestrator, "select_profile", lambda: {**orchestrator.load_profile("1"), "key": "1"})
    summary.run("idea.md")
    assert summary.calls["compress"] == 2


# ── a summary is one bounded request ─────────────────────────────────────────

def test_a_cut_answer_is_kept_not_continued_with_stop_at_ceiling(api):
    api.responses = [_response("max_tokens", _text("a summary that ran lon"))]
    text, usage = complete(
        [{"role": "user", "content": "x"}], model="m", max_tokens=100, stop_at_ceiling=True,
    )
    assert text == "a summary that ran lon"
    assert len(api.requests) == 1
    assert usage["output_tokens"] > 0


def test_a_cut_answer_is_still_continued_by_default(api):
    api.responses = [
        _response("max_tokens", _text("part one, ")),
        _response("end_turn", _text("part two")),
    ]
    text, _ = complete([{"role": "user", "content": "x"}], model="m", max_tokens=100)
    assert text == "part one, part two"
    assert len(api.requests) == 2


def test_compress_is_one_bounded_request(api):
    api.responses = [_response("max_tokens", _text("- cut at the ceiling"))]
    profile = {"steps": {"compress": {"model": "m", "max_tokens": 1500}}}
    assert compress("a long report", "competitive research report", profile) == "- cut at the ceiling"
    assert len(api.requests) == 1
    assert api.requests[0]["max_tokens"] == 1500


def test_other_direct_calls_are_still_completed(api):
    api.responses = [
        _response("max_tokens", _text("1. First, ")),
        _response("end_turn", _text("2. Second")),
    ]
    text, _ = orchestrator._llm(
        [{"role": "user", "content": "x"}], step="synthesis",
        profile={"steps": {"synthesis": {"model": "m", "max_tokens": 100}}},
    )
    assert "2. Second" in text and len(api.requests) == 2


# ── the setting ──────────────────────────────────────────────────────────────

def test_the_default_is_full():
    assert _context_mode({}) == "full"


@pytest.mark.parametrize("mode", ["full", "summary"])
def test_known_modes_are_accepted(mode):
    assert _context_mode({"context_mode": mode}) == mode


@pytest.mark.parametrize("mode", ["Full", "short", "", None])
def test_an_unknown_mode_is_an_error(mode):
    with pytest.raises(ValueError, match="context_mode must be one of full, summary"):
        _context_mode({"context_mode": mode})


def test_a_bad_mode_stops_the_run_before_any_model_call(fake):
    fake.context_mode = "short"
    with pytest.raises(ValueError, match="context_mode"):
        fake.run("idea.md")
    assert sum(fake.calls.values()) == 0


def test_every_profile_in_config_sets_a_known_mode_and_defaults_to_full():
    profiles = agent.CONFIG["profiles"]
    assert profiles
    for key, profile in profiles.items():
        assert profile.get("context_mode") == "full", f"profile {key}"
