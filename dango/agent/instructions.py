"""
The agent's system prompt, rebuilt on every run from per-request session_state.
"""

from collections.abc import Callable

from ..utils.build_instructions import build_instructions
from .skills import get_forced_skill_instructions


def make_instructions(contextual: bool) -> Callable[[dict], str]:
    """Return the instructions callable for Agent(instructions=...).

    Agno passes session_state by parameter name, so the inner function's
    parameter must stay named `session_state`.
    """

    def instructions(session_state: dict) -> str:
        text = build_instructions(
            base_prompt=session_state.get("chat_sys_prompt", ""),
            author_name=session_state.get("author_name", "User"),
            unique_users=set(session_state.get("unique_users", [])),
            enable_contextual=contextual,
            history_limit=session_state.get("history_limit"),
            timezone=session_state.get("timezone"),
        )
        # /skill: when a skill is forced for this turn, hard-inject its full
        # instructions so the model applies it directly (no get_skill_instructions
        # round-trip needed). The get_skill_* tools stay available for references.
        forced = session_state.get("forced_skill")
        if forced:
            body = get_forced_skill_instructions(forced)
            if body:
                text += (
                    f"\n\n---\n\n# Active skill: {forced}\n"
                    "The user explicitly requested this skill. You MUST apply the "
                    "following skill instructions for this response:\n\n"
                    f"{body}"
                )
        return text

    return instructions
