---
summary: "Embedding SDK reference — symbols re-exported from the `dango` package (ChatCog, AdminCog, create_discord_workflow, RuntimeConfig) and the `dango.extensions` custom-tool API (@command, @agent_tool, @command_and_tool, register_tools, Ctx)."
---

# API Reference

The core embedding symbols are re-exported from the `dango` top-level package.
The custom-extension SDK lives in `dango.extensions`.

## Quick import table

```python
from dango import (
    # Cogs
    ChatCog,
    AdminCog,

    # Workflow
    create_discord_workflow,

    # Config
    RuntimeConfig,
)

# Custom commands & tools (used inside custom/*.py — see the feature guide)
from dango.extensions import command, agent_tool, command_and_tool, Ctx
```

## Where things live

| Symbol | Top-level import | Sub-module (also works) |
|---|---|---|
| `ChatCog` | `from dango import ChatCog` | `from dango.commands import ChatCog` |
| `AdminCog` | `from dango import AdminCog` | `from dango.commands import AdminCog` |
| `create_discord_workflow` | `from dango import create_discord_workflow` | `from dango.workflow import create_discord_workflow` |
| `RuntimeConfig` | `from dango import RuntimeConfig` | `from dango.utils.runtime_config import RuntimeConfig` |
| `command` | — | `from dango.extensions import command` |
| `agent_tool` | — | `from dango.extensions import agent_tool` |
| `command_and_tool` | — | `from dango.extensions import command_and_tool` |
| `Ctx` | — | `from dango.extensions import Ctx` |

## Core symbols

### `ChatCog`

Discord.py Cog that handles incoming messages. Wraps the Agno workflow and routes Discord events into the four-step pipeline.

**Constructor:**

```python
ChatCog(
    bot: commands.Bot,
    discord_workflow: Workflow,
    chat_system_prompt: str,
    runtime_config: RuntimeConfig,
)
```

### `AdminCog`

Discord.py Cog that registers admin slash commands (`/addchannel`, `/adduser`, etc.). Requires the **Administrator** server permission for all commands.

**Constructor:**

```python
AdminCog(bot: commands.Bot, runtime_config: RuntimeConfig)
```

### `create_discord_workflow()`

Creates and returns the Agno `Workflow` object. Call once at startup; pass the result to `ChatCog`.

### `RuntimeConfig(config_path)`

Loads and manages `config/runtime.yml`. Stores allowed channels, allowed DM users, history limit, timezone, and activity string. Pass the same instance to both `ChatCog` and `AdminCog`.

## Custom extensions (`dango.extensions`)

These are what you use inside `custom/*.py`. See
[Custom Commands & Tools](../features/extensions.md) for the full guide.

### Decorators

Each decorator registers a function and supports bare usage (`@command`),
positional (`@command("name")`), or keyword (`@command(name=..., description=...)`).

| Decorator | Discord slash command | Agent tool |
|---|:---:|:---:|
| `command(name=None, description="", *, requires_permissions=None)` | ✅ | ❌ |
| `agent_tool(name=None, description="", *, requires_permissions=None, **tool_options)` | ❌ | ✅ |
| `command_and_tool(name=None, description="", *, requires_permissions=None, **tool_options)` | ✅ | ✅ |

When `name` is omitted the function name is used; when `description` is omitted
the first line of the docstring is used. A leading `ctx` parameter is optional
and is stripped from the public command/tool schema.

- `requires_permissions`: a discord.py permission name or a list of them
  (e.g. `"manage_guild"`). The caller must hold all of them, checked on every
  call from the agent and from Discord. Unknown names raise `ValueError`.
- `**tool_options`: passed to Agno's `@tool` — `show_result`,
  `stop_after_tool_call`, `instructions`, `add_instructions`, `pre_hook`,
  `post_hook`, `tool_hooks`, `cache_results`, `cache_dir`, `cache_ttl`, `title`,
  `annotations`, `strict`. Human-in-the-loop options and `cache_results`
  combined with `ctx` or `requires_permissions` raise `ValueError`; other names
  raise `TypeError`.

See [Restricting who can call a function](../features/extensions.md#restricting-who-can-call-a-function)
and [Agno tool options](../features/extensions.md#agno-tool-options).

### `register_tools(*tools)`

Attach raw Agno tools to the agent — plain functions, `@tool` functions,
`Toolkit` instances, or lists such as a context provider's `get_tools()`. Lists
and tuples are flattened. Call it from a `custom/*.py` file; everything passed is
exposed to the agent only (never a slash command).

```python
from dango.extensions import register_tools
from agno.context.gdrive import GoogleDriveContextProvider

register_tools(*GoogleDriveContextProvider().get_tools())
```

### `Ctx`

Dataclass describing where a function was invoked from, passed as the first
argument when the function declares `ctx`.

| Attribute | Type |
|---|---|
| `source` | `str` — `"discord_command"` or `"agent"` |
| `author_name` | `str` |
| `author_id` | `int \| None` |
| `channel_id` | `int \| None` |
| `channel_name` | `str` |
| `guild_id` | `int \| None` |
| `guild_name` | `str` |
| `mentioned_user_ids` | `list[int]` (agent path only) |
| `mentioned_role_ids` | `list[int]` (agent path only) |
| `author_permissions` | `list[str]` (empty in DMs) |
| `interaction` | `discord.Interaction \| None` (command path only) |
| `bot` | `commands.Bot \| None` (command path only) |

### Loader functions

Called by the app at startup; you normally don't call these yourself.

| Function | Effect |
|---|---|
| `load_custom_modules()` | Import every `custom/*.py` once so decorators register. Idempotent. |
| `get_custom_tools()` | Return the registered tools as Agno tool objects for the agent. |
| `register_custom_commands(bot)` | Add the registered slash commands to `bot.tree`; returns the count. |
