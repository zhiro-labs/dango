"""Dango tool helpers for third-party bot integration."""

from .discord_tool import (
    ContextMenuDef,
    RunContext,
    check_permissions,
    check_roles,
    discord_tool,
    get_discord_bot,
    get_discord_context,
    get_discord_interaction,
    set_discord_response,
    set_ephemeral,
)

__all__ = [
    "discord_tool",
    "RunContext",
    "ContextMenuDef",
    "get_discord_context",
    "get_discord_bot",
    "get_discord_interaction",
    "set_ephemeral",
    "set_discord_response",
    "check_roles",
    "check_permissions",
]
