import json
import os
from pathlib import Path

import yaml

_DATA_CONFIG = Path(os.getenv("DATA_DIR", "data")) / "config.yaml"


def _onoff(v: bool) -> str:
    return "on" if v else "off"


def inject_config_to_env() -> str | None:
    """Load data/config.yaml and inject its values into os.environ.

    Must be called before any local imports that read os.getenv() at module
    level (e.g. chat_commands.py). Returns the inline chat_sys_prompt if present.
    Returns None if data/config.yaml does not exist (developer .env path).
    """
    if not _DATA_CONFIG.exists():
        return None

    with open(_DATA_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    def _set(key: str, value: object) -> None:
        """Set env var only when value is non-empty."""
        if value is not None and str(value).strip():
            os.environ[key] = str(value)

    # ── Credentials ──────────────────────────────────────────────────────────
    _set("DISCORD_BOT_TOKEN",   cfg.get("discord_token"))
    _set("FAST_API_KEY",        cfg.get("fast_api_key"))
    _set("DEEP_API_KEY",        cfg.get("deep_api_key"))

    # ── Models ───────────────────────────────────────────────────────────────
    _set("FAST_MODEL",          cfg.get("fast_model"))
    _set("DEEP_MODEL",          cfg.get("deep_model"))
    _set("FAST_BASE_URL",       cfg.get("fast_base_url"))
    _set("DEEP_BASE_URL",       cfg.get("deep_base_url"))

    # ── Routing ──────────────────────────────────────────────────────────────
    _set("AUTO_ROUTE",          _onoff(cfg.get("auto_route", False)))
    _set("FALLBACK_ON_ERROR",   _onoff(cfg.get("fallback_on_error", False)))

    # ── Bot behaviour ─────────────────────────────────────────────────────────
    _set("ENABLE_CONTEXTUAL_SYSTEM_PROMPT", _onoff(cfg.get("enable_contextual_system_prompt", True)))
    _set("ENABLE_MESSAGE_BATCHING", _onoff(cfg.get("enable_message_batching", False)))
    _set("MESSAGE_BATCH_WINDOW",   cfg.get("message_batch_window", 5))
    _set("MESSAGE_BATCH_MAX_WAIT", cfg.get("message_batch_max_wait", 15))

    # ── Workspace ────────────────────────────────────────────────────────────
    _set("ENABLE_WORKSPACE",    _onoff(cfg.get("enable_workspace", False)))
    _set("WORKSPACE_ROOT",      cfg.get("workspace_root", "workspace"))

    # ── Skills ───────────────────────────────────────────────────────────────
    _set("ENABLE_SKILLS",       _onoff(cfg.get("enable_skills", False)))
    _set("SKILLS_ROOT",         cfg.get("skills_root", "skills"))

    # ── Web / search tools ────────────────────────────────────────────────────
    _set("ENABLE_DUCKDUCKGO",      _onoff(cfg.get("enable_duckduckgo", False)))
    _set("ENABLE_BRAVE_SEARCH",    _onoff(cfg.get("enable_brave_search", False)))
    _set("BRAVE_API_KEY",          cfg.get("brave_api_key"))
    _set("ENABLE_WEBSITE_TOOLS",   _onoff(cfg.get("enable_website_tools", False)))

    # ── Custom tools ──────────────────────────────────────────────────────────
    _set("ENABLE_CUSTOM_APIS",   _onoff(cfg.get("enable_custom_apis", False)))
    _set("ENABLE_SQL_DATABASES", _onoff(cfg.get("enable_sql_databases", False)))
    os.environ["CUSTOM_APIS_JSON"]     = json.dumps(cfg.get("custom_apis", []))
    os.environ["SQL_DATABASES_JSON"]   = json.dumps(cfg.get("sql_databases", []))

    # ── Shared model defaults ─────────────────────────────────────────────────
    _set("GEMINI_SEARCH",               "true" if cfg.get("gemini_search", True) else "false")
    _set("GEMINI_URL_CONTEXT",          "true" if cfg.get("gemini_url_context", False) else "false")
    _set("GEMINI_GROUNDING_THRESHOLD",  cfg.get("gemini_grounding_threshold"))
    _set("GEMINI_THINKING_BUDGET",      cfg.get("gemini_thinking_budget"))
    _set("GEMINI_THINKING_LEVEL",       cfg.get("gemini_thinking_level"))
    _set("CONTEXT_TOKEN_BUDGET",        cfg.get("context_token_budget"))

    # ── Per-model overrides ───────────────────────────────────────────────────
    for prefix in ("fast", "deep"):
        env = prefix.upper()
        _set(f"{env}_SEARCH",               cfg.get(f"{prefix}_search"))
        _set(f"{env}_URL_CONTEXT",          cfg.get(f"{prefix}_url_context"))
        _set(f"{env}_GROUNDING_THRESHOLD",  cfg.get(f"{prefix}_grounding_threshold"))
        _set(f"{env}_THINKING_BUDGET",      cfg.get(f"{prefix}_thinking_budget"))
        _set(f"{env}_THINKING_LEVEL",       cfg.get(f"{prefix}_thinking_level"))
        _set(f"{env}_CONTEXT_TOKEN_BUDGET", cfg.get(f"{prefix}_context_token_budget"))

    return cfg.get("chat_sys_prompt") or None
