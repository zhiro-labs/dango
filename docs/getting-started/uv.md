---
summary: "Developer path — clone, sync, fill `.env`, run."
description: "Install and run Dango Discord AI bot with uv — the recommended path for developers. Clone the repo, install dependencies, configure .env, and start the bot directly."
tags:
  - Getting Started
  - uv
  - Installation
  - Developers
---

# uv Setup

The uv path is for developers or anyone who prefers running the bot directly without Docker.

## Prerequisites

- Python 3.12–3.14
- [uv](https://github.com/astral-sh/uv) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh` (Mac/Linux)
- A Discord bot token — see [Discord Setup](discord-setup.md)
- An API key for your chosen model provider

## Steps

### 1. Clone and install

```bash
git clone https://github.com/zhiro-labs/dango
cd dango
uv sync
```

### 2. Copy config files

```bash
cp .env.example .env
cp config/runtime.yml.example config/runtime.yml
cp config/chat_sys_prompt.txt.example config/chat_sys_prompt.txt
```

`runtime.yml` stores live settings — allowed channels, DM users, timezone, history limit. The bot writes this file automatically when you use slash commands; you rarely need to touch it by hand. See [Runtime Config](../configuration/runtime.md) for details.

### 3. Fill in `.env`

Open `.env` and set at minimum these four values:

```env
DISCORD_BOT_TOKEN=your_discord_token
FAST_API_KEY=your_api_key
FAST_MODEL=google:gemma-4-26b-a4b-it   # format: provider:model_id
CHAT_SYS_PROMPT_PATH=config/chat_sys_prompt.txt
```

See [Model Providers](../features/models.md) for the full list of supported `provider:` prefixes and where to get API keys.

### 4. Edit the system prompt

Open `config/chat_sys_prompt.txt` and give the bot its personality. This is the instruction the model receives before every conversation.

### 5. Run

```bash
uv run main.py
```

On first run, Noto Sans CJK fonts (~100 MB) download automatically for table rendering.

### 6. Test the bot

In Discord, mention the bot in any channel it can see:

```
@YourBotName hello!
```

It should reply within a few seconds. If it doesn't, check the terminal for error messages.

## Updating

```bash
git pull
uv sync
```

Then restart the bot. `.env` and `config/` are not touched by updates.

## Managing the bot

**Stop:** Press **Ctrl+C** in the terminal running `uv run main.py`.

**Start again:**
```bash
uv run main.py
```

Your `.env` and everything in `config/` persists between restarts.
