---
layout: home
title: "Dango — Discord AI Bot & Agent"
titleTemplate: false
description: "Dango is a free, open-source, self-hosted Discord AI bot and agent. Connect Gemini, GPT-4o, Claude, Llama, or Ollama and run your own Discord AI on your server in minutes — no code changes needed."
tags:
  - Getting Started
  - Discord bot
  - AI chatbot

hero:
  name: Dango
  text: Discord AI Bot & Agent
  tagline: Connect Gemini, GPT-4o, Claude, Llama, or Ollama to your Discord server in minutes — no code changes needed.
  actions:
    - theme: brand
      text: Get Started
      link: /getting-started/discord-setup
    - theme: alt
      text: Docker Quick Start
      link: /getting-started/docker
    - theme: alt
      text: View on GitHub
      link: https://github.com/zhiro-labs/dango

features:
  - icon: 🔌
    title: Any AI provider
    details: "provider:model_id auto-configures the SDK and API key — cloud (Gemini, GPT-4o, Claude, Groq) or local (Ollama, LM Studio, vLLM) for fully offline runs."
    link: /features/models
  - icon: 🔀
    title: Dual-model routing
    details: Pair a fast model for simple messages and a deep model for complex ones; AUTO_ROUTE switches automatically.
    link: /features/models#dual-model-routing
  - icon: 🖼️
    title: Table rendering
    details: Markdown tables in replies are auto-converted to PNG images (CJK font support included).
    link: /features/workflow
  - icon: ⚙️
    title: Web dashboard
    details: Browser-based setup wizard and admin UI — no config file editing needed.
    link: /getting-started/docker
  - icon: ♻️
    title: No restarts
    details: Channels, users, history limit, timezone, and activity are all adjustable live via slash commands.
    link: /usage/commands
  - icon: 🎓
    title: Skills
    details: Drop a folder with a SKILL.md into skills/ and the bot loads its instructions, scripts, and references on demand — no code needed.
    link: /features/tools#skills
  - icon: 🛠️
    title: Tools
    details: Web search (DuckDuckGo), URL fetching, workspace file access, custom APIs, SQL databases.
    link: /features/tools
  - icon: 🧰
    title: Custom commands & tools
    details: Drop Python files in custom/ to add your own slash commands and agent tools — no core changes, loaded on startup.
    link: /features/extensions
  - icon: 🧩
    title: Embeddable
    details: Drop the Cogs into any existing discord.py bot in a few lines.
    link: /advanced/embedding
---

**Dango** is a free, open-source, self-hosted **Discord AI** bot and agent built on [Agno](https://docs.agno.com). Connect any model provider — Google Gemini, GPT-4o, Claude, Llama, Groq, or local Ollama — and run your own Discord AI chatbot and agent on your server in minutes, with no code changes.

## Before you start

You need:

- A **Discord bot token** — follow [Discord Setup](/getting-started/discord-setup) to create one (~5 minutes)
- An **API key** for your model provider ([Google AI Studio](https://aistudio.google.com/apikey), [OpenAI](https://platform.openai.com/api-keys), [Anthropic](https://console.anthropic.com/), [Groq](https://console.groq.com/), etc.) — or a local [Ollama](https://ollama.com) instance (no key needed)

| Method | Also requires |
|---|---|
| **Docker** (recommended) | [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Windows), [OrbStack](https://orbstack.dev) (Mac), or [Docker Engine](https://docs.docker.com/engine/install/) (Linux) |
| **uv** (developers) | Python 3.12–3.14, [uv](https://github.com/astral-sh/uv) |

## Quick Start

::: code-group

```bash [Docker (recommended)]
# 1. Download docker-compose.yml
cd ~/Downloads       # or wherever you'd like
curl -O https://raw.githubusercontent.com/zhiro-labs/dango/main/docker-compose.yml

# 2. Start the containers (-d runs in the background; logs -f streams output)
docker compose up -d && docker compose logs -f

# 3. Open the setup wizard at http://localhost:17860
#    The wizard asks for your Discord token, model API key, and bot personality.

# 4. Mention the bot in Discord: @YourBotName hello!
```

```bash [uv (developers)]
# 1. Clone and install
git clone https://github.com/zhiro-labs/dango
cd dango
uv sync

# 2. Copy config files
cp .env.example .env
cp config/runtime.yml.example config/runtime.yml
cp config/chat_sys_prompt.txt.example config/chat_sys_prompt.txt

# 3. Fill in .env (at minimum):
#    DISCORD_BOT_TOKEN=your_discord_token
#    FAST_API_KEY=your_api_key
#    FAST_MODEL=google:gemini-2.5-flash   # format: provider:model_id
#    CHAT_SYS_PROMPT_PATH=config/chat_sys_prompt.txt

# 4. Run (first run downloads Noto Sans CJK fonts ~100 MB for table rendering)
uv run main.py
```

:::

Full walkthroughs: [Docker guide](/getting-started/docker) · [uv guide](/getting-started/uv).

### Prefer to be walked through it?

No special tools needed — paste a prompt into any AI assistant ([Claude](https://claude.ai), [ChatGPT](https://chatgpt.com), [Grok](https://grok.com)) and it will guide you through installation step by step. [Claude Code](https://claude.ai/code) and Codex can run the commands for you directly.

::: details Docker setup prompt (click to expand)
```
I want to install the Dango Discord bot using Docker. Please go through these steps one at a time and explain what each command does before running it:

1. Check that Docker is installed and running (docker info). If not, stop and tell me to install it from https://docs.docker.com/get-docker/ before continuing.
2. Ask me where to create the project folder (suggest ~/dango as the default).
3. Create that folder and move into it.
4. Download the setup file: curl -O https://raw.githubusercontent.com/zhiro-labs/dango/main/docker-compose.yml
5. Show me the contents of docker-compose.yml before doing anything else.
6. Start the bot: docker compose up -d
7. Confirm both the "web" and "bot" containers are running: docker compose ps
8. Tell me to open http://localhost:17860 in my browser to finish setup.

Important: do NOT ask for, store, or touch any Discord tokens or API keys — the web setup wizard handles all credentials. Do not run any commands that delete files.
```
:::

::: details uv setup prompt (click to expand)
```
I want to install the Dango Discord bot using uv (a Python package manager). Please go through these steps one at a time and explain what each command does before running it:

1. Check that git is installed (git --version). If not, stop and tell me to install it from https://git-scm.com/downloads
2. Check that uv is installed (uv --version). If not, install it automatically:
   - Mac/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
   - Windows: tell me to visit https://docs.astral.sh/uv/getting-started/installation/
3. Ask me where to clone the project (suggest ~/dango as the default).
4. Clone and enter the folder:
   git clone https://github.com/zhiro-labs/dango <chosen-folder>
   cd <chosen-folder>
5. Install dependencies: uv sync
6. Copy the example config files:
   cp .env.example .env
   cp config/runtime.yml.example config/runtime.yml
   cp config/chat_sys_prompt.txt.example config/chat_sys_prompt.txt
7. Tell me exactly which values to fill in inside .env (DISCORD_BOT_TOKEN, FAST_API_KEY, FAST_MODEL, CHAT_SYS_PROMPT_PATH) and what each one means. Wait for me to confirm I've filled them in before continuing.
8. Start the bot: uv run main.py

Important: do NOT read, display, log, or store the contents of .env — it contains my API keys and tokens. Only tell me which variables to fill in and what they mean.
```
:::

## Project Structure

```
dango/                         # repo root
├── main.py                    # Entry point
├── dango/                     # Python package
│   ├── app_config.py          # Web UI config injection
│   ├── workflow.py            # Agno Workflow definition
│   ├── steps/                 # 4-step pipeline
│   │   ├── fetch_history.py
│   │   ├── call_agent.py      # Runs the agent for one message
│   │   ├── table_steps.py     # Table → PNG rendering
│   │   └── send_response.py   # Discord send (split, reply, table images)
│   ├── agent/                 # Settings, models, tools, skills, routing, retry/fallback
│   ├── commands/
│   │   ├── chat_commands.py   # ChatCog: on_message, /newchat, /deep
│   │   └── admin_commands.py  # AdminCog: all admin slash commands
│   ├── extensions/            # Custom commands & tools SDK (loads custom/*.py)
│   └── utils/
├── web/                       # FastAPI dashboard
├── config/                    # System prompt & runtime config
└── tests/
```
