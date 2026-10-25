"""Discover and load user-defined extensions from the ``custom/`` directory.

The directory is gitignored, so a clean checkout may not have it at all. A
missing directory, an empty directory, or a single broken file must never
crash the bot — failures are logged and skipped.

Public entry points:

    load_custom_modules()         -> import custom/*.py so decorators register
    get_custom_tools()            -> Agno tool objects for the agent's tools=[]
    register_custom_commands(bot) -> add slash commands to bot.tree
"""

import functools
import importlib.util
import inspect
import os
from pathlib import Path
from typing import Any, Callable, Optional, get_type_hints

from .context import Ctx
from .registry import ExtensionSpec, command_specs, raw_tools, tool_specs

_loaded = False


def load_custom_modules() -> None:
    """Import every ``custom/*.py`` once so the decorators populate the registry.

    Idempotent: safe to call from both the agent factory and the bot setup hook.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True

    custom_dir = Path(os.getenv("CUSTOM_DIR", "custom")).resolve()
    if not custom_dir.is_dir():
        return

    for py in sorted(custom_dir.glob("*.py")):
        if py.name.endswith(".example"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"dango_custom_{py.stem}", py)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"🧩 [custom] loaded {py.name}")
        except Exception as e:
            print(f"⚠️  [custom] failed to load {py.name}: {e}")


# ── Shared signature handling ────────────────────────────────────────────────
def _split_ctx(fn: Callable) -> tuple[inspect.Signature, list[inspect.Parameter], bool]:
    """Return (signature, user_params, has_ctx).

    A leading parameter literally named ``ctx`` is treated as the framework
    context and is stripped from the public-facing parameter list.
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    has_ctx = bool(params) and params[0].name == "ctx"
    user_params = params[1:] if has_ctx else params
    return sig, user_params, has_ctx


def _resolved_hints(fn: Callable) -> dict[str, Any]:
    """Resolve a function's type hints against its own module globals.

    Done here (not inside a wrapper) so string annotations from
    ``from __future__ import annotations`` resolve correctly before we hand a
    synthetic callable to Agno / discord.py.
    """
    try:
        return get_type_hints(fn)
    except Exception:
        return {}


# ── Permission checks ────────────────────────────────────────────────────────
def _missing_permissions(spec: ExtensionSpec, ctx: Ctx) -> list[str]:
    """The required permissions the caller lacks (empty when allowed).

    ctx.author_permissions comes from the Discord message or interaction, never
    from the model, so the model cannot talk its way past this check. It is
    discord.py's guild_permissions, which already counts server owners and
    administrators as holding every permission.
    """
    held = set(ctx.author_permissions)
    return [p for p in spec.requires_permissions if p not in held]


def _denied_text(spec: ExtensionSpec, missing: list[str], ctx: Ctx) -> str:
    needed = ", ".join(missing)
    if ctx.guild_id is None:
        return (
            f"Permission denied: '{spec.name}' needs the Discord permission(s) {needed}, "
            "which only exist in a server, so it cannot be used in direct messages."
        )
    return (
        f"Permission denied: '{spec.name}' needs the Discord permission(s) {needed}, "
        f"which {ctx.author_name} does not have."
    )


# ── Agent tools ──────────────────────────────────────────────────────────────
def _make_tool_wrapper(spec: ExtensionSpec) -> Callable:
    """Wrap a custom function as a clean callable for Agno's @tool.

    The wrapper exposes only the user's own parameters (a leading ``ctx`` is
    removed), sources Ctx from the request ContextVar at call time, and refuses
    the call when the caller lacks spec.requires_permissions.
    """
    fn = spec.fn
    _, user_params, has_ctx = _split_ctx(fn)
    hints = _resolved_hints(fn)
    gated = bool(spec.requires_permissions)

    def _prepare() -> tuple[Optional[str], tuple]:
        """(refusal text or None, leading args for fn)."""
        if not (has_ctx or gated):
            return None, ()
        ctx = Ctx.from_agent()
        missing = _missing_permissions(spec, ctx) if gated else []
        if missing:
            print(f"⛔ [custom] tool '{spec.name}' refused for {ctx.author_name}: missing {missing}")
            # Told to the model, which explains it to the user. Not an exception,
            # so the run treats it as an answer rather than a tool failure.
            return _denied_text(spec, missing, ctx) + " The action was not performed.", ()
        return None, ((ctx,) if has_ctx else ())

    is_async = inspect.iscoroutinefunction(fn)
    if is_async:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            refusal, lead = _prepare()
            if refusal is not None:
                return refusal
            return await fn(*lead, *args, **kwargs)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            refusal, lead = _prepare()
            if refusal is not None:
                return refusal
            return fn(*lead, *args, **kwargs)

    # Present only the user params to Agno's signature/type-hint introspection.
    wrapper.__signature__ = inspect.Signature(parameters=user_params)
    annotations = {p.name: hints[p.name] for p in user_params if p.name in hints}
    if "return" in hints:
        annotations["return"] = hints["return"]
    wrapper.__annotations__ = annotations
    # Py3.14 (PEP 649): functools.update_wrapper copies __annotate__, not
    # __annotations__. Agno's @tool wraps this callable again via update_wrapper;
    # without __annotate__ the re-wrapped entrypoint loses its annotations while
    # keeping __signature__, and pydantic's validate_call then raises KeyError on
    # the first param. Set __annotate__ so the annotations survive re-wrapping.
    wrapper.__annotate__ = lambda _format, _ann=annotations: dict(_ann)
    return wrapper


def get_custom_tools() -> list:
    """Build the agent's custom tool list.

    Combines decorated @agent_tool / @command_and_tool functions with any raw
    tools/toolkits/context-provider tools registered via register_tools().
    """
    tools = []

    specs = tool_specs()
    if specs:
        from agno.tools import tool

        for spec in specs:
            wrapper = _make_tool_wrapper(spec)
            try:
                tools.append(
                    tool(
                        name=spec.name,
                        description=spec.description or None,
                        **spec.tool_options,
                    )(wrapper)
                )
            except Exception as e:
                print(f"⚠️  [custom] could not register tool '{spec.name}': {e}")

    # Raw Agno toolkits / context-provider tools registered via register_tools().
    tools.extend(raw_tools())
    return tools


# ── Discord slash commands ────────────────────────────────────────────────────
def _make_app_command(spec: ExtensionSpec):
    """Build a discord.py app_commands.Command from a command spec."""
    import discord
    from discord import app_commands

    fn = spec.fn
    _, user_params, has_ctx = _split_ctx(fn)
    hints = _resolved_hints(fn)
    is_async = inspect.iscoroutinefunction(fn)

    async def callback(interaction: "discord.Interaction", **kwargs):
        ctx = Ctx.from_interaction(interaction, getattr(interaction, "client", None))
        missing = _missing_permissions(spec, ctx)
        if missing:
            print(f"⛔ [custom] command '{spec.name}' refused for {ctx.author_name}: missing {missing}")
            await interaction.response.send_message(f"⛔ {_denied_text(spec, missing, ctx)}", ephemeral=True)
            return
        try:
            await interaction.response.defer()
            if is_async:
                result = await fn(ctx, **kwargs) if has_ctx else await fn(**kwargs)
            else:
                result = fn(ctx, **kwargs) if has_ctx else fn(**kwargs)
        except Exception as e:
            print(f"❌ [custom] command '{spec.name}' failed: {e}")
            try:
                await interaction.followup.send(f"⚠️ Command error: {e}", ephemeral=True)
            except Exception:
                pass
            return
        await interaction.followup.send(str(result) if result is not None else "✅")

    # Build the callback signature discord.py introspects: (interaction, *user_params).
    interaction_param = inspect.Parameter(
        "interaction",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=discord.Interaction,
    )
    rebuilt = [
        p.replace(
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=hints.get(p.name, p.annotation),
        )
        for p in user_params
    ]
    callback.__signature__ = inspect.Signature([interaction_param, *rebuilt])
    callback.__annotations__ = {
        "interaction": discord.Interaction,
        **{p.name: hints[p.name] for p in user_params if p.name in hints},
    }
    callback.__name__ = spec.name

    description = (spec.description or "Custom command").strip()[:100]
    cmd = app_commands.Command(name=spec.name.lower(), description=description, callback=callback)
    if spec.requires_permissions:
        # Discord hides the command from members without these permissions and
        # from DMs. Server admins can change who sees it under Integrations, so
        # the check in callback stays the one that decides.
        cmd.default_permissions = discord.Permissions(**{p: True for p in spec.requires_permissions})
        app_commands.guild_only(cmd)
    return cmd


def register_custom_commands(bot) -> int:
    """Add every command spec to the bot's app command tree. Returns the count added."""
    specs = command_specs()
    added = 0
    for spec in specs:
        try:
            bot.tree.add_command(_make_app_command(spec))
            added += 1
        except Exception as e:
            print(f"⚠️  [custom] could not register command '{spec.name}': {e}")
    if added:
        print(f"🧩 [custom] registered {added} slash command(s)")
    return added
