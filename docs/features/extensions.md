---
summary: "Write your own Discord slash commands and agent tools in Python in a gitignored custom/ directory. Three decorators — @command, @agent_tool, @command_and_tool — with per-function opt-in for agent access. One function can be both a slash command and an LLM-callable tool; a normalized Ctx works across both call paths. requires_permissions gates a function on the caller's Discord permissions on both paths, and Agno @tool options (show_result, tool_hooks, cache_results, ...) pass through; human-in-the-loop options are rejected. register_tools() attaches any Agno toolkit or context provider (Drive, Gmail, Calendar, Slack, etc.) to the agent without editing core code."
description: "Write your own Discord slash commands and agent tools in Python, drop them into a gitignored custom/ directory, and let the agent call them — one function can be both a slash command and an LLM-callable tool."
tags:
  - Tools
  - Slash Commands
  - Custom code
  - Developers
---

# Custom Commands & Tools

Dango ships two ways to extend what the bot can do:

| Approach | Who it's for | Where |
|---|---|---|
| **No-code** — HTTP API & SQL tools configured as JSON / in the dashboard | Operators, non-developers | [Tools](tools.md#custom-api-tools) |
| **Code** — your own Python commands and agent tools | Developers | **this page** |

This page covers the **code** path: you write Python functions, drop them into a
`custom/` directory, and they become Discord slash commands, agent tools, or both.

## Git-safe by design

Everything you put in `custom/` (except the tracked templates and `README.md`) is
**gitignored**. Your code never shows up in `git status` and survives `git pull` —
no merge conflicts, no accidental commits of private logic or keys.

## Quick start

```bash
cp custom/commands.py.example custom/commands.py
cp custom/tools.py.example    custom/tools.py
# edit them, then restart the bot
```

Any `*.py` file in `custom/` is auto-loaded at startup. Use any filenames you like
and split your code across as many files as you want.

## The three decorators

```python
from dango.extensions import command, agent_tool, command_and_tool, Ctx
```

| Decorator | Discord slash command | Callable by the agent |
|---|:---:|:---:|
| `@command` | ✅ | ❌ |
| `@agent_tool` | ❌ | ✅ |
| `@command_and_tool` | ✅ | ✅ |

Whether the agent can call your function is decided **only** by the decorator —
there is no global switch, so exposing a function to the LLM is always an explicit,
per-function opt-in. For privileged actions, add
[`requires_permissions`](#restricting-who-can-call-a-function) so only members
with the right Discord permission can trigger them, from chat or as a command.

## A command the agent can also call

```python
from dango.extensions import command_and_tool, Ctx

@command_and_tool(name="stock", description="Get a stock quote by ticker")
async def stock(ctx: Ctx, ticker: str) -> str:
    """Look up the latest price for a stock ticker.

    Args:
        ticker: The stock symbol, e.g. AAPL.
    """
    data = await fetch_quote(ticker)
    return f"{ticker}: ${data['price']} ({data['pct']}%)"
```

That single function gives you:

- a `/stock ticker:AAPL` slash command in Discord, and
- a `stock` tool the model can call on its own when a user asks *"how's Apple doing?"*

## Writing a function

- **Return a string.** As a command it is sent as the reply; as a tool it is
  returned to the model. Return `None` and a command just acknowledges with ✅.
- **`ctx` is optional.** Declare `ctx: Ctx` as the **first** parameter to receive
  call context. Omit it if you don't need it.
- **Use scalar parameters for `@command_and_tool`** (`str`, `int`, `bool`,
  `float`) so both the Discord command schema and the agent tool schema can
  represent them. `@command`-only functions may use richer Discord types
  (`discord.Member`, `discord.Attachment`, …).
- **Write a docstring with an `Args:` section.** The agent reads it to decide when
  and how to call your tool, so be descriptive.
- **`async def` and `def` are both supported.**

## The `Ctx` object

`ctx` normalizes the two call paths so one function body works for both.

| Attribute | Type | Notes |
|---|---|---|
| `ctx.source` | `str` | `"discord_command"` or `"agent"` |
| `ctx.author_name` | `str` | Display name of the user |
| `ctx.author_id` | `int \| None` | The caller's Discord user ID |
| `ctx.channel_id` | `int \| None` | |
| `ctx.channel_name` | `str` | |
| `ctx.guild_id` | `int \| None` | |
| `ctx.guild_name` | `str` | |
| `ctx.mentioned_user_ids` | `list[int]` | IDs of members the message tagged. Agent path only — empty for slash commands |
| `ctx.mentioned_role_ids` | `list[int]` | IDs of roles the message tagged. Agent path only — empty for slash commands |
| `ctx.author_permissions` | `list[str]` | Permission names the caller holds in the guild (e.g. `"manage_guild"`). Empty in DMs |
| `ctx.interaction` | `discord.Interaction \| None` | Only on the command path |
| `ctx.bot` | `commands.Bot \| None` | Only on the command path |

Branch on `ctx.source` when a function needs to behave differently depending on
who called it:

```python
@command_and_tool(name="whoami")
def whoami(ctx: Ctx) -> str:
    if ctx.source == "discord_command":
        return f"You ran /whoami in #{ctx.channel_name}."
    return f"{ctx.author_name} is asking via chat."
```

### Mentions and permissions

When a user @-mentions members or roles in a chat message, the framework hands
your tool the **exact IDs** — no need to fuzzy-match display names against the
guild's member or role list. Because Discord mention syntax is built straight
from the ID (`<@user_id>`, `<@&role_id>`), a tool can echo a real, clickable
ping back into the channel using only what's on `ctx`:

```python
@agent_tool(name="page_role")
def page_role(ctx: Ctx) -> str:
    # "page @Moderator about this"  →  precise role IDs, already resolved.
    if not ctx.mentioned_role_ids:
        return "Tag a role to page."
    mentions = " ".join(f"<@&{rid}>" for rid in ctx.mentioned_role_ids)
    return f"Paging {mentions} 🍡"
```

`ctx.author_permissions` holds the caller's own Discord permissions. To
require a permission for the whole function, use
[`requires_permissions`](#restricting-who-can-call-a-function); check
`ctx.author_permissions` yourself only for finer rules, such as letting
everyone list items but only moderators delete other people's:

```python
    if owner_id != ctx.author_id and "manage_messages" not in ctx.author_permissions:
        return "Only the owner or a moderator can delete this."
```

::: info Mention/permission fields and the agent path
`mentioned_user_ids` and `mentioned_role_ids` come from the triggering chat
message, so they populate on the **agent path** and are empty for slash
commands (which carry no message mentions). `author_permissions` is
populated on **both** paths but is empty in DMs, where there is no guild to
grant permissions.
:::

::: warning Acting on the IDs needs a Discord client
The IDs identify who was tagged, but mutating Discord state (adding roles,
fetching members) needs a `discord.py` client. `ctx.bot` is set **only on
the command path** — on the agent path it is `None`. So agent-path tools can
*reference* mentioned users/roles (build mention strings, gate on
permissions, return them for the model to reason about) but cannot perform
member/role mutations directly.
:::

## Restricting who can call a function

`requires_permissions` takes one Discord permission name or a list; the caller
must hold **all** of them. It works on all three decorators:

```python
from dango.extensions import agent_tool, Ctx

@agent_tool(name="delete_event", requires_permissions="manage_events")
async def delete_event(ctx: Ctx, title: str) -> str:
    """Delete a scheduled event.

    Args:
        title: The event title.
    """
    ...
```

- **Checked on every call.** Before your function runs, Dango compares the
  list with the caller's Discord permissions. Those come from the Discord
  message or interaction, never from the model, so a prompt cannot get past the
  check. Server owners and administrators hold every permission.
- **Agent path:** when the caller lacks a permission, your function is not
  called; the model gets a short refusal naming the missing permission and
  tells the user. DMs have no server permissions, so gated tools are always
  refused there.
- **Command path:** the caller gets an ephemeral refusal. The slash command is
  also registered as server-only and hidden from members without the
  permissions (Discord's default member permissions). Server admins can change
  who sees it under **Server Settings → Integrations**; the check still applies.
- **Names are discord.py's**, as on
  [`discord.Permissions`](https://discordpy.readthedocs.io/en/stable/api.html#discord.Permissions):
  `manage_guild` (shown as *Manage Server* in Discord), `manage_messages`,
  `manage_events`, `kick_members`, `administrator`, … An unknown name stops the
  file from loading, with the error in the log, rather than locking everyone out.

## Agno tool options

`@agent_tool` and `@command_and_tool` pass other keyword arguments to Agno's
[`@tool`](https://docs.agno.com/tools/creating-tools/python-functions):

```python
@agent_tool(name="server_stats", show_result=True, cache_results=True, cache_ttl=600)
def server_stats(period: str = "week") -> str:
    ...
```

| Option | Effect |
|---|---|
| `show_result` | Add the tool's output to the reply as is |
| `stop_after_tool_call` | End the run after this tool; its output becomes the reply |
| `instructions`, `add_instructions` | Extra instructions for using the tool, added to the system prompt |
| `pre_hook`, `post_hook`, `tool_hooks` | Run your own code before/after the call ([Agno tool hooks](https://docs.agno.com/tools/hooks)) |
| `cache_results`, `cache_dir`, `cache_ttl` | Reuse the result for repeated calls with the same arguments |
| `title`, `annotations`, `strict` | Display name, MCP behaviour hints, strict parameter checking |

Two kinds of options are rejected when the file loads, with the reason in the log:

- **Human-in-the-loop options** (`requires_confirmation`, `requires_user_input`,
  `user_input_fields`, `external_execution`, `external_execution_silent`, and
  Agno's `@approval` decorator) pause the run until someone answers, and the
  Discord flow never resumes a paused run, so the bot would never reply. Use
  `requires_permissions`, or keep the action on `@command`.
- **`cache_results` with a `ctx` parameter or `requires_permissions`.** Agno's
  cache key covers only the model's arguments, so a cached result would be
  shared across users, channels and servers, and would skip the permission
  check.

`@command` takes no tool options, since it is never an agent tool.

## Using built-in Agno toolkits & context providers

Beyond writing your own functions, you can attach any
[Agno toolkit](https://docs.agno.com/tools/toolkits) or
[context provider](https://docs.agno.com/context-providers) to the agent from a
custom file with `register_tools()` — no core code changes:

```python
from dango.extensions import register_tools
from agno.context.gdrive import GoogleDriveContextProvider

# A context provider exposes its tools via get_tools()
register_tools(*GoogleDriveContextProvider(corpora="user").get_tools())
```

`register_tools()` accepts plain functions, `@tool` functions, `Toolkit`
instances, or lists (such as a provider's `get_tools()`). Everything you pass is
exposed to the **agent only** — it never becomes a Discord slash command. This is
the same mechanism Dango uses internally for its SQL database tools.

Agno ships context providers for Google Drive, Gmail, Calendar, Slack, web, wiki,
the filesystem, and more. Some need extra packages and credentials — e.g. Drive
needs `google-api-python-client google-auth-httplib2 google-auth-oauthlib` plus
OAuth. Install those in your clone the usual way (`uv add ...`).

::: info Agno's Scheduler does not apply
Agno's [Scheduler](https://docs.agno.com/scheduler/overview) is a runtime/cron
orchestration layer that drives AgentOS endpoints — it is not a tool and does
not plug into Dango's discord.py + Workflow model. For scheduled behaviour,
use `discord.ext.tasks` or an external cron job.
:::

## Interactive UI (modals, buttons, selects) — not supported here

This SDK is built around a simple contract: **your function takes arguments and
returns a string, and the framework sends it.** Under the hood the command path
calls `interaction.response.defer()` and then `followup.send(...)` for you. That
contract has two consequences:

- **No Discord UI components.** You cannot pop up a modal or attach buttons /
  select menus from an extension function — a modal must be the *first* response
  to an interaction, but the framework has already deferred it. This applies to
  `@command` too, not just the agent path.
- **The agent path has no interaction.** When the LLM calls your function,
  `ctx.interaction` is `None` and there is no human in the loop to fill a form.

**How the agent "fills in" missing input:** it asks. If a tool needs more
information the model simply asks a follow-up question in chat ("Which ticker?"),
the user replies, and the agent calls the tool again with the answer. Collection
is conversational, not a popup.

**If you genuinely need a modal / button flow,** write a normal `discord.py`
command or Cog directly (outside this SDK) so you own the interaction lifecycle.
To also let the agent do the same job, add a separate `@agent_tool` whose
parameters are the fields the modal would collect, and have both call one shared
logic function:

```python
async def _create_event(title: str, when: str) -> str:
    ...  # shared core logic

@agent_tool(description="Create a calendar event")
async def create_event(title: str, when: str) -> str:
    """Args: title: event title. when: ISO datetime."""
    return await _create_event(title, when)

# The modal-based version lives in your own discord.py Cog and also calls _create_event().
```

## How loading works

- On startup the bot imports every `custom/*.py` once (`*.example` files are
  skipped), then registers tools on the agent and slash commands on the bot.
- A **missing `custom/` directory** or a **broken file** is logged and skipped —
  it never crashes the bot. Look for `🧩 [custom]` / `⚠️ [custom]` lines in the log.
- New slash commands are synced to Discord on the next startup (during `on_ready`).
  Restart the bot after adding or changing a command.

::: info Docker deployments
The official `docker-compose.yml` mounts `./custom` into the bot container and
seeds the `*.example` templates on first run. Drop your `.py` files in `./custom`
on the host and `docker compose restart bot`. Tools needing extra Python packages
require a derived image — see [Docker → Custom commands & tools](../getting-started/docker.md#custom-commands-tools).
:::

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CUSTOM_DIR` | `custom` | Directory scanned for `*.py` extension files |

See also: [Tools](tools.md) for the no-code HTTP API and SQL tools, and
[Slash Commands](../usage/commands.md) for the built-in commands.
