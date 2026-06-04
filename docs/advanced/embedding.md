# Embedding into Another Bot

Dango's agent lives in a standard discord.py Cog, so you can drop it into any existing bot. The bot keeps all its slash commands and prefix commands; Dango adds a natural-language layer on top.

## Installation

```bash
# uv
uv add git+https://github.com/zhiro-labs/dango

# pip
pip install git+https://github.com/zhiro-labs/dango
```

## Loading the Cogs

Set the required environment variables before importing (e.g. via `load_dotenv()`), then load the Cogs in `setup_hook`:

```python
from dango.commands import ChatCog, AdminCog
from dango.utils.runtime_config import RuntimeConfig
from dango.workflow import create_discord_workflow

with open("config/chat_sys_prompt.txt", encoding="utf-8") as f:
    chat_system_prompt = f.read()

runtime_config = RuntimeConfig("config/runtime.yml")
discord_workflow = create_discord_workflow()

await bot.add_cog(ChatCog(bot, discord_workflow, chat_system_prompt, runtime_config))
await bot.add_cog(AdminCog(bot, runtime_config))
```

## `ChatCog` parameters

| Parameter | Type | Description |
|---|---|---|
| `bot` | `commands.Bot` | Your bot instance |
| `discord_workflow` | `Workflow` | Created by `create_discord_workflow()` |
| `chat_system_prompt` | `str` | System prompt for the agent |
| `runtime_config` | `RuntimeConfig` | Allowed channels, users, history limit, timezone |
| `extra_tools` | `list \| None` | `@discord_tool`-wrapped functions the agent can call |
| `context_menu_defs` | `list[ContextMenuDef] \| None` | Right-click context menu commands |

---

## Wrapping commands as tools

The agent can call your existing bot commands as tools. Users can ask naturally ("ban spammer") and the agent decides when to invoke `ban_user` — without breaking the original `!ban` or `/ban` commands.

### 1. Extract the logic and wrap it

```python
from dango.tools import discord_tool, RunContext, get_discord_context

@discord_tool(name="play_music")
async def play_music(song: str, run_context: RunContext) -> str:
    """Play music in the voice channel.

    Args:
        song (str): Song name or YouTube/Spotify URL
    """
    ctx = get_discord_context(run_context)
    if ctx["guild_id"] is None:
        return "This command can only be used in a server channel."
    await music_player.play(ctx["guild_id"], song)
    return f"Now playing: {song}"
```

### 2. Pass tools to `ChatCog`

```python
await bot.add_cog(ChatCog(
    bot, workflow, chat_system_prompt, runtime_config,
    extra_tools=[play_music],
))
```

Your original `!play` / `/play` commands keep working unchanged.

### Tool function rules

| Rule | Detail |
|---|---|
| Type hints | Required on every parameter and return value |
| Docstring | First line = tool description shown to the LLM |
| `Args:` block | One line per parameter; Agno parses this for the tool schema |
| `run_context: RunContext` | Agno injects this automatically — not exposed to the LLM |
| Return value | `str` by default; can be `""` when using `set_discord_response()` |
| Async or sync | Both work |

---

## Context helpers

### `get_discord_context(run_context)`

Returns the Discord request context as a dict:

```python
from dango.tools import discord_tool, RunContext, get_discord_context

@discord_tool(name="my_tool")
async def my_tool(run_context: RunContext) -> str:
    ctx = get_discord_context(run_context)
    # ctx["author_id"]          — int | None
    # ctx["author_name"]        — str
    # ctx["author_roles"]       — list[str]  (guild role names, excludes @everyone)
    # ctx["channel_id"]         — int | None
    # ctx["channel_name"]       — str
    # ctx["guild_id"]           — int | None  (None in DMs)
    # ctx["guild_name"]         — str
    ...
```

### `get_discord_bot(run_context)`

Returns the `discord.Bot` instance. Use this when a tool needs to send messages, fetch channels, or trigger native Discord UI:

```python
from dango.tools import get_discord_bot

bot = get_discord_bot(run_context)
channel = bot.get_channel(ctx["channel_id"])
await channel.send("Hello from a tool!")
```

### `get_discord_interaction(run_context)`

Returns the `discord.Interaction` that triggered this request, or `None` for regular chat messages. Present for button clicks, select menus, modal submits, and context menus.

---

## Permission helpers

### `check_roles()` — custom role names

```python
from dango.tools import check_roles

@discord_tool(name="ban_user")
async def ban_user(username: str, reason: str, run_context: RunContext) -> str:
    """Ban a user. Requires Moderator or Admin role.

    Args:
        username (str): Display name of the user to ban
        reason (str): Reason for the ban
    """
    if err := check_roles(run_context, any_of=["Moderator", "Admin"]):
        return err
    # ... logic ...
```

| Parameter | Description |
|---|---|
| `any_of` | User must have **at least one** of these role names |
| `all_of` | User must have **every** one of these role names |

Returns an error string if the check fails, `None` if it passes.

### `check_permissions()` — Discord built-in permissions

For Discord's built-in permissions (`manage_guild`, `ban_members`, etc.) rather than custom role names:

```python
from dango.tools import check_permissions

@discord_tool(name="set_timezone")
async def set_timezone(timezone: str, run_context: RunContext) -> str:
    """Set the server's reminder timezone.

    Args:
        timezone (str): Timezone name, e.g. Asia/Taipei
    """
    if err := check_permissions(run_context, any_of=["manage_guild"]):
        return err
    # ... logic ...
```

Common permission names: `administrator`, `manage_guild`, `manage_roles`, `manage_channels`, `ban_members`, `kick_members`, `manage_messages`, `moderate_members`.

---

## Response helpers

### `set_ephemeral()` — private response

Makes the response visible only to the invoking user. Only effective when the request came from a Discord Interaction (slash command, button, modal, context menu) — has no effect on regular chat messages.

```python
from dango.tools import set_ephemeral

@discord_tool(name="get_balance")
async def get_balance(run_context: RunContext) -> str:
    """Check your personal balance. Response is private."""
    set_ephemeral(run_context)
    return f"Your balance: 1000 coins"
```

### `set_discord_response()` — embed output and text suppression

Attach `discord.Embed` objects to the response, or suppress the LLM's text output entirely:

```python
import discord
from dango.tools import set_discord_response

@discord_tool(name="list_events")
async def list_events(run_context: RunContext) -> str:
    """List upcoming events."""
    embed = discord.Embed(title="Upcoming Events", color=discord.Color.blurple())
    embed.add_field(name="Concert", value="Saturday 19:00", inline=False)

    set_discord_response(run_context, embeds=[embed], suppress_text=True)
    set_ephemeral(run_context)
    return ""  # text is suppressed; only the embed is sent
```

| Parameter | Description |
|---|---|
| `embeds` | List of `discord.Embed` objects (max 10 per message) |
| `suppress_text` | If `True`, the LLM's generated text is not sent — only embeds and table images |

---

## Native Discord UI (stateful multi-step forms)

For complex interactive UI — multi-select dropdowns, confirm buttons, multi-step forms — use `discord.ui.View` directly. The `View` manages its own state through Python callbacks; no Dango routing needed.

```python
from dango.tools import discord_tool, RunContext, get_discord_bot, get_discord_context, set_discord_response

@discord_tool(name="open_event_form")
async def open_event_form(title: str, run_context: RunContext) -> str:
    """Open an interactive form to configure a new event.

    Args:
        title (str): Event title
    """
    bot = get_discord_bot(run_context)
    ctx = get_discord_context(run_context)
    channel = bot.get_channel(ctx["channel_id"])

    # EventView is a standard discord.ui.View — it manages role/reminder
    # selection state internally through Python callbacks.
    view = EventView(title=title, ...)
    await channel.send(f"Configure **{title}**:", view=view)

    set_discord_response(run_context, suppress_text=True)
    return ""
```

The key difference from `dango_component:` routing: `EventView`'s buttons and selects call their Python callbacks directly — the LLM is not involved after the form appears. Use this pattern when the UI has complex local state (e.g. three selects whose values must all be read together on confirm).

---

## `on_interaction` routing (modal & component)

For simpler interactions where you *do* want the LLM to process the result, prefix `custom_id` with `dango_modal:` or `dango_component:`. Dango routes these back through the full workflow automatically.

### Modal submit

```python
import discord

# Slash command opens the modal — no deferring, no workflow run here.
@bot.tree.command(name="report")
async def report_command(interaction: discord.Interaction):
    modal = discord.ui.Modal(title="Submit Report", custom_id="dango_modal:report")
    modal.add_item(discord.ui.TextInput(label="Issue", custom_id="issue"))
    modal.add_item(discord.ui.TextInput(label="Details", custom_id="details",
                                         style=discord.TextStyle.paragraph))
    await interaction.response.send_modal(modal)

# When submitted, on_interaction sees the dango_modal: prefix and routes
# through the workflow. The LLM receives:
#   [Modal submitted: report]
#   issue: Can't send messages
#   details: Getting a permission error since yesterday
```

The LLM then decides which tool to call based on the form contents.

### Button / select click

```python
import discord

# Tool sends a message with a dango_component:-prefixed button.
@discord_tool(name="confirm_delete")
async def confirm_delete(channel_name: str, run_context: RunContext) -> str:
    """Ask for confirmation before deleting a channel.

    Args:
        channel_name (str): Channel to delete
    """
    bot = get_discord_bot(run_context)
    ctx = get_discord_context(run_context)
    channel = bot.get_channel(ctx["channel_id"])

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Confirm delete",
        style=discord.ButtonStyle.danger,
        custom_id=f"dango_component:delete_confirmed:{channel_name}",
    ))
    view.add_item(discord.ui.Button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        custom_id="dango_component:delete_cancelled",
    ))
    await channel.send(f"Delete **#{channel_name}**?", view=view)
    set_discord_response(run_context, suppress_text=True)
    return ""

# When a button is clicked, the LLM receives:
#   [Button: delete_confirmed:general]
#   Context: Delete **#general**?
# and can call the actual delete tool.
```

---

## Context menu commands

Register right-click commands that route through the agent:

```python
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
        # Right-click a message → "Translate"
        ContextMenuDef(
            name="Translate",
            target="message",
            content_builder=lambda text: f"Translate this message to English:\n{text}",
        ),
        # Right-click a user → "User Info"
        ContextMenuDef(name="User Info", target="user"),
    ],
))
```

| `ContextMenuDef` field | Description |
|---|---|
| `name` | Label shown in Discord's right-click menu (max 32 chars) |
| `target` | `"message"` or `"user"` |
| `content_builder` | Optional callable `(str) → str`; transforms the target text into the agent's input. Defaults to `[Context menu: <name>]\nTarget: <text>` |

---

## Full example — Neko reminder bot

Neko has `/event`, `/event-list`, `/event-delete`, `/set-reminder-timezone`, and `/set-reminder-channel`. Here is how those commands become tools while the existing slash commands continue to work:

```python
# neko_tools.py
import discord
from dango.tools import (
    RunContext, discord_tool,
    get_discord_context, get_discord_bot,
    check_permissions, set_ephemeral, set_discord_response,
)
import db
from main import parse_date, parse_time, reminder_delta, discord_ts, REMINDER_OPTIONS, EventView


@discord_tool(name="set_reminder_timezone")
async def set_reminder_timezone(timezone: str, run_context: RunContext) -> str:
    """Set the server's reminder timezone.

    Args:
        timezone (str): Timezone name, e.g. Asia/Taipei
    """
    if err := check_permissions(run_context, any_of=["manage_guild"]):
        return err
    ctx = get_discord_context(run_context)
    db.set_timezone(ctx["guild_id"], timezone)
    set_ephemeral(run_context)
    return f"已將伺服器時區設定為 `{timezone}`。"


@discord_tool(name="list_events")
async def list_events(run_context: RunContext) -> str:
    """List all upcoming events."""
    ctx = get_discord_context(run_context)
    bot = get_discord_bot(run_context)
    reminder_channel_id = db.get_reminder_channel(ctx["guild_id"])
    if not reminder_channel_id:
        return "⚠️ 尚未設定提醒頻道。"

    events = db.get_upcoming_events(reminder_channel_id)
    if not events:
        return "目前沒有尚未到來的活動。"

    guild = bot.get_guild(ctx["guild_id"])
    embed = discord.Embed(title="即將到來的活動", color=discord.Color.blurple())
    for event in events:
        roles = [guild.get_role(rid) for rid in event.role_ids]
        users = [guild.get_member(uid) for uid in event.user_ids]
        mentions = " ".join([r.mention for r in roles if r] + [u.mention for u in users if u])
        value = f"📅 {discord_ts(event.event_time, 'F')}"
        if mentions:
            value += f"\n👥 {mentions}"
        embed.add_field(name=event.title, value=value, inline=False)

    set_ephemeral(run_context)
    set_discord_response(run_context, embeds=[embed], suppress_text=True)
    return ""


@discord_tool(name="create_event_with_ui")
async def create_event_with_ui(title: str, date: str, time: str, run_context: RunContext) -> str:
    """Create an event and open a UI to select roles and reminder times.

    Args:
        title (str): Event title
        date (str): Date in YYYY-MM-DD format
        time (str): Time in HH:MM format
    """
    ctx = get_discord_context(run_context)
    bot = get_discord_bot(run_context)

    parsed_date = parse_date(date)
    parsed_time = parse_time(time)
    if not parsed_date or not parsed_time:
        return "❌ 日期或時間格式錯誤。"

    from zoneinfo import ZoneInfo
    tz = ZoneInfo(db.get_timezone(ctx["guild_id"]))
    event_dt = parsed_date.replace(hour=parsed_time[0], minute=parsed_time[1], tzinfo=tz)

    reminder_channel_id = db.get_reminder_channel(ctx["guild_id"])
    channel = bot.get_channel(ctx["channel_id"])
    creator = bot.get_guild(ctx["guild_id"]).get_member(ctx["author_id"])

    # Use Neko's native EventView — it manages selection state internally.
    view = EventView(
        title=title, date=event_dt,
        announce_channel=channel,
        reminder_channel=bot.get_channel(reminder_channel_id),
        creator=creator,
    )
    await channel.send(
        f"**{title}** — {discord_ts(event_dt, 'F')}\n請選擇身份組與提醒時間：",
        view=view,
    )
    set_discord_response(run_context, suppress_text=True)
    return ""
```

Add to `.env`:

```env
CHAT_SYS_PROMPT_PATH=config/chat_sys_prompt.txt
```

Create `config/chat_sys_prompt.txt`:

```
你是 Neko，一個 Discord 活動提醒助理。
你可以幫助使用者建立活動、查詢活動清單、刪除活動，以及設定時區和提醒頻道。
用繁體中文回覆。
```

Then in `on_ready` or `setup_hook` — add alongside existing commands:

```python
import os
from dango.commands import ChatCog
from dango.workflow import create_discord_workflow
from dango.utils.runtime_config import RuntimeConfig
from neko_tools import set_reminder_timezone, list_events, create_event_with_ui

with open(os.getenv("CHAT_SYS_PROMPT_PATH", "config/chat_sys_prompt.txt"), encoding="utf-8") as f:
    chat_system_prompt = f.read()

workflow = create_discord_workflow()
runtime_config = RuntimeConfig("config/runtime.yml")

await bot.add_cog(ChatCog(
    bot, workflow, chat_system_prompt, runtime_config,
    extra_tools=[set_reminder_timezone, list_events, create_event_with_ui],
))
```

Users can now use `/event` as before **and** say "建立 Python 讀書會，6/7 晚上 7 點" in natural language.

---

## Updating

```bash
# uv
uv add git+https://github.com/zhiro-labs/dango

# pip
pip install --upgrade git+https://github.com/zhiro-labs/dango
```

Restart your bot to pick up the new version.
