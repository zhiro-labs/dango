"""
Running an agent with retry and cross-model fallback.
"""

import asyncio

from agno.agent import Agent
from agno.run.base import RunStatus

from .models import DangoGemini
from .registry import Agents
from .routing import Route
from .settings import ModelSpec

_NON_GEMINI_RETRIES = 2  # mirrors DangoGemini's default model-level retries


async def run_with_retry(agent: Agent, messages: list, session_state: dict):
    """Run agent.arun with retry for non-Gemini providers.

    DangoGemini already retries at model level (retries=2, exponential_backoff).
    All other providers have no built-in retry in Agno, so we add one here.
    """
    is_gemini = isinstance(getattr(agent, "model", None), DangoGemini)
    attempts = 1 if is_gemini else _NON_GEMINI_RETRIES + 1
    response = None

    for attempt in range(attempts):
        response = await agent.arun(input=messages, session_state=session_state)
        if response.status != RunStatus.error or attempt == attempts - 1:
            break
        delay = 2 ** attempt  # 1 s, 2 s
        print(f"⚡ [arun] non-Gemini error on attempt {attempt + 1}/{attempts - 1}, retrying in {delay}s")
        await asyncio.sleep(delay)

    return response


def _fallback_for(agents: Agents, route: Route) -> Route | None:
    """The other model: fast→deep or deep→fast."""
    if route.agent is agents.fast and agents.deep is not None:
        return Route(agents.deep, agents.settings.deep)
    if route.agent is agents.deep:
        return Route(agents.fast, agents.settings.fast)
    return None


async def run_with_fallback(
    agents: Agents, route: Route, messages: list, session_state: dict
) -> tuple[object, ModelSpec | None]:
    """Run the routed agent; on error, try the other model if FALLBACK_ON_ERROR.

    Returns (response, fallback spec or None when no fallback ran).
    """
    response = await run_with_retry(route.agent, messages, session_state)
    if not (agents.settings.fallback_on_error and response.status == RunStatus.error):
        return response, None

    fallback = _fallback_for(agents, route)
    if fallback is None:
        return response, None
    print(f"⚡ [call_discord_agent] {route.spec.name} failed, falling back to {fallback.spec.name}")
    response = await run_with_retry(fallback.agent, messages, session_state)
    return response, fallback.spec
