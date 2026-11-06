"""Fakes for the Claude client, shared by the offline tests."""

from types import SimpleNamespace

import anthropic


def make_usage(input_tokens=100, output_tokens=50, written=0, read=0, searches=None):
    usage = SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_creation_input_tokens=written, cache_read_input_tokens=read,
    )
    if searches is not None:
        usage.server_tool_use = SimpleNamespace(web_search_requests=searches)
    return usage


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def search_block():
    return SimpleNamespace(type="server_tool_use", name="web_search")


def results_block():
    return SimpleNamespace(type="web_search_tool_result", content=[])


def make_response(stop_reason, *blocks, usage=None, stop_details=None, headers=None):
    """A final message. headers are the HTTP headers its stream was served with."""
    return SimpleNamespace(
        stop_reason=stop_reason, content=list(blocks),
        usage=usage or make_usage(), stop_details=stop_details, headers=headers or {},
    )


def rate_limit_headers(input_left=None, input_limit=None, output_left=None, output_limit=None):
    """The anthropic-ratelimit-* headers the API sends, for the figures given."""
    figures = {
        "anthropic-ratelimit-input-tokens-remaining": input_left,
        "anthropic-ratelimit-input-tokens-limit": input_limit,
        "anthropic-ratelimit-output-tokens-remaining": output_left,
        "anthropic-ratelimit-output-tokens-limit": output_limit,
    }
    return {name: str(value) for name, value in figures.items() if value is not None}


class _Response:
    """Just enough of an HTTP response for the SDK's error classes."""

    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.request = SimpleNamespace()


def status_error(status, headers=None, body=None):
    return anthropic.APIStatusError(f"error {status}", response=_Response(status, headers), body=body)


def stream_error(error_type, error_code=None):
    """An error event that arrives inside a stream: the HTTP status was already 200."""
    error = {"type": error_type, "message": "mid-stream"}
    if error_code:
        error["details"] = {"error_code": error_code}
    return status_error(200, body={"type": "error", "error": error})


class _FakeStream:
    def __init__(self, item):
        self._item = item

    def __enter__(self):
        # Opening the stream is when the SDK raises an HTTP error or a connection error. Only an
        # error event inside a stream (status 200) is raised later, while the message is read.
        if isinstance(self._item, Exception) and not self._is_mid_stream():
            raise self._item
        return self

    def _is_mid_stream(self):
        return isinstance(self._item, anthropic.APIStatusError) and self._item.status_code < 300

    def __exit__(self, *exc):
        return False

    @property
    def response(self):
        """The HTTP response of the stream, which is where the SDK exposes its headers."""
        if isinstance(self._item, Exception):
            return getattr(self._item, "response", SimpleNamespace(headers={}))
        return SimpleNamespace(headers=self._item.headers)

    def get_final_message(self):
        if isinstance(self._item, Exception):
            raise self._item
        return self._item


class FakeApi:
    """Stands in for agent.client. Serves scripted responses (or raises scripted errors)
    to messages.stream, and records each request."""

    def __init__(self):
        self.responses: list = []
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return _FakeStream(self.responses.pop(0))
