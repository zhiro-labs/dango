"""
Tests for dango/agent/errors.py: capturing provider errors and classifying
failed runs. End-to-end replies are covered in test_call_agent.py.
"""

import asyncio

import httpx
import openai
import pytest
from agno.exceptions import ContextWindowExceededError, ModelAuthenticationError, ModelProviderError

from dango.agent.errors import FailureKind, RecordsProviderErrors, capture_provider_errors, classify_failure


def _chain(outer: BaseException, cause: BaseException) -> BaseException:
    outer.__cause__ = cause
    return outer


@pytest.mark.parametrize("error, kind", [
    # Status codes with a fixed meaning win over text.
    (ModelProviderError("whatever", status_code=401), FailureKind.AUTH),
    (ModelProviderError("whatever", status_code=403), FailureKind.AUTH),
    (ModelAuthenticationError("OPENAI_API_KEY not set."), FailureKind.AUTH),
    (ModelProviderError("Rate limit reached; see api key settings", status_code=429), FailureKind.RATE_LIMIT),
    (ModelProviderError("whatever", status_code=404), FailureKind.MODEL_NOT_FOUND),
    (ModelProviderError("Request too large", status_code=413), FailureKind.CONTEXT_TOO_LONG),
    (ContextWindowExceededError("too big"), FailureKind.CONTEXT_TOO_LONG),
    # Text decides for 400s and Agno's catch-all 502.
    (ModelProviderError("400 INVALID_ARGUMENT. API key not valid.", status_code=400), FailureKind.AUTH),
    (ModelProviderError("invalid x-api-key", status_code=502), FailureKind.AUTH),
    (ModelProviderError("prompt is too long: 250000 tokens > 200000 maximum", status_code=400),
     FailureKind.CONTEXT_TOO_LONG),
    (ModelProviderError("Overloaded", status_code=529), FailureKind.OVERLOADED),  # Anthropic
    (ModelProviderError("503 UNAVAILABLE", status_code=503), FailureKind.OVERLOADED),
    (ModelProviderError("Internal server error", status_code=500), FailureKind.OVERLOADED),
    (ModelProviderError("Invalid 'messages[1].role'", status_code=400), FailureKind.BAD_REQUEST),
    (ModelProviderError("Invalid 'messages[1].role'", status_code=422), FailureKind.BAD_REQUEST),
    # Network problems anywhere in the cause chain.
    (_chain(ModelProviderError("Connection error.", status_code=502),
            openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))),
     FailureKind.CONNECTION),
    (_chain(ModelProviderError("boom", status_code=502), httpx.ConnectError("refused")), FailureKind.CONNECTION),
    (_chain(ModelProviderError("boom", status_code=502), TimeoutError()), FailureKind.CONNECTION),
    (ConnectionRefusedError("ollama not running"), FailureKind.CONNECTION),
    (RuntimeError("something odd"), FailureKind.UNKNOWN),
])
def test_classify_exceptions(error, kind):
    assert classify_failure(error, "ignored when an exception is given") is kind


@pytest.mark.parametrize("content, kind", [
    ("You exceeded your current quota", FailureKind.RATE_LIMIT),
    ("models/gemini-9 is not found", FailureKind.MODEL_NOT_FOUND),
    ("The model is overloaded", FailureKind.OVERLOADED),
    ("Incorrect API key provided", FailureKind.AUTH),
    ("boom", FailureKind.UNKNOWN),
    ("", FailureKind.UNKNOWN),
    (None, FailureKind.UNKNOWN),
])
def test_classify_text_when_no_exception(content, kind):
    assert classify_failure(None, content) is kind


class _Provider:
    def __init__(self, error):
        self.error = error

    async def ainvoke(self, *args, **kwargs):
        raise self.error


class _RecordingProvider(RecordsProviderErrors, _Provider):
    pass


def _call(model) -> None:
    with pytest.raises(Exception):
        asyncio.run(model.ainvoke())


def test_errors_are_recorded_inside_a_capture():
    error = ModelProviderError("503", status_code=503)
    with capture_provider_errors() as errors:
        _call(_RecordingProvider(error))
    assert errors == [error]


def test_no_capture_means_no_recording():
    _call(_RecordingProvider(ValueError("x")))  # must not fail without a sink


def test_captures_are_independent():
    outer_error, inner_error = ValueError("outer"), ValueError("inner")
    with capture_provider_errors() as outer:
        with capture_provider_errors() as inner:
            _call(_RecordingProvider(inner_error))
        _call(_RecordingProvider(outer_error))
    assert inner == [inner_error]
    assert outer == [outer_error]


def test_errors_from_spawned_tasks_reach_the_capture():
    error = ValueError("in task")

    async def main():
        await asyncio.gather(asyncio.create_task(_RecordingProvider(error).ainvoke()), return_exceptions=True)

    with capture_provider_errors() as errors:
        asyncio.run(main())
    assert errors == [error]
