"""Helper for wrapping existing Discord bot commands as Agno tools.

Quick start for Neko (or any other bot) developers
====================================================

1. Extract your command's business logic into a plain async function.
2. Decorate it with @discord_tool (an alias for Agno's @tool).
3. Pass the list of tools when loading ChatCog.

The decorator turns any Python function into an Agno tool.  Rules:
  - Add type hints on every parameter and the return value.
  - Write a docstring — the first line becomes the tool description.
  - Add an ``Args:`` block; Agno strips it from the schema and uses it
    to build per-parameter descriptions for the LLM.
  - Async functions work the same as sync ones.

Accessing Discord context inside a tool
----------------------------------------
Dango injects the following into ``session_state`` for every request.
Declare ``run_context: RunContext`` as a parameter and Agno injects it
automatically (NOT exposed to the LLM as a callable parameter).

    author_id    : int | None
    author_name  : str
    author_roles : list[str]   — guild role names, excludes @everyone
    channel_id   : int | None
    channel_name : str
    guild_id     : int | None
    guild_name   : str

Helpers:

    get_discord_context(rc)    → dict of the above
    check_roles(rc, any_of=[]) → str error or None
    get_discord_bot(rc)        → discord.Bot instance
    get_discord_interaction(rc)→ discord.Interaction or None
    set_ephemeral(rc)          → mark response visible only to the sender


Example A — Prefix command (``!play <song>``)
----------------------------------------------
::

    from dango.tools import discord_tool, RunContext, get_discord_context

    @discord_tool(name="play_music")
    async def play_music(song: str, run_context: RunContext) -> str:
        \"""Play music in the voice channel.

        Args:
            song (str): Song name or YouTube/Spotify URL
        \"""
        ctx = get_discord_context(run_context)
        if ctx["guild_id"] is None:
            return "This command can only be used in a server channel."
        await music_player.play(ctx["guild_id"], song)
        return f"Now playing: {song}"


Example B — Role-restricted command
-------------------------------------
::

    from dango.tools import discord_tool, RunContext, check_roles

    @discord_tool(name="ban_user")
    async def ban_user(username: str, reason: str, run_context: RunContext) -> str:
        \"""Ban a user from the server. Requires Moderator or Admin role.

        Args:
            username (str): Display name of the user to ban
            reason (str): Reason for the ban
        \"""
        if err := check_roles(run_context, any_of=["Moderator", "Admin"]):
            return err
        # ... actual logic ...
        return f"Banned {username}: {reason}"


Example C — Ephemeral response (only visible to the sender)
------------------------------------------------------------
::

    from dango.tools import discord_tool, RunContext, set_ephemeral

    @discord_tool(name="get_balance")
    async def get_balance(run_context: RunContext) -> str:
        \"""Check your personal balance. Response is private.\"""
        set_ephemeral(run_context)
        balance = 1000  # ... fetch real data ...
        return f"Your balance: {balance} coins"


Example D — Context menu command (right-click a message or user)
-----------------------------------------------------------------
::

    from dango.commands import ChatCog
    from dango.tools import ContextMenuDef
    from dango.workflow import create_discord_workflow

    workflow = create_discord_workflow()

    await bot.add_cog(ChatCog(
        bot,
        workflow,
        chat_system_prompt,
        runtime_config,
        context_menu_defs=[
            ContextMenuDef(name="Translate", target="message",
                           content_builder=lambda text: f"Translate this to English: {text}"),
            ContextMenuDef(name="User Info", target="user"),
        ],
    ))


Loading into Neko's bot
------------------------
::

    from dango.commands import ChatCog
    from dango.workflow import create_discord_workflow

    workflow = create_discord_workflow()

    await bot.add_cog(ChatCog(
        bot,
        workflow,
        chat_system_prompt,
        runtime_config,
        extra_tools=[play_music, ban_user],
    ))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

from agno.run.base import RunContext
from agno.tools import tool as discord_tool

if TYPE_CHECKING:
    import discord as _discord

__all__ = [
    "discord_tool",
    "RunContext",
    "ContextMenuDef",
    "get_discord_context",
    "get_discord_bot",
    "get_discord_interaction",
    "set_ephemeral",
    "check_roles",
]


@dataclass
class ContextMenuDef:
    """Definition for a Discord context menu command routed through the Dango workflow.

    Args:
        name: Label shown in Discord's right-click menu (max 32 chars).
        target: ``"message"`` for message context menus, ``"user"`` for user context menus.
        content_builder: Optional callable that converts the target's text (message content
            or user display name) into the string injected as the user's message.
            Defaults to a generic ``[Context menu: <name>]\\nTarget: <text>`` format.

    Usage::

        ContextMenuDef(
            name="Translate",
            target="message",
            content_builder=lambda text: f"Translate this message to English: {text}",
        )
    """

    name: str
    target: Literal["message", "user"] = "message"
    content_builder: Callable[[str], str] | None = None

    def build_content(self, target_str: str) -> str:
        if self.content_builder:
            return self.content_builder(target_str)
        label = "message" if self.target == "message" else "user"
        return f"[Context menu: {self.name}]\nTarget {label}: {target_str}"


# ---------------------------------------------------------------------------
# Context accessors
# ---------------------------------------------------------------------------

def get_discord_context(run_context: RunContext) -> dict:
    """Extract Discord request context from Agno's RunContext.

    Returns a dict with keys: author_id, author_name, author_roles,
    channel_id, channel_name, guild_id, guild_name.  All values may be
    None/empty if the message originated from a DM or before context was
    populated.
    """
    state = run_context.session_state or {}
    return {
        "author_id": state.get("author_id"),
        "author_name": state.get("author_name", ""),
        "author_roles": state.get("author_roles", []),
        "channel_id": state.get("channel_id"),
        "channel_name": state.get("channel_name", ""),
        "guild_id": state.get("guild_id"),
        "guild_name": state.get("guild_name", ""),
    }


def get_discord_bot(run_context: RunContext) -> "_discord.Client | None":
    """Return the Discord bot (Client) instance for the current request."""
    state = run_context.session_state or {}
    return state.get("_bot")


def get_discord_interaction(run_context: RunContext) -> "_discord.Interaction | None":
    """Return the Discord Interaction that triggered this request, if any.

    Present when the workflow was initiated by a button click, select menu,
    modal submit, or context menu.  None for ordinary chat messages.
    """
    state = run_context.session_state or {}
    return state.get("_interaction")


def set_ephemeral(run_context: RunContext) -> None:
    """Mark the response as ephemeral (visible only to the invoking user).

    Only effective when the workflow was triggered by a Discord Interaction
    (slash command, button, modal, context menu).  Has no effect for regular
    chat messages, which are always public.
    """
    state = run_context.session_state
    if state is not None:
        state["_ephemeral"] = True


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def check_roles(
    run_context: RunContext,
    any_of: list[str] | None = None,
    all_of: list[str] | None = None,
) -> str | None:
    """Return an error string if the author lacks required roles, else None.

    Args:
        run_context: Agno RunContext injected by the framework.
        any_of: User must have at least one of these role names.
        all_of: User must have every one of these role names.

    Usage::

        @discord_tool(name="ban_user")
        async def ban_user(username: str, run_context: RunContext) -> str:
            if err := check_roles(run_context, any_of=["Moderator", "Admin"]):
                return err
            ...
    """
    ctx = get_discord_context(run_context)
    user_roles = set(ctx["author_roles"])

    if any_of and not user_roles.intersection(any_of):
        needed = " / ".join(any_of)
        return f"❌ This command requires one of these roles: {needed}"

    if all_of and not set(all_of).issubset(user_roles):
        missing = set(all_of) - user_roles
        return f"❌ Missing required roles: {', '.join(sorted(missing))}"

    return None
