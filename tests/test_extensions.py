"""Tests for the custom extensions SDK (dango.extensions)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from dango.extensions import agent_tool, command, command_and_tool, register_tools
from dango.extensions.context import (
    Ctx,
    reset_request_context,
    set_request_context,
)
from dango.extensions.loader import (
    _make_app_command,
    _make_tool_wrapper,
    get_custom_tools,
    register_custom_commands,
)
from dango.extensions.registry import command_specs, clear_registry, tool_specs


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts and ends with an empty registry (it is module-global)."""
    clear_registry()
    yield
    clear_registry()


# ── Registry / decorators ─────────────────────────────────────────────────────
class TestRegistry:
    def test_command_exposes_command_only(self):
        @command(name="ping", description="health")
        def ping(ctx):
            return "pong"

        assert len(command_specs()) == 1
        assert len(tool_specs()) == 0
        spec = command_specs()[0]
        assert spec.name == "ping"
        assert spec.description == "health"

    def test_agent_tool_exposes_tool_only(self):
        @agent_tool()
        def t(x: str):
            return x

        assert len(tool_specs()) == 1
        assert len(command_specs()) == 0

    def test_command_and_tool_exposes_both(self):
        @command_and_tool(name="echo")
        def echo(ctx, text: str):
            return text

        assert len(command_specs()) == 1
        assert len(tool_specs()) == 1

    def test_bare_decorator_uses_function_name(self):
        @command
        def hello(ctx):
            return "hi"

        assert command_specs()[0].name == "hello"

    def test_description_falls_back_to_docstring(self):
        @agent_tool()
        def t(x: str):
            """First line used as description.

            Args:
                x: a value
            """
            return x

        assert tool_specs()[0].description == "First line used as description."


# ── Ctx ─────────────────────────────────────────────────────────────────────
class TestCtx:
    def test_from_agent_reads_request_context(self):
        token = set_request_context(
            {"author_name": "Alice", "channel_id": 42, "guild_name": "G"}
        )
        try:
            ctx = Ctx.from_agent()
        finally:
            reset_request_context(token)
        assert ctx.source == "agent"
        assert ctx.author_name == "Alice"
        assert ctx.channel_id == 42
        assert ctx.guild_name == "G"

    def test_from_agent_defaults_without_context(self):
        ctx = Ctx.from_agent()
        assert ctx.source == "agent"
        assert ctx.author_name == "User"
        assert ctx.channel_id is None

    def test_from_interaction_maps_fields(self):
        interaction = MagicMock()
        interaction.user.display_name = "Bob"
        interaction.user.id = 7
        interaction.channel.id = 100
        interaction.channel.name = "general"
        interaction.guild.id = 200
        interaction.guild.name = "MyGuild"
        ctx = Ctx.from_interaction(interaction)
        assert ctx.source == "discord_command"
        assert ctx.author_name == "Bob"
        assert ctx.author_id == 7
        assert ctx.channel_name == "general"
        assert ctx.guild_id == 200
        assert ctx.interaction is interaction


# ── Tool wrapper ──────────────────────────────────────────────────────────────
class TestToolWrapper:
    def test_wrapper_strips_ctx_from_signature(self):
        @agent_tool()
        def f(ctx, x: str, n: int = 1):
            return f"{x}*{n}"

        wrapper = _make_tool_wrapper(tool_specs()[0])
        params = list(wrapper.__signature__.parameters)
        assert params == ["x", "n"]
        assert "ctx" not in wrapper.__annotations__

    def test_wrapper_annotations_survive_update_wrapper(self):
        # Agno's @tool re-wraps our callable via functools.update_wrapper. On
        # Python 3.14 (PEP 649) update_wrapper copies __annotate__, not
        # __annotations__, so the wrapper must expose __annotate__ or the
        # re-wrapped entrypoint loses its hints and pydantic's validate_call
        # raises KeyError on the first param. Guard against that regression.
        import functools

        @agent_tool()
        def f(ctx, x: str, n: int = 1):
            return f"{x}*{n}"

        wrapper = _make_tool_wrapper(tool_specs()[0])

        def outer(*args, **kwargs):
            return wrapper(*args, **kwargs)

        functools.update_wrapper(outer, wrapper)
        assert outer.__annotations__ == {"x": str, "n": int}

    def test_wrapper_injects_ctx_at_call_time(self):
        @agent_tool()
        def f(ctx, x: str):
            return f"{ctx.author_name}:{x}"

        wrapper = _make_tool_wrapper(tool_specs()[0])
        token = set_request_context({"author_name": "Zoe"})
        try:
            assert wrapper(x="hi") == "Zoe:hi"
        finally:
            reset_request_context(token)

    def test_wrapper_without_ctx_param(self):
        @agent_tool()
        def f(x: str):
            return x.upper()

        wrapper = _make_tool_wrapper(tool_specs()[0])
        assert wrapper(x="abc") == "ABC"

    def test_async_wrapper(self):
        @agent_tool()
        async def f(ctx, x: str):
            return f"async:{x}"

        wrapper = _make_tool_wrapper(tool_specs()[0])
        token = set_request_context({"author_name": "Z"})
        try:
            assert asyncio.run(wrapper(x="y")) == "async:y"
        finally:
            reset_request_context(token)


# ── Integration with Agno ─────────────────────────────────────────────────────
class TestAgnoIntegration:
    def test_get_custom_tools_builds_clean_schema(self):
        @agent_tool(name="multiply", description="multiply text")
        def f(ctx, text: str, times: int = 2):
            return text * times

        tools = get_custom_tools()
        assert len(tools) == 1
        fn = tools[0]
        assert fn.name == "multiply"
        props = fn.parameters["properties"]
        # ctx must not leak into the LLM-facing schema; user params must.
        assert "ctx" not in props
        assert set(props) == {"text", "times"}
        # text has no default -> required; times has a default -> not required.
        assert fn.parameters["required"] == ["text"]

    def test_no_tools_returns_empty_list(self):
        assert get_custom_tools() == []


# ── register_tools (raw toolkits / context providers) ──────────────────────────
class TestRegisterTools:
    def test_single_object_passes_through(self):
        sentinel = object()
        register_tools(sentinel)
        assert sentinel in get_custom_tools()

    def test_list_is_flattened(self):
        # Mirrors register_tools(*provider.get_tools()) and register_tools(provider.get_tools()).
        a, b = object(), object()
        register_tools([a, b])
        tools = get_custom_tools()
        assert a in tools and b in tools

    def test_raw_tools_are_not_slash_commands(self):
        register_tools(object())
        assert command_specs() == []

    def test_combined_with_decorated_tools(self):
        @agent_tool(name="decorated")
        def decorated(x: str):
            return x

        sentinel = object()
        register_tools(sentinel)
        tools = get_custom_tools()
        assert sentinel in tools
        assert "decorated" in [getattr(t, "name", None) for t in tools]


# ── Integration with discord.py ────────────────────────────────────────────────
class TestDiscordIntegration:
    def test_make_app_command_strips_ctx_and_interaction(self):
        @command(name="Roll", description="roll a die")
        def roll(ctx, sides: int = 6):
            return str(sides)

        cmd = _make_app_command(command_specs()[0])
        # Discord command names must be lowercased.
        assert cmd.name == "roll"
        # Neither ctx nor interaction is exposed as a user-facing option.
        param_names = {p.name for p in cmd.parameters}
        assert param_names == {"sides"}

    def test_register_custom_commands_adds_to_tree(self):
        @command(name="ping")
        def ping(ctx):
            return "pong"

        bot = MagicMock()
        added = register_custom_commands(bot)
        assert added == 1
        bot.tree.add_command.assert_called_once()
