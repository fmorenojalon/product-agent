"""Stop-reason handling: agent.complete, run_skill and orchestrator._llm. No API calls, no cost."""

from types import SimpleNamespace

import pytest

import agent
import orchestrator
from agent import StopReasonError, complete, run_skill
from tests.fakes import (
    make_response as _response, make_usage as _usage, results_block as _results,
    search_block as _search, text_block as _text,
)

TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]


def call(**kwargs):
    return complete([{"role": "user", "content": "go"}], model="m", max_tokens=100, step="research", **kwargs)


# ── end_turn ─────────────────────────────────────────────────────────────────

def test_end_turn_returns_the_text_and_usage(api):
    api.responses = [_response("end_turn", _text("done"), usage=_usage(10, 5, 3, 7))]
    text, usage = call()
    assert text == "done"
    assert usage == {
        "input_tokens": 10, "output_tokens": 5,
        "cache_write_tokens": 3, "cache_read_tokens": 7, "search_count": 0,
    }
    assert len(api.requests) == 1


def test_blank_answer_raises(api):
    api.responses = [_response("end_turn", _search(), _results())]
    with pytest.raises(StopReasonError, match="no text"):
        call(tools=TOOLS)


# ── max_tokens ───────────────────────────────────────────────────────────────

def test_max_tokens_continues_without_tools_or_search_blobs(api):
    api.responses = [
        _response("max_tokens", _search(), _results(), _text("Part one,")),
        _response("end_turn", _text(" part two.")),
    ]
    text, usage = call(tools=TOOLS)

    assert "Part one," in text and text.endswith("part two.")
    assert usage["input_tokens"] == 200 and usage["output_tokens"] == 100
    first, second = api.requests
    assert first["tools"] == TOOLS
    assert "tools" not in second
    assert [b.type for b in second["messages"][1]["content"]] == ["text"]
    assert second["messages"][2] == {"role": "user", "content": agent._CONTINUE_PROMPT}


# ── pause_turn ───────────────────────────────────────────────────────────────

def test_pause_turn_resumes_the_same_turn_with_tools(api):
    paused = [_text("Searching."), _search(), _results()]
    api.responses = [
        _response("pause_turn", *paused, usage=_usage(100, 20)),
        _response("end_turn", _text("Final answer."), usage=_usage(300, 40)),
    ]
    text, usage = call(tools=TOOLS)

    assert text.endswith("Final answer.")
    assert len(api.requests) == 2
    resumed = api.requests[1]
    assert resumed["tools"] == TOOLS
    assert resumed["messages"][-1] == {"role": "assistant", "content": paused}, "sent back unchanged"
    assert usage["input_tokens"] == 400 and usage["output_tokens"] == 60
    assert usage["search_count"] == 1


# ── refusal and everything unexpected ────────────────────────────────────────

def test_refusal_raises_with_its_category_and_stops(api):
    api.responses = [_response(
        "refusal", _text("partial"),
        stop_details=SimpleNamespace(category="cyber", explanation="blocked by policy"),
    )]
    with pytest.raises(StopReasonError) as raised:
        call()
    assert raised.value.stop_reason == "refusal"
    assert raised.value.step == "research"
    assert "cyber" in str(raised.value) and "blocked by policy" in str(raised.value)
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    "reason", ["tool_use", "stop_sequence", "model_context_window_exceeded", "a_reason_added_later"]
)
def test_unexpected_stop_reasons_raise_instead_of_returning_partial_text(api, reason):
    api.responses = [_response(reason, _text("partial text"))]
    with pytest.raises(StopReasonError) as raised:
        call()
    assert raised.value.stop_reason == reason
    assert len(api.requests) == 1


def test_running_out_of_rounds_raises(api, monkeypatch):
    monkeypatch.setattr(agent, "_MAX_ROUNDS", 3)
    api.responses = [_response("pause_turn", _search()) for _ in range(3)]
    with pytest.raises(StopReasonError, match="no final answer after 3 rounds"):
        call(tools=TOOLS)
    assert len(api.requests) == 3


# ── run_skill goes through the same loop ─────────────────────────────────────

PROFILE = {"steps": {"research": {"model": "m", "max_tokens": 100, "max_searches": 5}}}


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n# Skill\n")
    return str(tmp_path)


def test_run_skill_sends_the_skill_as_system_prompt(api, skill_dir):
    api.responses = [_response("end_turn", _text("done"))]
    run_skill(skill_dir, "msg", profile=PROFILE, step="research")
    request = api.requests[0]
    assert request["system"].startswith("# Skill")
    assert request["model"] == "m" and request["max_tokens"] == 100


def test_run_skill_resumes_a_paused_search(api, skill_dir):
    api.responses = [
        _response("pause_turn", _text("Searching."), _search(), _results()),
        _response("end_turn", _text("Report.")),
    ]
    text, usage = run_skill(skill_dir, "msg", profile=PROFILE, step="research")
    assert text.endswith("Report.")
    assert usage["search_count"] == 1
    assert api.requests[1]["tools"] == api.requests[0]["tools"]


def test_run_skill_raises_on_refusal(api, skill_dir):
    api.responses = [_response("refusal", stop_details=SimpleNamespace(category="bio", explanation=""))]
    with pytest.raises(StopReasonError, match="bio"):
        run_skill(skill_dir, "msg", profile=PROFILE, step="research")


# ── direct calls (_llm) go through it too ────────────────────────────────────

LLM_PROFILE = {"steps": {"compress": {"model": "m", "max_tokens": 800}}}


def test_llm_completes_an_answer_that_hit_max_tokens(api):
    api.responses = [_response("max_tokens", _text("- fact one")), _response("end_turn", _text("\n- fact two"))]
    text, usage = orchestrator._llm(
        [{"role": "user", "content": "compress"}], step="compress", profile=LLM_PROFILE
    )
    assert "fact one" in text and "fact two" in text
    assert usage["output_tokens"] == 100 and usage["search_count"] == 0
    assert all("tools" not in r for r in api.requests)


def test_llm_raises_on_refusal(api):
    api.responses = [_response("refusal", stop_details=SimpleNamespace(category="cyber", explanation=""))]
    with pytest.raises(StopReasonError):
        orchestrator._llm([{"role": "user", "content": "x"}], step="compress", profile=LLM_PROFILE)
