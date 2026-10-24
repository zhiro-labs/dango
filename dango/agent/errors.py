"""
Provider errors behind failed runs, and what kind of failure they are.

Agno turns a failed model call into RunOutput(status=error, content=str(e)),
dropping the exception and its status code. Models built by make_model()
record the provider's exception into the active capture, so the caller can
still tell an invalid API key from an overloaded server.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum

from agno.exceptions import ContextWindowExceededError, ModelAuthenticationError, ModelProviderError

_sink: ContextVar[list[BaseException] | None] = ContextVar("dango_provider_errors", default=None)


@contextmanager
def capture_provider_errors() -> Iterator[list[BaseException]]:
    """Collect exceptions raised by model calls made inside the block.

    The list is shared by reference, so errors raised in tasks Agno spawns
    (which copy the context) still land in it.
    """
    errors: list[BaseException] = []
    token = _sink.set(errors)
    try:
        yield errors
    finally:
        _sink.reset(token)


class RecordsProviderErrors:
    """Model mixin: record exceptions from ainvoke into the active capture."""

    async def ainvoke(self, *args, **kwargs):
        try:
            return await super().ainvoke(*args, **kwargs)
        except Exception as e:
            sink = _sink.get()
            if sink is not None:
                sink.append(e)
            raise


class FailureKind(Enum):
    AUTH = "auth"                          # bad API key or no access
    RATE_LIMIT = "rate_limit"              # 429, quota exhausted
    OVERLOADED = "overloaded"              # 5xx, provider unavailable
    MODEL_NOT_FOUND = "model_not_found"    # wrong model name
    CONTEXT_TOO_LONG = "context_too_long"  # input exceeds the context window
    CONNECTION = "connection"              # network error or timeout
    BAD_REQUEST = "bad_request"            # other 4xx
    UNKNOWN = "unknown"


# Exception class names (anywhere in the cause chain) that mean the provider
# was never reached. Matched by name so optional SDKs need not be imported.
_CONNECTION_ERRORS = {
    "APIConnectionError", "APITimeoutError",             # openai, anthropic, groq, ...
    "ConnectError", "ConnectTimeout", "ReadTimeout",     # httpx (google-genai, ollama)
    "WriteTimeout", "PoolTimeout", "TimeoutException",
    "ClientConnectorError", "ServerDisconnectedError",   # aiohttp
}

_AUTH_HINTS = (
    "api key", "api_key", "apikey", "x-api-key", "unauthenticated", "unauthorized",
    "authentication", "permission denied", "permission_denied",
)
_RATE_LIMIT_HINTS = ("rate limit", "rate_limit", "quota", "resource_exhausted", "too many requests")
_NOT_FOUND_HINTS = ("does not exist", "is not found", "model_not_found", "no such model")
_OVERLOADED_HINTS = ("overloaded", "unavailable")


def _cause_chain(error: BaseException | None) -> Iterator[BaseException]:
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def _is_connection_error(error: BaseException | None) -> bool:
    return any(
        isinstance(e, (ConnectionError, TimeoutError)) or type(e).__name__ in _CONNECTION_ERRORS
        for e in _cause_chain(error)
    )


def classify_failure(error: BaseException | None, content: str | None = None) -> FailureKind:
    """Classify a failed run from the provider exception, else its error text.

    `content` is the failed RunOutput's content (str of the final exception);
    it is used when no exception was recorded.
    """
    text = (str(error) if error is not None else content or "").lower()
    status = getattr(error, "status_code", None)

    if _is_connection_error(error):
        return FailureKind.CONNECTION

    # Exception types and status codes with unambiguous meaning.
    if isinstance(error, ModelAuthenticationError) or status in (401, 403):
        return FailureKind.AUTH
    if isinstance(error, ContextWindowExceededError) or status == 413:
        return FailureKind.CONTEXT_TOO_LONG
    if status == 429:
        return FailureKind.RATE_LIMIT
    if status == 404:
        return FailureKind.MODEL_NOT_FOUND

    # Message text: Gemini reports a bad key as 400 "API key not valid", and
    # Agno wraps unrecognized SDK errors as 502 regardless of their cause.
    if any(h in text for h in _AUTH_HINTS):
        return FailureKind.AUTH
    if any(p in text for p in ModelProviderError.CONTEXT_WINDOW_PATTERNS):
        return FailureKind.CONTEXT_TOO_LONG
    if any(h in text for h in _RATE_LIMIT_HINTS):
        return FailureKind.RATE_LIMIT
    if any(h in text for h in _NOT_FOUND_HINTS):
        return FailureKind.MODEL_NOT_FOUND
    if any(h in text for h in _OVERLOADED_HINTS):
        return FailureKind.OVERLOADED

    if status is not None and status >= 500:
        return FailureKind.OVERLOADED
    if status is not None and 400 <= status < 500:
        return FailureKind.BAD_REQUEST
    return FailureKind.UNKNOWN
