---
summary: "Load Dango's ChatCog and AdminCog into an existing discord.py bot to add natural-language chat, web search, read-URL, and workspace access on top of the host bot's own commands — all opt-in via env vars, no code changes beyond loading the Cogs. Includes a full Neko reminder bot integration example. To add your own commands/agent tools, see Custom Commands & Tools."
description: "Embed Dango's AI agent into an existing discord.py bot. Install the package, load ChatCog and AdminCog in setup_hook, and add natural-language chat on top of your bot's own commands — without touching them."
tags:
  - Advanced
  - Embedding
  - discord.py
  - Developers
---

# Embedding into Another Bot

Dango's agent is a standard `discord.py` Cog. Drop `ChatCog` (and optionally
`AdminCog`) into an existing bot and it gains natural-language chat, web search,
and file access — while every slash command and prefix command you already have
keeps working untouched.

## What you get

| Capability | How to enable | Notes |
|---|---|---|
| **Chat** | always on | History-aware natural-language replies |
| **Web search** | `ENABLE_DUCKDUCKGO=on` / `ENABLE_BRAVE_SEARCH=on` | Agent decides when to search |
| **Read URL** | `ENABLE_WEBSITE_TOOLS=on` | Agent reads links that appear in messages |
| **Workspace** | `ENABLE_WORKSPACE=on` | Read-only access to a local folder ([extra setup](#workspace-extra-setup-when-embedding)) |
| **Custom commands & tools** | write Python in `custom/` | [Custom Commands & Tools](../features/extensions.md) |

Every toggle is read from the environment. Full list and per-feature behaviour:
[Environment Variables](../configuration/env-vars.md) and [Tools](../features/tools.md).

## Install

```bash
uv add git+https://github.com/zhiro-labs/dango     # uv
pip install git+https://github.com/zhiro-labs/dango # pip
```

Dango supports Python 3.12–3.14; the upper bound comes from LiteLLM, one of the bundled model providers. With uv, your project's `requires-python` must fall inside that range (for example `requires-python = ">=3.12,<3.15"`), otherwise the resolver reports that dango cannot be used.

## Minimal integration

Dango reads environment variables **at import time**, so `load_dotenv()` must run
before the first `dango` import. Then load the Cogs in `setup_hook`:

```python
# main.py
from dotenv import load_dotenv
load_dotenv()  # MUST run before any dango import

import os
import discord
from discord.ext import commands
from dango import ChatCog, AdminCog, create_discord_workflow, RuntimeConfig

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())


@bot.event
async def setup_hook():
    with open(os.getenv("CHAT_SYS_PROMPT_PATH", "config/chat_sys_prompt.txt"), encoding="utf-8") as f:
        chat_system_prompt = f.read()

    runtime_config = RuntimeConfig("config/runtime.yml")
    discord_workflow = create_discord_workflow()

    await bot.add_cog(ChatCog(bot, discord_workflow, chat_system_prompt, runtime_config))
    await bot.add_cog(AdminCog(bot, runtime_config))  # optional — admin slash commands

    await bot.tree.sync()
```

That is the whole integration. `ChatCog` handles incoming messages; `AdminCog`
adds admin slash commands (optional). Everything else is configuration.

::: warning Three things that will bite you
- **`load_dotenv()` before imports.** dango resolves model/feature settings at
  import time. Importing before `.env` is loaded silently uses defaults.
- **`uv run` does not load `.env`.** You must call `load_dotenv()` yourself —
  `uv` only injects shell-exported variables.
- **Register Cogs in `setup_hook`, never `on_ready`.** `setup_hook` runs once
  before the gateway connects, so no events are missed.
:::

### Required intents

`ChatCog` needs `message_content` (to read messages) and `members` (for display
names). `discord.Intents.all()` covers these; to be explicit:

```python
intents = discord.Intents(
    guilds=True, guild_messages=True, dm_messages=True,
    message_content=True,  # required: read message text
    members=True,          # required: resolve display names
)
```

## Configuration

The host bot owns its own configuration; dango only reads the variables it needs.

- **Discord token is yours, not dango's.** `DISCORD_BOT_TOKEN` belongs to the host
  bot's config — dango never reads it.
- **Model + features** come from the environment. See
  [Environment Variables](../configuration/env-vars.md) for the complete list and
  start from the repo's commented [`.env.example`](https://github.com/zhiro-labs/dango/blob/main/.env.example).
- **When does the bot respond?** By default only when @mentioned. To answer every
  message in a channel, seed channel IDs on first run or add them at runtime:

    ```python
    # Seeds config/runtime.yml on first run only; later /removechannel edits are kept.
    runtime_config = RuntimeConfig("config/runtime.yml", default_channels=[CHANNEL_ID])
    ```

    Or let an admin run `/addchannel` in the target channel after startup.

- **Generated files** to add to `.gitignore`:

    ```
    config/runtime.yml
    config/workspace_sys_prompt.txt
    config/workspace_sys_prompt.fingerprint.json
    ```

## Workspace: extra setup when embedding

The standalone bot initialises the workspace automatically; an embedded bot must
do it itself. Without this call the workspace system prompt is never generated and
the agent has no knowledge of the files.

```python
@bot.event
async def setup_hook():
    if os.getenv("ENABLE_WORKSPACE") == "on":
        from dango.utils import workspace_context
        await workspace_context.init(
            os.getenv("WORKSPACE_ROOT", "workspace"),
            os.getenv("WORKSPACE_SYS_PROMPT_PATH", "config/workspace_sys_prompt.txt"),
        )
    # ... add_cog calls follow
```

`init()` reads the files, builds a topic-index prompt block, and caches it; the
cache invalidates automatically when the files change. See
[Tools → Workspace](../features/tools.md#workspace-file-access) for behaviour.

## The objects you wire up

| Object | Role |
|---|---|
| `create_discord_workflow()` | Builds the Agno `Workflow` (fetch history → call agent → render tables → send). Call once. |
| `RuntimeConfig(path, default_channels=None)` | Allowed channels/users, history limit, timezone, activity. Pass the **same instance** to both Cogs. |
| `ChatCog(bot, workflow, system_prompt, runtime_config)` | Handles messages and runs the pipeline. |
| `AdminCog(bot, runtime_config)` | Admin slash commands (`/addchannel`, `/settimezone`, …), all require the Administrator permission. |

Full signatures: [API Reference](../reference/api.md). The admin commands are listed
under [Slash Commands](../usage/commands.md).

## Add your own commands and tools

To extend the embedded agent with your own slash commands or LLM-callable tools —
including ones that are both at once — use the `dango.extensions` SDK and drop
Python files into a gitignored `custom/` directory. See
[Custom Commands & Tools](../features/extensions.md).

## Full example — Neko reminder bot

Neko is an event-reminder bot with its own slash commands (`/event`,
`/event-list`, `/event-delete`, …). Adding Dango lets users chat with it in plain
language while every existing command keeps working.

**1. Install** in the Neko project: `uv add git+https://github.com/zhiro-labs/dango`

**2. Configure `.env`:**

```env
FAST_MODEL=google:gemini-2.0-flash
FAST_API_KEY=your_api_key_here
CHAT_SYS_PROMPT_PATH=config/chat_sys_prompt.txt
ENABLE_DUCKDUCKGO=on
```

**3. Write the system prompt** (`config/chat_sys_prompt.txt`). Describe the bot's
existing commands so the agent can point users to them — this is what turns chat
into a front door for your slash commands:

```
You are Neko, a Discord event reminder assistant. Guide users to the right command:
- Create an event → /event
- See upcoming events → /event-list
- Delete an event → /event-delete
- Set the reminder timezone → /set-reminder-timezone
Reply in a friendly, helpful tone.
```

**4. Wire it into `main.py`** using the [minimal integration](#minimal-integration)
pattern. Add the Dango pieces inside Neko's existing `setup_hook` (after its own
`db.init_db()` etc.), and pass `default_channels=[YOUR_CHANNEL_ID]` so Neko replies
to every message in your chosen channel.

The result: all original slash commands work unchanged, and users can now ask
questions in plain English — the agent answers, suggests the right command, and
searches the web when it helps.

## Updating

```bash
uv add git+https://github.com/zhiro-labs/dango              # uv
pip install --upgrade git+https://github.com/zhiro-labs/dango # pip
```

Restart the bot to pick up the new version.
