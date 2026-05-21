#!/usr/bin/env python3
"""
Real-API smoke test for the Notion connector.
Writes 2 fixture stories to your actual Notion workspace.

Prerequisites:
  NOTION_TOKEN and NOTION_PARENT_PAGE_ID set in .env

Cost: ~$0.001 (one Haiku call to parse a tiny fixture)

What to check manually after running:
  - 2 rows appear in the Notion database
  - All fields populated: Name, Epic, Description, Acceptance Criteria, Status
"""
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FIXTURE_MARKDOWN = """
## Epic 1: Core Loop

### User Stories

#### Story 1.1: Post in community

| User Story | Files and Documentation |
|------------|------------------------|
| As a member, I can post text and images in a community feed. | Designs: TBD |

**Background**

Members need to share content to keep the community active.

**Acceptance Criteria**

- Post appears immediately in the feed.
- Other members can see it within 5 seconds.

**Linked Stories / Dependencies**

- Story 1.2

---

#### Story 1.2: Reply to a post

| User Story | Files and Documentation |
|------------|------------------------|
| As a member, I can reply to any post in a community. | Designs: TBD |

**Background**

Replies drive conversation and engagement within communities.

**Acceptance Criteria**

- Reply is threaded under the original post.
- Author of the original post is notified.
"""


@unittest.skipUnless(
    os.getenv("NOTION_TOKEN") and os.getenv("NOTION_PARENT_PAGE_ID"),
    "NOTION_TOKEN and NOTION_PARENT_PAGE_ID must be set in .env to run smoke tests",
)
class TestNotionSmoke(unittest.TestCase):

    def test_two_stories_written_to_notion(self):
        """Writes 2 fixture stories to a new Notion database without error."""
        from connectors.notion import push_stories

        db_name = f"smoke-test — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        push_stories(FIXTURE_MARKDOWN, db_name)
        # If no exception was raised, the write succeeded.
        # Verify the new database and 2 rows appeared in Notion by eye.

    def test_graceful_failure_on_bad_token(self):
        """Bad token must warn and return, not raise."""
        original = os.environ.get("NOTION_TOKEN")
        os.environ["NOTION_TOKEN"] = "secret_badtoken000000000000000000000000000000"
        try:
            from connectors.notion import push_stories
            push_stories(FIXTURE_MARKDOWN, f"smoke-bad-token — {datetime.now().strftime('%Y-%m-%d %H:%M')}")  # must not raise
        finally:
            if original:
                os.environ["NOTION_TOKEN"] = original
            else:
                del os.environ["NOTION_TOKEN"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
