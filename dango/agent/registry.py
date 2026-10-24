"""
The fast and deep agents, built once per process.

Per-request context is never stored on the agents; it travels in
session_state on each run.
"""

from dataclasses import dataclass

from agno.agent import Agent

from .instructions import make_instructions
from .models import DangoGemini, inject_provider_key, make_model
from .settings import AgentSettings, ModelSpec, get_settings
from .skills import get_skills
from .tools import build_tools


@dataclass(frozen=True)
class Agents:
    settings: AgentSettings
    fast: Agent
    fast_model: DangoGemini | object | str
    deep: Agent | None
    deep_model: DangoGemini | object | str | None

    @property
    def fast_gemini(self) -> DangoGemini | None:
        return self.fast_model if isinstance(self.fast_model, DangoGemini) else None

    @property
    def deep_gemini(self) -> DangoGemini | None:
        return self.deep_model if isinstance(self.deep_model, DangoGemini) else None

    def spec_for(self, agent: Agent) -> ModelSpec:
        return self.settings.deep if agent is self.deep else self.settings.fast


def _build_agent(model, settings: AgentSettings, fast_model, instructions) -> Agent:
    return Agent(
        model=model,
        tools=build_tools(settings, fast_model) or None,
        skills=get_skills(),
        instructions=instructions,
        # Time is injected by the instructions callable (reads runtime_config.timezone
        # each call), so add_datetime_to_context is intentionally off.
        add_history_to_context=False,
        markdown=False,
    )


def _build_agents(settings: AgentSettings) -> Agents:
    fast, deep = settings.fast, settings.deep
    if not fast.name:
        raise RuntimeError(
            "FAST_MODEL is not set. Configure it in the Web GUI (Models tab) or set the "
            "FAST_MODEL environment variable (e.g. 'google:gemini-2.0-flash')."
        )
    inject_provider_key(fast)
    if deep:
        inject_provider_key(deep)
    if settings.fallback_on_error and deep and fast.provider == deep.provider:
        print(
            f"⚠️  [config] FAST_MODEL and DEEP_MODEL share provider "
            f"'{fast.provider}' — FALLBACK_ON_ERROR won't protect against provider-wide outages."
        )

    instructions = make_instructions(settings.contextual_prompt)
    fast_model = make_model(fast)
    fast_agent = _build_agent(fast_model, settings, fast_model, instructions)
    deep_model = make_model(deep) if deep else None
    deep_agent = _build_agent(deep_model, settings, fast_model, instructions) if deep_model else None
    return Agents(settings, fast_agent, fast_model, deep_agent, deep_model)


_agents: Agents | None = None


def get_agents() -> Agents:
    """The process-wide agents, built (and config validated) on first call."""
    global _agents
    if _agents is None:
        _agents = _build_agents(get_settings())
    return _agents
