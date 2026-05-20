#!/usr/bin/env python3
"""
Unit tests for search-related fixes in agent.py. No API calls, no cost.

Tests:
1. search_count counts server_tool_use blocks (not just tool_use)
2. max_tokens continuation strips web_search_tool_result blobs from stored messages
"""
import unittest
from unittest.mock import MagicMock, patch


def _text_block(text: str):
    """A block that has .text = str (like a real TextBlock)."""
    b = MagicMock(spec=["type", "text"])
    b.type = "text"
    b.text = text
    return b


def _other_block(type_: str, **kwargs):
    """A block with no .text attribute (search blocks, tool blocks, etc.)."""
    b = MagicMock(spec=["type"] + list(kwargs.keys()))
    b.type = type_
    for k, v in kwargs.items():
        setattr(b, k, v)
    return b


def _response(stop_reason: str, blocks: list):
    r = MagicMock()
    r.stop_reason = stop_reason
    r.content = blocks
    return r


class TestSearchCountFix(unittest.TestCase):

    def _run_single_response(self, blocks, stop_reason="end_turn"):
        """Run run_skill with a single mocked response and return the result."""
        from agent import run_skill
        resp = _response(stop_reason, blocks)
        with patch("agent.api_call_with_retry", return_value=resp), \
             patch("builtins.open", return_value=MagicMock(read=lambda: "# skill")):
            return run_skill("dummy", "msg", profile={"brief_mode": True}, step="research")

    def test_server_tool_use_is_counted(self):
        """server_tool_use (Anthropic's built-in search type) must be counted."""
        blocks = [
            _other_block("server_tool_use", name="web_search", input={"query": "q"}),
            _other_block("web_search_tool_result", content=[]),
            _text_block("analysis done"),
        ]
        result = self._run_single_response(blocks)
        self.assertEqual(result, "analysis done")

    def test_tool_use_still_counted(self):
        """Legacy tool_use blocks must also be counted for backwards compat."""
        blocks = [
            _other_block("tool_use", id="tu1", name="web_search", input={}),
            _text_block("result"),
        ]
        result = self._run_single_response(blocks)
        self.assertEqual(result, "result")


class TestSearchBlobStripping(unittest.TestCase):

    def test_search_blobs_stripped_on_max_tokens_continuation(self):
        """
        web_search_tool_result and server_tool_use blocks must NOT be carried
        into the continuation messages — their encrypted_content blobs are
        ~27k chars each and push the request over the 30k token/min rate limit.
        """
        from agent import run_skill

        # First response: model did a search then hit max_tokens mid-output
        server_use = _other_block("server_tool_use", name="web_search", input={"query": "q"})
        result_blob = _other_block("web_search_tool_result", content=[
            MagicMock(encrypted_content="A" * 27000)
        ])
        partial = _text_block("Based on research,")

        # Second response: clean continuation
        end_block = _text_block(" the market is competitive.")

        call_count = [0]
        continuation_messages = []

        def fake_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _response("max_tokens", [server_use, result_blob, partial])
            else:
                continuation_messages.extend(kwargs.get("messages", []))
                return _response("end_turn", [end_block])

        with patch("agent.client") as mock_client, \
             patch("builtins.open", return_value=MagicMock(read=lambda: "# skill")):
            mock_client.messages.create.side_effect = fake_create
            run_skill("dummy", "msg", profile={"brief_mode": False, "steps": {}}, step="research")

        # Verify two API calls were made (first + continuation)
        self.assertEqual(call_count[0], 2)

        # Find what was stored as the assistant message for continuation
        assistant_msgs = [m for m in continuation_messages if m.get("role") == "assistant"]
        self.assertTrue(len(assistant_msgs) > 0, "No assistant message stored for continuation")

        stored_blocks = assistant_msgs[0].get("content", [])
        stored_types = [getattr(b, "type", "?") for b in stored_blocks]

        self.assertNotIn("web_search_tool_result", stored_types,
            f"Encrypted search blobs were stored in continuation: {stored_types}")
        self.assertNotIn("server_tool_use", stored_types,
            f"server_tool_use stored in continuation: {stored_types}")

        # The partial text must still be there so the model can continue
        self.assertIn("text", stored_types,
            f"Partial text was lost from continuation context: {stored_types}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
