"""
The LLM agent behind the chat pipeline: configuration, models, tools,
skills, routing between the fast and deep models, and resilient runs.

The LLMChat workflow step (dango/steps/call_agent.py) only orchestrates
these pieces for one Discord message.
"""

from .registry import Agents, get_agents
from .routing import Route, choose_route, trim_to_token_budget
from .runner import run_with_fallback, run_with_retry
from .settings import AgentSettings, ModelSpec, get_settings
from .skills import get_forced_skill_instructions, list_skill_names

__all__ = [
    "AgentSettings",
    "Agents",
    "ModelSpec",
    "Route",
    "choose_route",
    "get_agents",
    "get_forced_skill_instructions",
    "get_settings",
    "list_skill_names",
    "run_with_fallback",
    "run_with_retry",
    "trim_to_token_budget",
]
