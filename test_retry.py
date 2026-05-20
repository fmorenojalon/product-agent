#!/usr/bin/env python3
"""
Tests for api_call_with_retry. Uses mocks — no API calls, no cost.
"""
import time
import unittest
from unittest.mock import patch, MagicMock

import httpx
import anthropic
from agent import api_call_with_retry


def _rate_limit_error() -> anthropic.RateLimitError:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429
    response.headers = {}
    return anthropic.RateLimitError("rate limit", response=response, body={})


class TestApiCallWithRetry(unittest.TestCase):

    def test_succeeds_on_first_try(self):
        fn = MagicMock(return_value="ok")
        with patch("time.sleep"):
            result = api_call_with_retry(fn)
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 1)

    def test_retries_after_rate_limit_and_succeeds(self):
        """Fails twice with 429, succeeds on third attempt."""
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _rate_limit_error()
            return "ok"

        with patch("time.sleep") as mock_sleep:
            result = api_call_with_retry(flaky, max_retries=5)

        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # slept before attempt 2 and 3

    def test_wait_is_around_65_to_85_seconds(self):
        """Each retry waits 65–85s (past the 60s rate-limit window)."""
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _rate_limit_error()
            return "ok"

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            api_call_with_retry(flaky, max_retries=5)

        for wait in sleep_calls:
            self.assertGreaterEqual(wait, 65, f"wait {wait}s is below the 60s window")
            self.assertLessEqual(wait, 85, f"wait {wait}s is unexpectedly long")

    def test_raises_after_max_retries_exhausted(self):
        """After max_retries attempts all fail, the error propagates."""
        fn = MagicMock(side_effect=_rate_limit_error())

        with patch("time.sleep"):
            with self.assertRaises(anthropic.RateLimitError):
                api_call_with_retry(fn, max_retries=3)

        self.assertEqual(fn.call_count, 3)

    def test_non_rate_limit_errors_are_not_retried(self):
        """Other API errors (e.g. invalid request) should raise immediately."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 400
        response.headers = {}
        error = anthropic.BadRequestError("bad input", response=response, body={})
        fn = MagicMock(side_effect=error)

        with patch("time.sleep"):
            with self.assertRaises(anthropic.BadRequestError):
                api_call_with_retry(fn, max_retries=5)

        self.assertEqual(fn.call_count, 1)  # no retry


if __name__ == "__main__":
    unittest.main(verbosity=2)
