#!/usr/bin/env python3
"""
Test that the continuation loop prevents truncation.
Forces multiple continuation rounds by using a very low max_tokens ceiling.
Uses Haiku to keep cost under $0.01.
"""
from dotenv import load_dotenv
load_dotenv()

from agent import client, api_call_with_retry

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 80  # artificially low — forces multiple continuation rounds


def run_with_continuation(prompt: str) -> tuple[str, int]:
    messages = [{"role": "user", "content": prompt}]
    accumulated: list[str] = []
    rounds = 0

    for _ in range(20):
        rounds += 1
        response = api_call_with_retry(
            lambda: client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, messages=messages)
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        if text:
            accumulated.append(text)

        print(f"  Round {rounds}: stop_reason={response.stop_reason!r}  chars={len(text)}")

        if response.stop_reason == "end_turn":
            break
        elif response.stop_reason == "max_tokens":
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": "Continue exactly where you left off. No preamble."})
        else:
            break

    return "\n".join(accumulated), rounds


def main():
    prompt = (
        "Write a numbered list of exactly 10 product features for a local community app. "
        "Each item: one sentence only. Number them 1 through 10. "
        "Do not stop until all 10 are written."
    )

    print(f"Running continuation test (max_tokens={MAX_TOKENS} to force multiple rounds)...\n")
    result, rounds = run_with_continuation(prompt)

    print(f"\n{'─'*60}")
    print(result)
    print(f"{'─'*60}")

    # Verify all 10 items are present
    found = [i for i in range(1, 11) if f"{i}." in result or f"{i})" in result]
    missing = [i for i in range(1, 11) if i not in found]

    print(f"\nRounds used   : {rounds}")
    print(f"Items found   : {found}")
    if missing:
        print(f"Items MISSING : {missing}")
        print("FAIL — truncation not resolved")
    else:
        print("PASS — all 10 items present, continuation working correctly")


if __name__ == "__main__":
    main()
