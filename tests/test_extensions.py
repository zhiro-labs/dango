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


# ── requires_permissions ──────────────────────────────────────────────────────
def _run_agent_tool(fn, arguments: dict, session_state: dict | None):
    """Run an Agno Function the way an agent run does, with a request context."""
    import copy

    from agno.tools.function import FunctionCall

    f = copy.deepcopy(fn)
    f.process_entrypoint()

    async def go():
        token = set_request_context(session_state)
        try:
            return await FunctionCall(function=f, arguments=arguments).aexecute()
        finally:
            reset_request_context(token)

    return asyncio.run(go())


MOD = {"author_name": "Mod", "guild_id": 1, "author_permissions": ["manage_messages", "send_messages"]}
MEMBER = {"author_name": "Ann", "guild_id": 1, "author_permissions": ["send_messages"]}
DM = {"author_name": "Ann", "guild_id": None, "author_permissions": []}


class TestRequiresPermissions:
    def test_names_are_normalized(self):
        @agent_tool(requires_permissions="manage_guild")
        def a():
            return ""

        @command_and_tool(requires_permissions=["kick_members", "ban_members", "kick_members"])
        def b(ctx):
            return ""

        assert [s.requires_permissions for s in tool_specs()] == [
            ("manage_guild",),
            ("kick_members", "ban_members"),
        ]

    def test_unknown_permission_fails_at_decoration(self):
        # "manage_server" is the Discord UI label; discord.py calls it manage_guild.
        with pytest.raises(ValueError, match="manage_server"):
            @agent_tool(requires_permissions="manage_server")
            def f():
                return ""

        assert tool_specs() == []

    @pytest.mark.parametrize("is_async", [False, True])
    def test_agent_call_allowed_with_permission(self, is_async):
        calls = []
        if is_async:
            @agent_tool(name="purge", requires_permissions="manage_messages")
            async def purge(ctx, n: int = 5):
                calls.append(n)
                return f"{ctx.author_name} purged {n}"
        else:
            @agent_tool(name="purge", requires_permissions="manage_messages")
            def purge(ctx, n: int = 5):
                calls.append(n)
                return f"{ctx.author_name} purged {n}"

        result = _run_agent_tool(get_custom_tools()[0], {"n": 3}, MOD)
        assert result.status == "success"
        assert result.result == "Mod purged 3"
        assert calls == [3]

    @pytest.mark.parametrize("is_async", [False, True])
    def test_agent_call_refused_without_permission(self, is_async):
        calls = []
        if is_async:
            @agent_tool(name="purge", requires_permissions="manage_messages")
            async def purge(n: int = 5):
                calls.append(n)
                return "purged"
        else:
            # No ctx parameter: the check still reads the request context.
            @agent_tool(name="purge", requires_permissions="manage_messages")
            def purge(n: int = 5):
                calls.append(n)
                return "purged"

        result = _run_agent_tool(get_custom_tools()[0], {"n": 3}, MEMBER)
        # A refusal is an answer for the model to relay, not a tool failure.
        assert result.status == "success"
        assert result.result.startswith("Permission denied: 'purge' needs")
        assert "manage_messages" in result.result and "Ann" in result.result
        assert "not performed" in result.result
        assert calls == []

    def test_agent_call_refused_in_dm(self):
        @agent_tool(name="purge", requires_permissions="manage_messages")
        def purge():
            return "purged"

        result = _run_agent_tool(get_custom_tools()[0], {}, DM)
        assert "direct messages" in result.result

    def test_agent_call_refused_without_request_context(self):
        # Fails closed: no context means no permissions.
        @agent_tool(requires_permissions="manage_messages")
        def purge():
            return "purged"

        assert _make_tool_wrapper(tool_specs()[0])().startswith("Permission denied")

    def test_all_required_permissions_must_be_held(self):
        @agent_tool(name="moderate", requires_permissions=["manage_messages", "ban_members"])
        def moderate():
            return "done"

        result = _run_agent_tool(get_custom_tools()[0], {}, MOD)
        assert "ban_members" in result.result and "manage_messages" not in result.result

    def test_ungated_tool_is_unaffected(self):
        @agent_tool()
        def echo(x: str):
            return x

        assert _run_agent_tool(get_custom_tools()[0], {"x": "hi"}, MEMBER).result == "hi"


def _interaction(**permissions):
    import discord
    from unittest.mock import AsyncMock

    interaction = MagicMock()
    interaction.user.display_name = "Ann"
    interaction.user.guild_permissions = discord.Permissions(**permissions)
    interaction.guild.id = 1
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestCommandPermissions:
    def _command(self, calls):
        @command_and_tool(name="purge", requires_permissions="manage_messages")
        async def purge(ctx, n: int = 5):
            calls.append(n)
            return f"purged {n}"

        return _make_app_command(command_specs()[0])

    def test_refused_without_permission(self):
        calls = []
        interaction = _interaction(send_messages=True)
        asyncio.run(self._command(calls).callback(interaction, n=3))

        assert calls == []
        interaction.response.defer.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        text = interaction.response.send_message.await_args.args[0]
        assert "manage_messages" in text
        assert interaction.response.send_message.await_args.kwargs == {"ephemeral": True}

    def test_runs_with_permission(self):
        calls = []
        interaction = _interaction(manage_messages=True)
        asyncio.run(self._command(calls).callback(interaction, n=3))

        assert calls == [3]
        interaction.response.send_message.assert_not_called()
        interaction.followup.send.assert_awaited_once_with("purged 3")

    def test_administrator_passes(self):
        # discord.py's guild_permissions reports every permission for admins.
        import discord

        calls = []
        interaction = _interaction()
        interaction.user.guild_permissions = discord.Permissions.all()
        asyncio.run(self._command(calls).callback(interaction, n=1))
        assert calls == [1]

    def test_gated_command_is_hidden_and_guild_only(self):
        import discord

        cmd = self._command([])
        assert cmd.default_permissions == discord.Permissions(manage_messages=True)
        assert cmd.guild_only is True

    def test_ungated_command_keeps_discord_defaults(self):
        @command(name="ping")
        def ping():
            return "pong"

        cmd = _make_app_command(command_specs()[0])
        assert cmd.default_permissions is None
        assert cmd.guild_only is False


# ── Agno @tool options ────────────────────────────────────────────────────────
def _hook(function_name, function_call, arguments):
    return function_call(**arguments)


# One sample value per option in TOOL_OPTIONS.
OPTION_SAMPLES = {
    "title": "Purge messages",
    "annotations": {"destructiveHint": True},
    "strict": False,
    "instructions": "Only purge when asked.",
    "add_instructions": False,
    "show_result": True,
    "stop_after_tool_call": True,
    "pre_hook": lambda fc: None,
    "post_hook": lambda fc: None,
    "tool_hooks": [_hook],
    "cache_results": True,
    "cache_dir": "/tmp/dango-test-cache",
    "cache_ttl": 60,
}


class TestToolOptions:
    def test_samples_cover_every_supported_option(self):
        from dango.extensions.registry import TOOL_OPTIONS

        assert set(OPTION_SAMPLES) == TOOL_OPTIONS

    @pytest.mark.parametrize("option", sorted(OPTION_SAMPLES))
    def test_option_reaches_agno(self, option):
        # Also catches an Agno upgrade that renames or drops an option.
        value = OPTION_SAMPLES[option]

        @agent_tool(name="t", **{option: value})
        def t(x: str = ""):
            return x

        fn = get_custom_tools()
        assert len(fn) == 1, f"Agno rejected {option}"
        assert getattr(fn[0], option) == value

    def test_command_and_tool_forwards_options(self):
        @command_and_tool(name="t", show_result=True, requires_permissions="manage_guild")
        def t(ctx):
            return ""

        assert get_custom_tools()[0].show_result is True
        assert len(command_specs()) == 1

    @pytest.mark.parametrize("option, value", [
        ("requires_confirmation", True),
        ("requires_user_input", True),
        ("user_input_fields", ["x"]),
        ("external_execution", True),
        ("external_execution_silent", True),
    ])
    def test_hitl_options_are_rejected(self, option, value):
        with pytest.raises(ValueError, match="never resumes a paused run"):
            @agent_tool(**{option: value})
            def t(x: str):
                return x

        assert tool_specs() == []

    def test_agno_approval_decorator_is_rejected(self):
        from agno.approval import approval

        with pytest.raises(ValueError, match="@approval"):
            @agent_tool()
            @approval
            def t(x: str):
                return x

    def test_unknown_option_is_rejected(self):
        with pytest.raises(TypeError, match="cache_result"):
            @agent_tool(cache_result=True)
            def t():
                return ""

    def test_command_takes_no_tool_options(self):
        with pytest.raises(TypeError, match="@command_and_tool"):
            @command(show_result=True)
            def t():
                return ""

    @pytest.mark.parametrize("kind", ["ctx", "permissions"])
    def test_cache_results_rejected_when_result_depends_on_caller(self, kind):
        with pytest.raises(ValueError, match="cache_results"):
            if kind == "ctx":
                @agent_tool(cache_results=True)
                def t(ctx, x: str):
                    return x
            else:
                @agent_tool(cache_results=True, requires_permissions="manage_guild")
                def t(x: str):
                    return x
