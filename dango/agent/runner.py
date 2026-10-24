"""
Running an agent with retry and cross-model fallback.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from agno.agent import Agent
from agno.run.base import RunStatus

from .errors import FailureKind, capture_provider_errors, classify_failure
from .models import DangoGemini
from .registry import Agents
from .routing import Route
from .settings import ModelSpec

_NON_GEMINI_RETRIES = 2  # mirrors DangoGemini's default model-level retries

# Failures the same request would hit again: retrying only delays the
# fallback or the error reply.
_NOT_RETRYABLE = frozenset({
    FailureKind.AUTH,
    FailureKind.MODEL_NOT_FOUND,
    FailureKind.CONTEXT_TOO_LONG,
    FailureKind.BAD_REQUEST,
})


@dataclass(frozen=True)
class RunResult:
    response: Any                  # Agno RunOutput of the last attempt
    error: BaseException | None    # provider exception behind a failed response, if one was seen
    fallback: ModelSpec | None     # model tried after the routed one failed

    @property
    def failed(self) -> bool:
        return self.response.status == RunStatus.error


async def run_with_retry(agent: Agent, messages: list, session_state: dict) -> tuple[Any, BaseException | None]:
    """Run agent.arun with retry for non-Gemini providers.

    DangoGemini already retries at model level (retries=2, exponential_backoff).
    All other providers have no built-in retry in Agno, so we add one here,
    skipping failures a retry cannot fix (bad key, unknown model, context too
    long, rejected request).
    Returns (response, provider exception of the failed final attempt or None).
    """
    is_gemini = isinstance(getattr(agent, "model", None), DangoGemini)
    attempts = 1 if is_gemini else _NON_GEMINI_RETRIES + 1
    response, error = None, None

    for attempt in range(attempts):
        with capture_provider_errors() as errors:
            response = await agent.arun(input=messages, session_state=session_state)
        failed = response.status == RunStatus.error
        error = errors[-1] if failed and errors else None
        if not failed or attempt == attempts - 1:
            break
        kind = classify_failure(error, response.content)
        if kind in _NOT_RETRYABLE:
            print(f"⚡ [arun] non-Gemini error on attempt {attempt + 1} is not retryable ({kind.value})")
            break
        delay = 2 ** attempt  # 1 s, 2 s
        print(f"⚡ [arun] non-Gemini error on attempt {attempt + 1}/{attempts - 1}, retrying in {delay}s")
        await asyncio.sleep(delay)

    return response, error


def _fallback_for(agents: Agents, route: Route) -> Route | None:
    """The other model: fast→deep or deep→fast."""
    if route.agent is agents.fast and agents.deep is not None:
        return Route(agents.deep, agents.settings.deep)
    if route.agent is agents.deep:
        return Route(agents.fast, agents.settings.fast)
    return None


async def run_with_fallback(agents: Agents, route: Route, messages: list, session_state: dict) -> RunResult:
    """Run the routed agent; on error, try the other model if FALLBACK_ON_ERROR."""
    response, error = await run_with_retry(route.agent, messages, session_state)
    if not (agents.settings.fallback_on_error and response.status == RunStatus.error):
        return RunResult(response, error, None)

    fallback = _fallback_for(agents, route)
    if fallback is None:
        return RunResult(response, error, None)
    print(f"⚡ [call_discord_agent] {route.spec.name} failed, falling back to {fallback.spec.name}")
    response, error = await run_with_retry(fallback.agent, messages, session_state)
    return RunResult(response, error, fallback.spec)
