"""
Agent configuration read from environment variables.

Docker deployments get these from data/config.yaml (injected into the env by
app_config.py); developer deployments get them from .env. Settings are read
once, on first use, so importing dango never requires them to be set.
"""

import json
import os
import re
from dataclasses import dataclass

from ..utils.config_utils import env_onoff_to_bool


def parse_provider(model_str: str) -> str:
    """Provider prefix of 'provider:model_id'; a bare model id means Google."""
    return model_str.split(":", 1)[0] if ":" in model_str else "google"


def sanitize_name(raw: str, fallback: str) -> str:
    """Turn a user-given name into an identifier usable in tool names."""
    return re.sub(r"\W+", "_", raw, flags=re.UNICODE).strip("_") or fallback


@dataclass(frozen=True)
class ModelSpec:
    """One configured model (fast or deep)."""

    name: str              # as configured: "provider:model_id"
    api_key: str | None
    base_url: str | None   # custom endpoint for local / proxied models
    env_prefix: str        # "FAST" or "DEEP", for per-model env overrides
    context_budget: int    # max input tokens; 0 = never trim

    @property
    def provider(self) -> str:
        return parse_provider(self.name)

    @property
    def model_id(self) -> str:
        return self.name.split(":", 1)[1] if ":" in self.name else self.name


@dataclass(frozen=True)
class AgentSettings:
    fast: ModelSpec
    deep: ModelSpec | None  # None disables routing, /deep and fallback

    auto_route: bool         # pick fast/deep by message complexity
    fallback_on_error: bool  # retry a failed run on the other model
    contextual_prompt: bool  # inject names, participants and time

    enable_workspace: bool
    workspace_root: str      # absolute path
    enable_skills: bool
    skills_root: str         # absolute path

    enable_duckduckgo: bool
    enable_brave_search: bool
    brave_api_key: str | None
    enable_website_tools: bool

    enable_custom_apis: bool
    custom_apis: tuple[dict, ...]
    enable_sql_databases: bool
    sql_databases: tuple[dict, ...]

    # Tool results longer than this many characters are kept out of the
    # model's context (preview + id, read back on demand); 0 turns it off.
    tool_result_offload_chars: int
    # How long an offloaded result stays readable; 0 keeps it until exit.
    tool_result_ttl_seconds: int


def _onoff(name: str, default: bool = False) -> bool:
    return env_onoff_to_bool(os.getenv(name), default=default)


DEFAULT_TOOL_RESULT_OFFLOAD_CHARS = 16_000  # Agno's default: one read_result page
DEFAULT_TOOL_RESULT_TTL_SECONDS = 3_600


def _non_negative_int(name: str, default: int) -> int:
    """An env var holding a whole number >= 0; unset or blank means `default`."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name} must be 0 or more, got {value}")
    return value


def _context_budget(prefix: str) -> int:
    v = os.getenv(f"{prefix}_CONTEXT_TOKEN_BUDGET") or os.getenv("CONTEXT_TOKEN_BUDGET")
    return int(v) if v else 0


def _check_unique_names(configs: list[dict], kind: str, fallback: str) -> None:
    """Two entries whose names sanitize to the same tool name would collide."""
    seen: dict[str, int] = {}
    for i, cfg in enumerate(configs):
        safe = sanitize_name(cfg.get("name", ""), fallback)
        if safe in seen:
            raise ValueError(
                f"{kind} config error: entries at index {seen[safe]} and {i} both resolve to "
                f"the same sanitized name '{safe}'. Give them distinct 'name' values."
            )
        seen[safe] = i


def load_settings() -> AgentSettings:
    """Read AgentSettings from the current environment."""
    fast_api_key = os.getenv("FAST_API_KEY")
    fast = ModelSpec(
        name=os.getenv("FAST_MODEL") or "",
        api_key=fast_api_key,
        base_url=os.getenv("FAST_BASE_URL"),
        env_prefix="FAST",
        context_budget=_context_budget("FAST"),
    )
    deep_model = os.getenv("DEEP_MODEL")
    deep = ModelSpec(
        name=deep_model,
        api_key=os.getenv("DEEP_API_KEY") or fast_api_key,
        base_url=os.getenv("DEEP_BASE_URL"),
        env_prefix="DEEP",
        context_budget=_context_budget("DEEP"),
    ) if deep_model else None

    custom_apis = json.loads(os.getenv("CUSTOM_APIS_JSON", "[]"))
    sql_databases = json.loads(os.getenv("SQL_DATABASES_JSON", "[]"))
    _check_unique_names(custom_apis, "CUSTOM_APIS_JSON", "api")
    _check_unique_names(sql_databases, "SQL_DATABASES_JSON", "db")

    return AgentSettings(
        fast=fast,
        deep=deep,
        auto_route=_onoff("AUTO_ROUTE"),
        fallback_on_error=_onoff("FALLBACK_ON_ERROR"),
        contextual_prompt=_onoff("ENABLE_CONTEXTUAL_SYSTEM_PROMPT", default=True),
        enable_workspace=_onoff("ENABLE_WORKSPACE"),
        workspace_root=os.path.abspath(os.getenv("WORKSPACE_ROOT", "workspace")),
        enable_skills=_onoff("ENABLE_SKILLS"),
        skills_root=os.path.abspath(os.getenv("SKILLS_ROOT", "skills")),
        enable_duckduckgo=_onoff("ENABLE_DUCKDUCKGO"),
        enable_brave_search=_onoff("ENABLE_BRAVE_SEARCH"),
        brave_api_key=os.getenv("BRAVE_API_KEY"),
        enable_website_tools=_onoff("ENABLE_WEBSITE_TOOLS"),
        enable_custom_apis=_onoff("ENABLE_CUSTOM_APIS"),
        custom_apis=tuple(custom_apis),
        enable_sql_databases=_onoff("ENABLE_SQL_DATABASES"),
        sql_databases=tuple(sql_databases),
        tool_result_offload_chars=_non_negative_int(
            "TOOL_RESULT_OFFLOAD_CHARS", DEFAULT_TOOL_RESULT_OFFLOAD_CHARS
        ),
        tool_result_ttl_seconds=_non_negative_int(
            "TOOL_RESULT_TTL_SECONDS", DEFAULT_TOOL_RESULT_TTL_SECONDS
        ),
    )


_settings: AgentSettings | None = None


def get_settings() -> AgentSettings:
    """Settings for this process, read from the environment on first call."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
