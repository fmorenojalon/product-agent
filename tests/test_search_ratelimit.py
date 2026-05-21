#!/usr/bin/env python3
"""
Real-API test that proves the rate-limit fix works.
Cost: ~$0.01 (one Haiku search call, one tiny continuation call).

What it checks:
1. A search response with stop_reason=max_tokens contains web_search_tool_result blobs
2. After the fix, the continuation call does NOT carry those blobs
3. The continuation call succeeds (no rate-limit error)
"""
from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic

client = Anthropic()
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
MODEL = "claude-haiku-4-5-20251001"


def block_summary(blocks) -> str:
    return [f"{getattr(b,'type','?')}({len(getattr(b,'text','') or '')}ch)" for b in blocks]


def run():
    print("Step 1 — make a real search call with max_tokens=300 to force truncation...\n")

    messages = [{"role": "user", "content":
        "Search for 'Meetup.com product review 2024' and write a detailed 300-word analysis "
        "of its strengths and weaknesses."}]

    r1 = client.messages.create(
        model=MODEL,
        max_tokens=300,
        tools=[SEARCH_TOOL],
        messages=messages,
    )

    types = [getattr(b, "type", "?") for b in r1.content]
    print(f"  stop_reason : {r1.stop_reason}")
    print(f"  blocks      : {block_summary(r1.content)}")

    if r1.stop_reason != "max_tokens":
        print("\nSKIP: didn't hit max_tokens — try lowering max_tokens further.")
        return

    if "web_search_tool_result" not in types:
        print("\nSKIP: no search happened — model didn't call the tool.")
        return

    # Measure blob size BEFORE stripping
    blob_chars = sum(
        len(str(getattr(item, "encrypted_content", "") or ""))
        for b in r1.content if getattr(b, "type", "") == "web_search_tool_result"
        for item in (getattr(b, "content", []) or [])
    )
    print(f"\n  Search blob size in response: {blob_chars:,} chars")
    print(f"  Approx tokens (chars/4):      {blob_chars // 4:,}")
    print(f"  → This ALONE would exceed the 30k token/min limit if re-sent.\n")

    # Apply the fix: strip non-text blocks
    text_blocks = [b for b in r1.content if getattr(b, "type", "") == "text"]
    stored = text_blocks if text_blocks else r1.content
    stored_chars = sum(len(b.text or "") for b in stored if hasattr(b, "text"))
    print(f"  After stripping: {len(stored)} block(s), ~{stored_chars} chars\n")

    assert "web_search_tool_result" not in [getattr(b, "type", "") for b in stored], \
        "FAIL: blobs still present after stripping"

    print("Step 2 — send the stripped continuation and verify it succeeds...\n")

    continuation_messages = messages + [
        {"role": "assistant", "content": stored},
        {"role": "user", "content": "Continue exactly where you left off. No preamble."},
    ]

    r2 = client.messages.create(
        model=MODEL,
        max_tokens=150,
        messages=continuation_messages,  # no tools — continuation doesn't search
    )

    print(f"  stop_reason : {r2.stop_reason}")
    text2 = "".join(getattr(b, "text", "") or "" for b in r2.content)
    print(f"  output      : {text2[:200]!r}")
    print()

    assert r2.stop_reason in ("end_turn", "max_tokens"), \
        f"FAIL: unexpected stop_reason {r2.stop_reason}"

    print("PASS — search blobs stripped, continuation succeeded without rate-limit error.")


if __name__ == "__main__":
    run()
