"""How a response's text blocks become one text: no glued sentences, no split ones. No API calls."""

from agent import _text_of, complete
from tests.fakes import (
    make_response as _response, results_block as _results, search_block as _search, text_block as _text,
)


def _of(*blocks):
    return _text_of(_response("end_turn", *blocks))


def test_text_blocks_that_follow_each_other_join_as_they_are():
    """Citations split one sentence across blocks: no separator may be added inside it."""
    assert _of(_text("Release notes can be"), _text(" a pain, as one"), _text(" developer put it.")) == (
        "Release notes can be a pain, as one developer put it."
    )


def test_text_before_and_after_a_search_is_separated_by_a_blank_line():
    """The announcement before the searches must not run into the answer after them."""
    text = _of(
        _text("I'll run all the research searches in parallel to gather feedback on this product space."),
        _search(), _results(),
        _text("**Note on data scarcity:** Reddit returned very little."),
    )
    assert text == (
        "I'll run all the research searches in parallel to gather feedback on this product space."
        "\n\n**Note on data scarcity:** Reddit returned very little."
    )


def test_several_searches_in_a_row_make_one_separator():
    text = _of(_text("Searching."), _search(), _results(), _search(), _results(), _search(), _results(), _text("Done."))
    assert text == "Searching.\n\nDone."


def test_every_interruption_is_separated():
    text = _of(_text("One."), _search(), _results(), _text("Two."), _search(), _results(), _text("Three."))
    assert text == "One.\n\nTwo.\n\nThree."


def test_a_split_sentence_after_a_search_stays_whole():
    text = _of(_text("Plan."), _search(), _results(), _text("Beamer is"), _text(" a tool"), _text("."))
    assert text == "Plan.\n\nBeamer is a tool."


def test_blocks_before_the_first_text_add_nothing():
    assert _of(_search(), _results(), _text("Answer.")) == "Answer."


def test_blocks_after_the_last_text_add_nothing():
    assert _of(_text("Answer."), _search(), _results()) == "Answer."


def test_no_text_gives_an_empty_string():
    assert _of(_search(), _results()) == ""


def test_complete_returns_the_separated_text(api):
    api.responses = [_response(
        "end_turn", _text("Announcing."), _search(), _results(), _text("The report."),
    )]
    text, _ = complete([{"role": "user", "content": "x"}], model="m", max_tokens=100)
    assert text == "Announcing.\n\nThe report."


# ── how the rounds of one answer are joined ──────────────────────────────────

def _answer(*responses, api):
    api.responses = list(responses)
    text, _ = complete([{"role": "user", "content": "x"}], model="m", max_tokens=100)
    return text


def test_a_cut_inside_a_word_is_continued_without_a_break(api):
    text = _answer(
        _response("max_tokens", _text("Half a re")),
        _response("end_turn", _text("port and the rest")),
        api=api,
    )
    assert text == "Half a report and the rest"


def test_a_cut_inside_a_table_row_is_continued_without_a_break(api):
    text = _answer(
        _response("max_tokens", _text("| Beamer | $49 | Yes |\n| LaunchN")),
        _response("end_turn", _text("otes | $249 | No |\n")),
        api=api,
    )
    assert text == "| Beamer | $49 | Yes |\n| LaunchNotes | $249 | No |\n"


def test_several_cuts_add_nothing_between_any_of_the_pieces(api):
    text = _answer(
        _response("max_tokens", _text("one")),
        _response("max_tokens", _text("two")),
        _response("end_turn", _text("three")),
        api=api,
    )
    assert text == "onetwothree"


def test_a_resumed_pause_is_joined_with_a_newline(api):
    text = _answer(
        _response("pause_turn", _text("Before the pause."), _search(), _results()),
        _response("end_turn", _text("After it.")),
        api=api,
    )
    assert text == "Before the pause.\nAfter it."


def test_a_round_with_no_text_adds_no_separator(api):
    text = _answer(
        _response("max_tokens", _search(), _results()),
        _response("end_turn", _text("The whole answer.")),
        api=api,
    )
    assert text == "The whole answer."


def test_a_pause_then_a_cut_then_the_end(api):
    text = _answer(
        _response("pause_turn", _text("Searching.")),
        _response("max_tokens", _text("The repo")),
        _response("end_turn", _text("rt body")),
        api=api,
    )
    assert text == "Searching.\nThe report body"


def test_a_pause_before_any_text_leaves_no_leading_newline(api):
    """A turn can pause while it is still searching, before it has written anything."""
    text = _answer(
        _response("pause_turn", _search(), _results()),
        _response("end_turn", _text("The answer.")),
        api=api,
    )
    assert text == "The answer."
