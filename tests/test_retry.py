#!/usr/bin/env python3
"""
Tests for api_call_with_retry. Uses fake errors — no API calls, no cost, no real sleeping.
"""
import contextlib
import io
import unittest
from unittest.mock import patch, MagicMock

import anthropic
import agent
from agent import api_call_with_retry


class _Response:
    """Just enough of an HTTP response for the SDK's error classes."""

    def __init__(self, status_code: int, headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self.request = MagicMock()


def _status_error(status: int, headers: dict | None = None, body: dict | None = None):
    return anthropic.APIStatusError(
        f"error {status}", response=_Response(status, headers), body=body
    )


def _spend_cap_error():
    return _status_error(429, body={
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": "You have reached your API usage limits.",
            "details": {"error_code": "enforced_spend_limit_reached"},
        },
    })


def _flaky(errors: list, result="ok"):
    """A fn that raises each error in turn, then returns result."""
    queue = list(errors)

    def fn():
        if queue:
            raise queue.pop(0)
        return result

    return MagicMock(side_effect=fn)


def _run(fn, **kwargs):
    """Run api_call_with_retry with sleep recorded instead of performed. Returns (sleeps, stdout)."""
    sleeps: list[float] = []
    out = io.StringIO()
    with patch("time.sleep", side_effect=sleeps.append), contextlib.redirect_stdout(out):
        api_call_with_retry(fn, **kwargs)
    return sleeps, out.getvalue()


class TestRetriedErrors(unittest.TestCase):

    def test_succeeds_on_first_try(self):
        fn = MagicMock(return_value="ok")
        sleeps, _ = _run(fn)
        self.assertEqual(fn.call_count, 1)
        self.assertEqual(sleeps, [])

    def test_retry_after_header_is_obeyed(self):
        fn = _flaky([_status_error(429, {"retry-after": "23"})] * 2)
        sleeps, _ = _run(fn)
        self.assertEqual(fn.call_count, 3)
        for wait in sleeps:
            self.assertGreaterEqual(wait, 23)
            self.assertLessEqual(wait, 24)  # up to 1s of jitter on top

    def test_retry_after_ms_header_is_obeyed(self):
        fn = _flaky([_status_error(429, {"retry-after-ms": "1500"})])
        sleeps, _ = _run(fn)
        self.assertGreaterEqual(sleeps[0], 1.5)
        self.assertLessEqual(sleeps[0], 2.5)

    def test_429_without_retry_after_backs_off_exponentially(self):
        fn = _flaky([_status_error(429)] * 4)
        sleeps, _ = _run(fn)
        self.assertEqual(len(sleeps), 4)
        for retry, wait in enumerate(sleeps, start=1):
            delay = 2.0 * 2 ** (retry - 1)  # 2, 4, 8, 16
            self.assertGreaterEqual(wait, delay / 2)
            self.assertLessEqual(wait, delay)

    def test_backoff_is_capped(self):
        for _ in range(50):
            self.assertLessEqual(agent._backoff_s(30), 60)
            self.assertGreaterEqual(agent._backoff_s(30), 30)

    def test_server_errors_and_overload_are_retried(self):
        for status in (408, 409, 500, 502, 503, 504, 529):
            with self.subTest(status=status):
                fn = _flaky([_status_error(status)])
                sleeps, _ = _run(fn)
                self.assertEqual(fn.call_count, 2)
                self.assertEqual(len(sleeps), 1)

    def test_connection_errors_are_retried(self):
        for error in (
            anthropic.APIConnectionError(request=MagicMock()),
            anthropic.APITimeoutError(request=MagicMock()),
        ):
            with self.subTest(error=type(error).__name__):
                fn = _flaky([error])
                _run(fn)
                self.assertEqual(fn.call_count, 2)


class TestPermanentErrors(unittest.TestCase):

    def test_permanent_statuses_make_exactly_one_request(self):
        for status in (400, 401, 402, 403, 404, 413, 422):
            with self.subTest(status=status):
                error = _status_error(status)
                fn = MagicMock(side_effect=error)
                sleeps: list[float] = []
                with patch("time.sleep", side_effect=sleeps.append):
                    with self.assertRaises(anthropic.APIStatusError) as ctx:
                        api_call_with_retry(fn)
                self.assertIs(ctx.exception, error)
                self.assertEqual(fn.call_count, 1)
                self.assertEqual(sleeps, [])

    def test_spend_cap_429_makes_exactly_one_request(self):
        fn = MagicMock(side_effect=_spend_cap_error())
        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(anthropic.APIStatusError):
                api_call_with_retry(fn)
        self.assertEqual(fn.call_count, 1)
        mock_sleep.assert_not_called()

    def test_non_api_errors_propagate_without_retry(self):
        fn = MagicMock(side_effect=ValueError("not an API error"))
        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(ValueError):
                api_call_with_retry(fn)
        self.assertEqual(fn.call_count, 1)
        mock_sleep.assert_not_called()


class TestLimits(unittest.TestCase):

    def test_wait_larger_than_budget_raises_without_sleeping(self):
        fn = MagicMock(side_effect=_status_error(429, {"retry-after": "1000"}))
        out = io.StringIO()
        with patch("time.sleep") as mock_sleep, contextlib.redirect_stdout(out):
            with self.assertRaises(anthropic.APIStatusError):
                api_call_with_retry(fn)  # default budget is 900s
        self.assertEqual(fn.call_count, 1)
        mock_sleep.assert_not_called()
        self.assertIn("not retrying", out.getvalue())

    def test_budget_is_spent_across_retries(self):
        fn = MagicMock(side_effect=_status_error(429, {"retry-after": "400"}))
        sleeps: list[float] = []
        with patch("time.sleep", side_effect=sleeps.append), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(anthropic.APIStatusError):
                api_call_with_retry(fn, max_total_wait=900)
        self.assertEqual(len(sleeps), 2)      # 2 x ~400s fit in 900s, a third does not
        self.assertEqual(fn.call_count, 3)
        self.assertLessEqual(sum(sleeps), 900)

    def test_raises_after_max_retries(self):
        fn = MagicMock(side_effect=_status_error(503))
        with patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(anthropic.APIStatusError):
                api_call_with_retry(fn, max_retries=3)
        self.assertEqual(fn.call_count, 4)  # the first attempt plus 3 retries


class TestVisibleWaits(unittest.TestCase):

    def test_long_wait_is_printed_with_its_reason(self):
        _, out = _run(_flaky([_status_error(429, {"retry-after": "10"})]))
        self.assertIn("Rate limited (429)", out)
        self.assertIn("waiting", out)
        self.assertIn("retry 1/8", out)

    def test_server_error_reason_is_printed(self):
        _, out = _run(_flaky([_status_error(529, {"retry-after": "10"})]))
        self.assertIn("overloaded (529)", out)

    def test_short_wait_is_not_printed(self):
        sleeps, out = _run(_flaky([_status_error(429, {"retry-after": "2"})]))
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(out, "")


def _stream_error(error_type: str, error_code: str | None = None):
    """An error event inside a stream: the HTTP status was already 200, so only the type tells."""
    error = {"type": error_type, "message": "mid-stream"}
    if error_code:
        error["details"] = {"error_code": error_code}
    return _status_error(200, body={"type": "error", "error": error})


class TestErrorsInsideAStream(unittest.TestCase):

    def test_transient_error_types_are_retried(self):
        for kind in ("overloaded_error", "api_error", "rate_limit_error"):
            with self.subTest(kind=kind):
                fn = _flaky([_stream_error(kind)])
                sleeps, _ = _run(fn)
                self.assertEqual(fn.call_count, 2)
                self.assertEqual(len(sleeps), 1)

    def test_other_error_types_are_raised_without_retry(self):
        for kind in ("invalid_request_error", "authentication_error", "a_type_added_later"):
            with self.subTest(kind=kind):
                error = _stream_error(kind)
                fn = MagicMock(side_effect=error)
                with patch("time.sleep") as mock_sleep:
                    with self.assertRaises(anthropic.APIStatusError) as ctx:
                        api_call_with_retry(fn)
                self.assertIs(ctx.exception, error)
                self.assertEqual(fn.call_count, 1)
                mock_sleep.assert_not_called()

    def test_spend_cap_inside_a_stream_is_not_retried(self):
        fn = MagicMock(side_effect=_stream_error("rate_limit_error", "enforced_spend_limit_reached"))
        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(anthropic.APIStatusError):
                api_call_with_retry(fn)
        self.assertEqual(fn.call_count, 1)
        mock_sleep.assert_not_called()


class TestSdkRetriesAreOff(unittest.TestCase):
    """The wrapper must be the only retry layer, or waits stack up silently underneath it."""

    def test_pipeline_client_has_sdk_retries_off(self):
        self.assertEqual(agent.client.max_retries, 0)

    def test_quality_scorer_client_has_sdk_retries_off(self):
        import observability

        block = MagicMock()
        block.text = '{"score": 4, "reason": "ok"}'
        with patch("observability.api_call_with_retry", side_effect=lambda fn: fn()), \
             patch("observability.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.return_value = MagicMock(content=[block])
            observability.llm_quality_score("research", "some output", {})
        mock_anthropic.assert_called_once_with(max_retries=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
