"""The compact story format: what the stories step is told, and that the result still reaches Notion."""

import re

import orchestrator
from connectors.notion import parse_stories
from orchestrator import _STORIES_FORMAT, run_stories

FORMAT = " ".join(_STORIES_FORMAT.split())  # one line, so the checks do not depend on wrapping

COMPACT = """\
## Epic 1: Release notes workflow

An epic summary of one sentence.

### Story 1: Connect a repository

As a product manager, I want to connect my GitHub repository, So that drafts can be generated from merged pull requests.

#### Background

Nothing can be drafted before the repository is connected.

#### Out of Scope

- GitLab and Bitbucket

Depends on: none
Assumption: one workspace has one repository in the first release.

#### Acceptance Criteria

**Connecting**

- Given a new user, When they click "Connect GitHub", Then they reach GitHub's consent page
- Given consent was given, When GitHub redirects back, Then the repository list is shown

**Failure**

- Given consent was declined, When GitHub redirects back, Then an error with a retry option is shown

### Story 2: Review a draft

As a product manager, I want to edit a draft, So that I publish what I approve.

Depends on: Story 1

#### Acceptance Criteria

**Editing**

- Given a draft, When the user edits a line, Then the change is kept
"""


# ── what the step is told ────────────────────────────────────────────────────

def test_the_format_keeps_the_headings_the_parser_needs():
    assert "`## Epic N: Title`" in FORMAT
    assert "`### Story N: Title`" in FORMAT
    assert "`#### Acceptance Criteria`" in FORMAT


def test_the_format_caps_the_acceptance_criteria():
    assert "At most 8 statements, each on one line" in FORMAT
    assert "at most 3 named groups" in FORMAT


def test_the_format_names_what_not_to_write():
    for section in ("intro table", "Notes", "Views", "Designs", "Tracking / Metrics", "Linked Stories"):
        assert section in FORMAT.split("Do not write")[1], section


def test_the_format_overrides_the_skill_and_asks_for_no_overview():
    assert "override the skill's own length and section rules" in FORMAT
    assert "no overview, no dependency map, no closing summary" in FORMAT


def test_the_format_puts_the_acceptance_criteria_last():
    """Everything before them becomes the Notion description, so nothing may follow them."""
    ac = FORMAT.index("`#### Acceptance Criteria` — last")
    for earlier in ("`#### Background`", "`#### Out of Scope`", "`Depends on:`", "`Assumption:`"):
        assert FORMAT.index(earlier) < ac, earlier


def test_the_stories_request_carries_the_format(monkeypatch):
    sent = []
    monkeypatch.setattr(orchestrator, "run_skill", lambda skill, message, **kw: sent.append(message) or ("", {}))
    run_stories("the spec", {}, full_scope=False)
    assert _STORIES_FORMAT in sent[0] and "ONE epic only" in sent[0]


def test_the_test_profile_sends_its_own_stub_and_not_the_format(monkeypatch):
    sent = []
    monkeypatch.setattr(orchestrator, "run_skill", lambda skill, message, **kw: sent.append(message) or ("", {}))
    run_stories("the spec", {"brief_mode": True})
    assert _STORIES_FORMAT not in sent[0]


# ── the result still reaches Notion ──────────────────────────────────────────

def test_a_compact_story_parses_into_its_epic_description_and_criteria():
    stories = parse_stories(COMPACT)
    assert [s["title"] for s in stories] == ["Story 1: Connect a repository", "Story 2: Review a draft"]
    assert {s["epic"] for s in stories} == {"Release notes workflow"}

    first = stories[0]
    for part in ("As a product manager", "Nothing can be drafted", "GitLab and Bitbucket",
                 "Depends on: none", "Assumption: one workspace"):
        assert part in first["description"], part
    assert "Acceptance Criteria" not in first["description"] and "Given" not in first["description"]


def test_the_acceptance_criteria_hold_only_the_criteria():
    first = parse_stories(COMPACT)[0]["acceptance_criteria"]
    assert first.count("Given") == 3
    assert "**Connecting**" in first and "**Failure**" in first
    for other in ("As a product manager", "Depends on", "Assumption", "Out of Scope", "### Story 2"):
        assert other not in first, other


def test_a_story_without_background_or_out_of_scope_parses():
    second = parse_stories(COMPACT)[1]
    assert second["description"].startswith("As a product manager, I want to edit a draft")
    assert "Depends on: Story 1" in second["description"]
    assert second["acceptance_criteria"].count("Given") == 1
