"""Reading the pre-step's reply: the model may wrap its JSON in a fence, a preface or a closing note."""

import pytest

from agent import parse_json
from orchestrator import extract_competitors_and_persona
from tests.fakes import make_response as _response, text_block as _text

OBJECT = '{"competitors": ["Asana", "Linear", "Monday.com"], "persona": "project manager"}'
PRETTY = '{\n  "competitors": ["Asana", "Linear", "Monday.com"],\n  "persona": "project manager"\n}'
PROFILE = {"steps": {"pre_step": {"model": "m", "max_tokens": 512, "max_searches": 0}}}


@pytest.mark.parametrize("reply", [
    OBJECT,
    PRETTY,
    f"```json\n{OBJECT}\n```",
    f"```json\n{PRETTY}\n```\n\nNote: these are the three closest products.",
    f"{OBJECT}\n\nThese are the closest competitors.",
    f"Here is the JSON:\n\n```json\n{OBJECT}\n```",
    f"Using {{the idea}} as a guide:\n{OBJECT}",
    f"{OBJECT}\n{OBJECT}",
])
def test_the_first_object_is_read_whatever_surrounds_it(reply):
    assert parse_json(reply) == {
        "competitors": ["Asana", "Linear", "Monday.com"], "persona": "project manager",
    }


@pytest.mark.parametrize("reply", ["", "no json here", '{"competitors": ["Asana"', "[1, 2, 3]"])
def test_a_reply_without_an_object_raises_and_shows_the_reply(reply):
    with pytest.raises(ValueError) as error:
        parse_json(reply)
    assert reply in str(error.value)


def test_the_pre_step_returns_competitors_and_persona(api):
    api.responses = [_response("end_turn", _text(f"```json\n{OBJECT}\n```\n\nNote: done."))]
    assert extract_competitors_and_persona("idea", PROFILE) == (
        ["Asana", "Linear", "Monday.com"], "project manager",
    )


@pytest.mark.parametrize("reply", [
    '{"competitors": ["Asana", "Linear", "Monday.com"]}',
    '{"persona": "project manager"}',
    '{"competitors": "Asana", "persona": "project manager"}',
    '{"competitors": ["Asana"], "persona": ["project manager"]}',
])
def test_a_reply_missing_a_field_stops_with_the_reply_shown(api, reply):
    api.responses = [_response("end_turn", _text(reply))]
    with pytest.raises(ValueError) as error:
        extract_competitors_and_persona("idea", PROFILE)
    assert "competitors" in str(error.value) and reply in str(error.value)
