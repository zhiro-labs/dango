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
Dango injects the following keys into ``session_state`` for every request.
Declare ``run_context: RunContext`` as a parameter and Agno injects it
automatically (it is NOT exposed to the LLM as a callable parameter).

    channel_id   : int | None
    channel_name : str
    guild_id     : int | None
    guild_name   : str
    author_name  : str

Use the ``get_discord_context`` helper to read them in one call.


Example A — Prefix command (``!play <song>``)
----------------------------------------------
::

    # Before: original Neko command
    @bot.command()
    async def play(ctx: commands.Context, *, song: str):
        await music_player.play(ctx.guild.id, ctx.voice_client, song)
        await ctx.send(f"Now playing: {song}")

    # After: extract logic, wrap as tool
    from dango.tools import discord_tool, RunContext, get_discord_context

    @discord_tool(name="play_music", description="Play a song or URL in the voice channel")
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

    # Keep the original command working unchanged:
    @bot.command()
    async def play(ctx: commands.Context, *, song: str):
        result = await music_player.play(ctx.guild.id, song)
        await ctx.send(result)


Example B — Slash command (``/volume <level>``)
-----------------------------------------------
::

    from discord import app_commands
    from dango.tools import discord_tool

    # Slash command stays as-is
    @app_commands.command(name="volume", description="Set the playback volume")
    @app_commands.describe(level="Volume level 0-100")
    async def volume_cmd(interaction: discord.Interaction, level: int):
        result = await _set_volume(interaction.guild_id, level)
        await interaction.response.send_message(result)

    # Agno tool wraps the same extracted logic
    @discord_tool(name="set_volume", description="Set the playback volume in the voice channel")
    async def set_volume(level: int, run_context: RunContext) -> str:
        \"""Set the playback volume.

        Args:
            level (int): Volume level between 0 and 100
        \"""
        ctx = get_discord_context(run_context)
        return await _set_volume(ctx["guild_id"], level)

    async def _set_volume(guild_id: int | None, level: int) -> str:
        if not 0 <= level <= 100:
            return "Volume must be between 0 and 100."
        # ... actual logic ...
        return f"Volume set to {level}%"


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
        extra_tools=[play_music, set_volume],   # ← pass your tools here
    ))
"""

from agno.run.base import RunContext
from agno.tools import tool as discord_tool

__all__ = ["discord_tool", "RunContext", "get_discord_context", "check_roles"]


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
