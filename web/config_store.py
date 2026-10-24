import os
from pathlib import Path

import yaml
from pydantic import BaseModel

_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
CONFIG_PATH = _DATA_DIR / "config.yaml"
CONFIG_VERSION = "1"


class BotConfig(BaseModel):
    config_version: str = CONFIG_VERSION

    # ── Credentials ──────────────────────────────────────────────────────────
    discord_token: str = ""
    fast_api_key: str = ""
    deep_api_key: str = ""  # falls back to fast_api_key if empty

    # ── Models ───────────────────────────────────────────────────────────────
    fast_model: str = ""
    fast_base_url: str = ""  # custom endpoint (e.g. http://host.docker.internal:11434)
    deep_model: str = ""
    deep_base_url: str = ""

    # ── Routing ──────────────────────────────────────────────────────────────
    auto_route: bool = False
    fallback_on_error: bool = False

    # ── Bot behaviour ─────────────────────────────────────────────────────────
    chat_sys_prompt: str = (
        "You are Dango, a helpful AI assistant on this Discord server. "
        "Always be polite and positive in your responses."
    )
    enable_contextual_system_prompt: bool = True
    enable_message_batching: bool = False
    message_batch_window: float = 5
    message_batch_max_wait: float = 15

    # ── Workspace ────────────────────────────────────────────────────────────
    enable_workspace: bool = False
    workspace_root: str = "workspace"
    workspace_allowed: str = "read,list,search"

    # ── Skills ───────────────────────────────────────────────────────────────
    enable_skills: bool = False
    skills_root: str = "skills"

    # ── Web / search tools ────────────────────────────────────────────────────
    enable_duckduckgo: bool = False
    enable_brave_search: bool = False
    brave_api_key: str = ""
    enable_website_tools: bool = False

    # ── Custom tools ──────────────────────────────────────────────────────────
    enable_custom_apis: bool = False
    # Each entry: {"name": str, "base_url": str, "api_key": str, "description": str (optional)}
    custom_apis: list = []
    enable_sql_databases: bool = False
    # Each entry: {"name": str, "db_url": str, "description": str (optional)}
    sql_databases: list = []

    # ── Shared model defaults ─────────────────────────────────────────────────
    gemini_search: bool = True
    gemini_url_context: bool = False
    gemini_grounding_threshold: str = ""  # 0.0–1.0; empty = model default
    gemini_thinking_budget: str = ""  # int; empty = model default
    gemini_thinking_level: str = ""  # "low" | "high" | ""
    context_token_budget: str = ""

    # ── Large tool results (empty = default, 0 = off) ─────────────────────────
    # Results longer than this many characters are kept out of the model's
    # context (default 16000) for this many seconds (default 3600).
    tool_result_offload_chars: str | int = ""
    tool_result_ttl_seconds: str | int = ""

    # ── Fast model overrides (empty = inherit shared default) ─────────────────
    fast_search: str = ""
    fast_url_context: str = ""
    fast_grounding_threshold: str = ""
    fast_thinking_budget: str = ""
    fast_thinking_level: str = ""
    fast_context_token_budget: str = ""

    # ── Deep model overrides (empty = inherit shared default) ─────────────────
    deep_search: str = ""
    deep_url_context: str = ""
    deep_grounding_threshold: str = ""
    deep_thinking_budget: str = ""
    deep_thinking_level: str = ""
    deep_context_token_budget: str = ""


def load_config() -> BotConfig:
    if not CONFIG_PATH.exists():
        return BotConfig()
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return BotConfig(**{k: v for k, v in data.items() if v is not None})


def save_config(config: BotConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, allow_unicode=True)


def is_setup_complete() -> bool:
    c = load_config()
    return bool(c.discord_token and c.fast_api_key and c.fast_model)
