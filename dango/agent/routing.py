"""
Choosing the fast or deep agent for a request, and fitting its context.
"""

from dataclasses import dataclass

from agno.agent import Agent
from agno.models.message import Message

from ..utils.complexity_router import URL as _URL_RE, classify
from .registry import Agents
from .settings import ModelSpec


@dataclass(frozen=True)
class Route:
    agent: Agent
    spec: ModelSpec


def _by_complexity(agents: Agents, content: str, history: list[str]) -> Route:
    """Deep for complex messages when AUTO_ROUTE is on; fast otherwise."""
    settings = agents.settings
    if settings.auto_route and agents.deep and settings.deep:
        r = classify(content, history=history)
        print(
            f"🔀 [route] {'deep' if r.decision == 'complex' else 'fast'}  "
            f"← band={r.band} score={r.score} "
            f"{('rules=' + ','.join(r.hard_rules) + ' ') if r.hard_rules else ''}"
            f"content: {content!r}"
        )
        if r.decision == "complex":
            return Route(agents.deep, settings.deep)
    else:
        deep_name = settings.deep.name if settings.deep else None
        print(f"🔀 [route] fast  ← auto_route={settings.auto_route} deep_model={deep_name!r}")
    return Route(agents.fast, settings.fast)


def _needs_url_context(agents: Agents, route: Route, content: str) -> bool:
    """Fast Gemini lacks url_context but deep Gemini has it, and there is a URL.

    Intentionally Gemini-only: url_context is a Gemini-specific fetch feature.
    Non-Gemini fast models are not upgraded — the user chose that provider
    deliberately and it can still process URLs as plain text.
    """
    return (
        route.agent is agents.fast
        and agents.deep is not None
        and agents.fast_gemini is not None
        and not getattr(agents.fast_gemini, "url_context", False)
        and agents.deep_gemini is not None
        and getattr(agents.deep_gemini, "url_context", False)
        and bool(_URL_RE.search(content))
    )


def choose_route(agents: Agents, content: str, history: list[str], force_deep: bool) -> Route:
    """Pick the agent for this message.

    Order: forced deep (/deep, !!) → complexity routing → URL upgrade.
    """
    settings = agents.settings
    if force_deep and agents.deep and settings.deep:
        print("🔀 [route] deep  ← forced via !! prefix")
        route = Route(agents.deep, settings.deep)
    else:
        route = _by_complexity(agents, content, history)

    if _needs_url_context(agents, route, content):
        print("🔀 [route] deep  ← URL in message, fast model lacks url_context")
        route = Route(agents.deep, settings.deep)
    return route


def trim_to_token_budget(messages: list[Message], budget: int, model_id: str) -> list[Message]:
    """Trim oldest messages until estimated token count fits within budget.

    Uses agno's tiktoken-based counter — local, no API calls, works with all providers.
    The model_id is passed to tiktoken for encoding selection; unknown models fall back
    to o200k_base which is a reasonable general-purpose estimate.
    Falls back gracefully (no trimming) if token counting itself fails.
    """
    if budget == 0 or len(messages) <= 1:
        return messages

    from agno.utils.tokens import count_tokens as _agno_count_tokens

    def _count(msgs: list[Message]) -> int:
        return _agno_count_tokens(msgs, model_id=model_id)

    try:
        count = _count(messages)
    except Exception:
        return messages  # counting unavailable — don't drop anything

    if count <= budget:
        return messages

    # Proportional drop: remove roughly (1 - budget/count) fraction from the front,
    # but always keep the last message (current user turn).
    drop = max(1, int(len(messages) * (1 - budget / count)))
    messages = messages[drop:]

    # Single follow-up loop in case proportional estimate was off
    try:
        while len(messages) > 1 and _count(messages) > budget:
            messages.pop(0)
    except Exception:
        pass

    return messages
