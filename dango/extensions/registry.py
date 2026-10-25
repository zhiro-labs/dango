"""Registry and decorators for user-defined commands and agent tools.

Developers drop ``.py`` files into the ``custom/`` directory (gitignored) and
decorate their functions with one of:

    @command           -> a Discord slash command only
    @agent_tool        -> an Agent tool only (callable by the LLM)
    @command_and_tool  -> both at once (one function, two entry points)

The decorators only record a spec here. The loader (``loader.py``) turns these
specs into real Discord slash commands and Agno tools at startup. Whether the
agent may call a function is decided purely by which decorator is used — there
is no global switch, so exposure is always an explicit per-function opt-in.

Each decorator also takes ``requires_permissions`` (Discord permission names
the caller must hold, checked by the loader on every call), and the two tool
decorators pass other keyword arguments to Agno's ``@tool``. Options that
cannot work in Dango are rejected here, when the file is imported.
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Union

# Agno @tool options that @agent_tool / @command_and_tool pass through as is.
TOOL_OPTIONS = frozenset({
    "title",
    "annotations",
    "strict",
    "instructions",
    "add_instructions",
    "show_result",
    "stop_after_tool_call",
    "pre_hook",
    "post_hook",
    "tool_hooks",
    "cache_results",
    "cache_dir",
    "cache_ttl",
})

# Agno options that pause the run until a human answers (human-in-the-loop).
# Dango's Discord flow never resumes a paused run, so the reply would never come.
HITL_OPTIONS = frozenset({
    "requires_confirmation",
    "requires_user_input",
    "user_input_fields",
    "external_execution",
    "external_execution_silent",
})


@dataclass
class ExtensionSpec:
    """One registered custom function and how it should be exposed."""

    fn: Callable
    name: str
    description: str
    expose_command: bool
    expose_tool: bool
    # Discord permission names the caller must all hold (e.g. "manage_guild").
    requires_permissions: tuple[str, ...] = ()
    # Extra Agno @tool options for the agent tool (see TOOL_OPTIONS).
    tool_options: dict[str, Any] = field(default_factory=dict)


# Populated at import time, when the loader imports each custom/*.py file.
_REGISTRY: list[ExtensionSpec] = []

# Raw Agno tools/toolkits/context-provider tools registered via register_tools().
_RAW_TOOLS: list = []


def _first_doc_line(fn: Callable) -> str:
    doc = (fn.__doc__ or "").strip()
    return doc.split("\n", 1)[0].strip() if doc else ""


def _permission_names(requires_permissions: Union[str, Iterable[str], None]) -> tuple[str, ...]:
    """Normalize and check requires_permissions against discord.py's names."""
    if not requires_permissions:
        return ()
    if isinstance(requires_permissions, str):
        requires_permissions = [requires_permissions]
    names = tuple(dict.fromkeys(requires_permissions))

    import discord

    unknown = [n for n in names if n not in discord.Permissions.VALID_FLAGS]
    if unknown:
        # A typo would otherwise lock everyone out without saying why.
        raise ValueError(
            f"Unknown Discord permission(s) {unknown}. Use discord.py names such as "
            "'manage_guild', 'manage_messages' or 'administrator'."
        )
    return names


def _check_tool_options(
    fn: Callable,
    tool_options: dict[str, Any],
    requires_permissions: tuple[str, ...],
    *,
    expose_tool: bool,
) -> None:
    """Reject Agno options that cannot work in Dango, at decoration time."""
    if tool_options and not expose_tool:
        raise TypeError(
            f"@command does not take Agno tool options: {sorted(tool_options)}. "
            "Use @command_and_tool to also expose the function to the agent."
        )

    hitl = sorted(set(tool_options) & HITL_OPTIONS)
    if hitl or getattr(fn, "_agno_approval_type", None) is not None:
        raise ValueError(
            f"{hitl or '@approval'} pauses the agent run until someone answers, and "
            "Dango's Discord flow never resumes a paused run. Use requires_permissions "
            "to limit who can trigger the tool, or keep the action on @command."
        )

    unknown = sorted(set(tool_options) - TOOL_OPTIONS)
    if unknown:
        raise TypeError(
            f"Unknown Agno tool option(s) {unknown}. Supported: {sorted(TOOL_OPTIONS)}."
        )

    if tool_options.get("cache_results"):
        params = list(inspect.signature(fn).parameters)
        if requires_permissions or (params and params[0] == "ctx"):
            # Agno keys the cache on the model's arguments only. A cached result
            # would skip the permission check and could be served to another
            # user, channel or server, since Ctx is not part of the key.
            raise ValueError(
                "cache_results cannot be combined with requires_permissions or a ctx "
                "parameter: the cache key only covers the model's arguments, so a "
                "cached result would be shared across callers and skip the check."
            )


def _register(
    fn: Callable,
    name: Optional[str],
    description: str,
    *,
    expose_command: bool,
    expose_tool: bool,
    requires_permissions: Union[str, Iterable[str], None] = None,
    tool_options: Optional[dict[str, Any]] = None,
) -> Callable:
    tool_options = dict(tool_options or {})
    permissions = _permission_names(requires_permissions)
    _check_tool_options(fn, tool_options, permissions, expose_tool=expose_tool)
    _REGISTRY.append(
        ExtensionSpec(
            fn=fn,
            name=name or fn.__name__,
            description=description or _first_doc_line(fn),
            expose_command=expose_command,
            expose_tool=expose_tool,
            requires_permissions=permissions,
            tool_options=tool_options,
        )
    )
    return fn


def _make_decorator(*, expose_command: bool, expose_tool: bool):
    """Build a decorator that supports @deco, @deco("name") and @deco(name=..., description=...).

    Keyword-only extras:
        requires_permissions: Discord permission name(s) the caller must all
            hold, checked on every call from the agent and from Discord.
        **tool_options: Agno @tool options for the agent tool (TOOL_OPTIONS);
            not accepted by @command.
    """

    def decorator(
        name=None,
        description: str = "",
        *,
        requires_permissions: Union[str, Iterable[str], None] = None,
        **tool_options: Any,
    ):
        # Bare usage: @command applied directly to a function.
        if callable(name):
            return _register(
                name, None, "", expose_command=expose_command, expose_tool=expose_tool
            )

        def wrap(fn: Callable) -> Callable:
            return _register(
                fn,
                name,
                description,
                expose_command=expose_command,
                expose_tool=expose_tool,
                requires_permissions=requires_permissions,
                tool_options=tool_options,
            )

        return wrap

    return decorator


command = _make_decorator(expose_command=True, expose_tool=False)
"""Register a Discord slash command. Not exposed to the agent."""

agent_tool = _make_decorator(expose_command=False, expose_tool=True)
"""Register an Agent tool the LLM can call. No Discord slash command."""

command_and_tool = _make_decorator(expose_command=True, expose_tool=True)
"""Register a function as BOTH a Discord slash command and an Agent tool."""


def register_tools(*tools) -> None:
    """Attach raw Agno tools/toolkits/context providers to the agent.

    For anything that is not a single decorated function — an Agno ``Toolkit``
    instance, or the list produced by a context provider's ``get_tools()`` — call
    this from a ``custom/*.py`` file so it reaches the agent without editing core
    code. Accepts plain functions, ``@tool`` functions, Toolkit instances, or
    lists/tuples of any of these::

        from dango.extensions import register_tools
        from agno.context.gdrive import GoogleDriveContextProvider

        register_tools(*GoogleDriveContextProvider().get_tools())

    These are exposed to the agent only; they are never turned into Discord slash
    commands.
    """
    for t in tools:
        if isinstance(t, (list, tuple)):
            _RAW_TOOLS.extend(t)
        else:
            _RAW_TOOLS.append(t)


def command_specs() -> list[ExtensionSpec]:
    return [s for s in _REGISTRY if s.expose_command]


def tool_specs() -> list[ExtensionSpec]:
    return [s for s in _REGISTRY if s.expose_tool]


def raw_tools() -> list:
    return list(_RAW_TOOLS)


def clear_registry() -> None:
    """Reset the registry. Used by tests and (later) hot-reload."""
    _REGISTRY.clear()
    _RAW_TOOLS.clear()
