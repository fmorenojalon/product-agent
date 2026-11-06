"""The shape of what the pipeline sends: search cap, caching, streaming, token ceilings. No API calls."""

import pytest

import agent
import orchestrator
from agent import complete, run_skill
from tests.fakes import (
    make_response as _response, make_usage as _usage, results_block as _results,
    search_block as _search, stream_error, text_block as _text,
)

CACHE = {"type": "ephemeral"}


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n# Skill\n")
    return str(tmp_path)


def _profile(max_searches, **extra):
    return {"steps": {"research": {"model": "m", "max_tokens": 100, "max_searches": max_searches}}, **extra}


# ── the search cap is sent to the API ────────────────────────────────────────

@pytest.mark.parametrize("cap", [1, 5, 8])
def test_the_configured_search_cap_is_sent_as_max_uses(api, skill_dir, cap):
    api.responses = [_response("end_turn", _text("done"))]
    run_skill(skill_dir, "msg", profile=_profile(cap), step="research")
    assert api.requests[0]["tools"] == [{**agent.SEARCH_TOOL, "max_uses": cap}]


def test_zero_searches_offers_no_tools_and_no_caching(api, skill_dir):
    api.responses = [_response("end_turn", _text("done"))]
    run_skill(skill_dir, "msg", profile=_profile(0), step="research")
    assert "tools" not in api.requests[0] and "cache_control" not in api.requests[0]


def test_test_mode_offers_no_tools_and_no_caching(api, skill_dir):
    api.responses = [_response("end_turn", _text("done"))]
    run_skill(skill_dir, "msg", profile=_profile(5, brief_mode=True), step="research")
    assert "tools" not in api.requests[0] and "cache_control" not in api.requests[0]


# ── caching: search steps only ───────────────────────────────────────────────

def test_a_searching_step_turns_caching_on(api, skill_dir):
    api.responses = [_response("end_turn", _text("done"))]
    run_skill(skill_dir, "msg", profile=_profile(5), step="research")
    assert api.requests[0]["cache_control"] == CACHE


def test_direct_calls_are_not_cached(api):
    api.responses = [_response("end_turn", _text("done"))]
    orchestrator._llm([{"role": "user", "content": "x"}], step="compress",
                      profile={"steps": {"compress": {"model": "m", "max_tokens": 100}}})
    assert "cache_control" not in api.requests[0]


def test_caching_covers_resumed_rounds_but_not_a_continuation(api):
    """A continuation drops the tools, which changes the cached prefix: it could not be read."""
    tools = [{**agent.SEARCH_TOOL, "max_uses": 5}]
    api.responses = [
        _response("pause_turn", _search(), _results()),
        _response("max_tokens", _text("part one")),
        _response("end_turn", _text(" part two")),
    ]
    complete([{"role": "user", "content": "go"}], model="m", max_tokens=100, tools=tools, cache=True)
    first, resumed, continued = api.requests
    assert first["cache_control"] == CACHE and resumed["cache_control"] == CACHE
    assert "cache_control" not in continued and "tools" not in continued


def test_cache_tokens_reach_the_usage_totals(api):
    api.responses = [_response("end_turn", _text("done"), usage=_usage(10, 5, written=4000, read=9000))]
    _, usage = complete([{"role": "user", "content": "go"}], model="m", max_tokens=100)
    assert usage["cache_write_tokens"] == 4000 and usage["cache_read_tokens"] == 9000


# ── streaming ────────────────────────────────────────────────────────────────

def test_a_mid_stream_error_restarts_the_whole_request(api, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    api.responses = [stream_error("overloaded_error"), _response("end_turn", _text("done"))]
    text, _ = complete([{"role": "user", "content": "go"}], model="m", max_tokens=100)
    assert text == "done"
    assert len(api.requests) == 2
    assert api.requests[0]["messages"] == api.requests[1]["messages"]


# ── search count comes from what the API reports ─────────────────────────────

def test_search_count_uses_the_usage_the_api_reports(api):
    """Three search blocks, but only two ran: the third failed (over the cap) and is not billed."""
    api.responses = [_response(
        "end_turn", _search(), _results(), _search(), _results(), _search(), _results(), _text("done"),
        usage=_usage(searches=2),
    )]
    _, usage = complete([{"role": "user", "content": "go"}], model="m", max_tokens=100)
    assert usage["search_count"] == 2


def test_search_count_falls_back_to_counting_blocks_without_that_field(api):
    api.responses = [_response("end_turn", _search(), _results(), _text("done"))]
    _, usage = complete([{"role": "user", "content": "go"}], model="m", max_tokens=100)
    assert usage["search_count"] == 1


def test_search_count_is_summed_across_rounds(api):
    api.responses = [
        _response("pause_turn", _search(), _results(), usage=_usage(searches=3)),
        _response("end_turn", _text("done"), usage=_usage(searches=2)),
    ]
    _, usage = complete([{"role": "user", "content": "go"}], model="m", max_tokens=100,
                        tools=[agent.SEARCH_TOOL])
    assert usage["search_count"] == 5


# ── the token ceilings in config.yaml ────────────────────────────────────────

STEPS = ["pre_step", "compress", "research", "feedback", "synthesis", "spec", "stories"]


def test_test_profile_keeps_small_ceilings_and_no_search():
    profile = agent.load_profile("1")
    for step in STEPS:
        assert agent.step_max_tokens(step, profile) <= 400, step
        assert agent.step_max_searches(step, profile) == 0, step


@pytest.mark.parametrize("key", ["2", "3", "4"])
def test_real_profiles_leave_room_for_a_whole_document(key):
    """Ceilings above the expected outputs (about 7k, 9k and 12k tokens), so a normal
    document is finished in one request instead of being continued."""
    profile = agent.load_profile(key)
    for step in ("research", "feedback", "spec"):
        assert agent.step_max_tokens(step, profile) >= 16000, step
    assert agent.step_max_tokens("stories", profile) >= 32000
    assert agent.step_max_tokens("compress", profile) >= 1500


@pytest.mark.parametrize("key", ["2", "3", "4"])
def test_only_research_and_feedback_search(key):
    profile = agent.load_profile(key)
    for step in STEPS:
        searches = agent.step_max_searches(step, profile)
        assert (searches > 0) == (step in ("research", "feedback")), step
