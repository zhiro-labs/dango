# 🍡 Dango — Discord AI Agent

An **open-source Discord AI bot** and agent — connect any AI model to your Discord server in minutes.

Gemini, GPT-4o, Claude, Llama, local Ollama — they all work. Switch providers by changing one line and restarting. No code changes — channels, users, and bot behaviour are all configurable live from Discord slash commands.

No database setup required — mount a folder of docs and the bot answers from them directly.

**[📖 Full Documentation](https://zhiro-labs.github.io/dango)** · [中文版 README](README.zh-TW.md)

---

## What it can do

- **Use any AI provider** — set `FAST_MODEL` to `provider:model_id` (e.g. `google:gemini-2.5-flash`, `openai:gpt-4o`, `anthropic:claude-sonnet-4-20250514`, `groq:llama-3.3-70b-versatile`) and the bot figures out the right SDK and API key automatically.
- **Run locally** — point `FAST_MODEL` (or `DEEP_MODEL`) at a local Ollama or LM Studio instance and set `FAST_BASE_URL` (or `DEEP_BASE_URL`) to its address. Running the bot in Docker while the model server is on the host? Use `http://host.docker.internal:<port>` and it just works.
- **Fast/Deep Auto Route** *(beta)* — the bot automatically picks the fast or deep model based on the request; no manual switching needed.
- **Understands images** — users can attach images to their messages; the bot passes them straight to the model.
- **Gets reply context** — when someone replies to a Discord message, the quoted content is woven into the prompt naturally.
- **Renders tables** — any markdown table in the bot's reply is auto-converted to a PNG image (with CJK font support).

And that's not all — you can also give it tools:

- **Workspace file access** — mount a local folder and the bot becomes your team's living reference. Custom game data, shared docs, community wikis, internal FAQs — members ask, the bot answers from your own files.
- **DuckDuckGo search** — free web search that works with any model provider (`ENABLE_DUCKDUCKGO=on`, no API key needed).
- **Brave Search** — higher-quality web search via the official Brave Search API (`ENABLE_BRAVE_SEARCH=on` + `BRAVE_API_KEY`, free tier available).
- **Website tool** — lets the bot fetch and read URLs from the conversation, for any provider.
- **Custom API tools** — plug any HTTP API into the bot through the web dashboard; no code changes needed.
- **SQL database tools** — add a database connection string in the dashboard and the bot gets `list_tables` + `run_query` tools automatically.
- **Custom commands & tools (code)** — write your own in Python and drop them into a gitignored `custom/` folder. One function can be a slash command *and* a tool the agent calls itself — type `/stock AAPL`, or just ask "how's Apple doing?" and the agent calls it. See [Custom Commands & Tools](https://zhiro-labs.github.io/dango/features/extensions/).

Already have a Discord bot?

- **Embeddable** (Beta) — the whole thing is a standard discord.py Cog; drop Dango's agent and slash commands into any existing bot in a few lines.

## Before you start

You'll need:
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- An API key for whatever model provider you want to use (e.g. [Google AI Studio](https://aistudio.google.com), [OpenAI Platform](https://platform.openai.com/api-keys), [Anthropic Console](https://console.anthropic.com))

| Method | Extra requirements |
|---|---|
| Docker (recommended) | [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Windows), [OrbStack](https://orbstack.dev) (Mac), or [Docker Engine](https://docs.docker.com/engine/install/) (Linux) |
| uv (developers / low-spec machines) | Python 3.12–3.14, [uv](https://docs.astral.sh/uv/getting-started/installation/) |

## Discord Application Setup

### 1. Create a Bot

Follow the [Discord Quick Start guide](https://discord.com/developers/docs/quick-start/getting-started#step-1-creating-an-app) to create a new application and bot. Copy the **Bot Token** — you'll need it in a moment.

### 2. Enable Privileged Gateway Intents

Go to your application → **Bot** → **Privileged Gateway Intents** and turn on both of these:

| Intent | Why |
|---|---|
| **Server Members Intent** | Needed to read user display names |
| **Message Content Intent** | Needed to read message text |

### 3. Invite the Bot

When generating an invite link (**OAuth2 → URL Generator**), include these permissions:

| Category | Permission |
|---|---|
| General | View Channels |
| Text | Send Messages |
| Text | Attach Files |
| Text | Read Message History |

## Setup

Get your Bot Token from [Discord Application Setup](#discord-application-setup) first, then pick one of the options below.

> [!TIP]
> First time running commands on a computer? Read [Running commands for the first time](#running-commands-for-the-first-time) below before picking an option — it takes 2 minutes.

### Running commands for the first time

> **Tip:** I personally recommend [Warp](https://www.warp.dev/) — a modern terminal with autocomplete and AI assistance built in. Much nicer than the default terminal on any OS.

<details>
<summary>Click to expand — even if you've never typed a command before, this takes 2 minutes</summary>

Every option in this guide requires typing a few commands into a text window on your computer. A command window (called a "terminal", "shell", "command prompt", or "PowerShell" depending on the system) lets you control your computer by typing instead of clicking. You only need the basics.

**Opening the terminal**

| System | How |
|---|---|
| macOS | ⌘ Space → type `Terminal` → Enter |
| Windows | Win key → type `Terminal` or `PowerShell` → Enter |
| Linux | Ctrl + Alt + T |

**Your computer is a tree of folders**

```
~ (your home folder)
├── Downloads/
│   └── dango/        ← you'll work here
├── Documents/
└── Desktop/
```

**`cd` — moving between folders**

| Action | macOS / Linux | Windows (PowerShell) |
|---|---|---|
| Go into a folder | `cd Downloads` | `cd Downloads` |
| Go up one level | `cd ..` | `cd ..` |
| Jump straight there | `cd ~/Downloads/dango` | `cd ~\Downloads\dango` |

That's it. `cd` to the right folder, then copy-paste the commands.

</details>

---

### Option 1: Let an AI set it up for you (easiest)

No special tools needed — paste the prompt below into any AI assistant:

| Assistant | How it helps |
|---|---|
| [Claude](https://claude.ai), [ChatGPT](https://chatgpt.com), [Grok](https://grok.com) | Guides you step by step — you copy-paste each command into your terminal |
| [Claude Code](https://claude.ai/code), Codex | Runs commands directly on your computer for you |

<details>
<summary>Click to show the prompt</summary>

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

</details>

---

### Option 2: Docker (recommended)

No Python required — everything runs in a container and you configure it through the browser.

**1. Download `docker-compose.yml`**

```bash
cd ~/Downloads       # or wherever you'd like
curl -O https://raw.githubusercontent.com/zhiro-labs/dango/main/docker-compose.yml
```

**2. Start it up**

```bash
docker compose up -d && docker compose logs -f
```

`-d` starts the containers in the background; `logs -f` streams their output to your terminal. Press Ctrl+C to stop watching the logs — the containers keep running.

**3. Open the browser**

Head to `http://localhost:17860`. The Setup Wizard will ask for your Discord Token, model API key, and bot personality. Once you save, the bot connects to Discord automatically.

> [!NOTE]
> **Contributing or building from source?** Use `docker-compose.dev.yml` instead — it builds the image locally rather than pulling from the registry:
> ```bash
> docker compose -f docker-compose.dev.yml up -d --build
> ```

---

### Option 3: uv (developers / low-spec machines)

**AI-assisted** — paste this into any AI assistant to have it walk you through the steps:

<details>
<summary>Click to show the prompt</summary>

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

</details>

Or follow the steps manually:

**1. Clone and install**

```bash
cd ~/Downloads       # or wherever you'd like
git clone https://github.com/zhiro-labs/dango
cd dango
uv sync
```

**2. Set up your `.env`**

```bash
cp .env.example .env
```

Open `.env` and fill in at least these four:

```env
DISCORD_BOT_TOKEN=your_discord_token
FAST_API_KEY=your_api_key
FAST_MODEL=google:gemini-2.5-flash   # format: provider:model_id
CHAT_SYS_PROMPT_PATH=config/chat_sys_prompt.txt
```

**3. Copy the config files**

```bash
cp config/runtime.yml.example config/runtime.yml
cp config/chat_sys_prompt.txt.example config/chat_sys_prompt.txt
```

Edit `config/chat_sys_prompt.txt` to give the bot its personality.

**4. Run**

```bash
uv run main.py
```

The first time you run it, the Noto Sans CJK font (~100 MB) downloads automatically for table rendering.

## Stopping & restarting

### Docker

```bash
docker compose stop    # pause (keeps your data)
docker compose start   # resume
```

To fully remove containers (e.g. to start fresh): `docker compose down` — your data stays safe, but use `docker compose up -d` to bring it back.

> [!NOTE]
> **Computer restarted?** The containers don't come back automatically. `cd` into the folder with `docker-compose.yml` and run `docker compose start`.

### uv

**Stop:** Ctrl+C in the terminal running `uv run main.py`.

**Start again:**
```bash
uv run main.py
```

## Updating

### Docker

```bash
docker compose pull && docker compose up -d
```

Your data (`data/`, `config/`, `workspace/`) lives in a volume and won't be touched.

### uv

```bash
git pull && uv sync
```

Then restart the bot. `.env` and `config/` won't be overwritten.

## Running on a VPS

The Docker setup works on any VPS, but the web dashboard has no login screen — don't expose port `17860` to the internet. The fix is an SSH tunnel: keep the port closed in your firewall and forward it locally whenever you need to access the dashboard.

```bash
ssh -L 17860:localhost:17860 user@your-vps-ip
```

[→ Full VPS guide](https://zhiro-labs.github.io/dango/advanced/vps/)

## Embedding into Another Bot

Everything is a standard discord.py Cog, so you can drop Dango's agent and slash commands into any existing bot. To add your own commands and agent tools — including ones the agent can call itself — see [Custom Commands & Tools](https://zhiro-labs.github.io/dango/features/extensions/).

```bash
uv add git+https://github.com/zhiro-labs/dango
```

[→ Full embedding guide](https://zhiro-labs.github.io/dango/advanced/embedding/)

## Usage

### Starting a conversation

| How | What to do |
|---|---|
| **Mention** | `@BotName hello!` in any channel the bot can see |
| **Allowed channel** | Just send a message — no mention needed if the channel is in the allowed list (`/addchannel`) |
| **Direct Message** | DM the bot directly (your user ID needs to be added first with `/adduser`) |

Use `/newchat` to drop a session marker and start fresh. The bot ignores everything before that point.

### Slash Commands

| Command | What it does |
|---|---|
| `/newchat` | Reset conversation history |
| `/deep <message>` | Force the deep model for one message |
| `/addchannel` / `/removechannel` | Manage allowed channels (admin) |
| `/listchannels` | List all channels where the bot is allowed in this server (admin) |
| `/adduser` / `/removeuser` | Manage DM allowlist (admin) |
| `/listusers` | List all users allowed to DM the bot (admin) |
| `/refreshmetadata` | Refresh channel and user names in config comments (admin) |
| `/sethistorylimit <n>` | Set context window in messages (admin) |
| `/settimezone <tz>` | Set bot timezone with autocomplete (admin) |
| `/setactivity <text>` | Set Discord activity status (admin) |

[→ Full slash command reference](https://zhiro-labs.github.io/dango/usage/commands/)

## Documentation

Full docs at **[zhiro-labs.github.io/dango](https://zhiro-labs.github.io/dango)**

| Page | What's in it |
|---|---|
| [Environment Variables](https://zhiro-labs.github.io/dango/configuration/env-vars/) | Every config option with defaults — models, routing, tools, Gemini settings |
| [Model Providers & Routing](https://zhiro-labs.github.io/dango/features/models/) | Supported providers, dual-model AUTO_ROUTE, error fallback, local models |
| [Tools](https://zhiro-labs.github.io/dango/features/tools/) | Workspace, DuckDuckGo, Brave Search, website fetching, custom APIs, SQL databases |
| [Custom Commands & Tools](https://zhiro-labs.github.io/dango/features/extensions/) | Write your own slash commands and agent tools in Python in a gitignored `custom/` folder |
| [Embedding into Another Bot](https://zhiro-labs.github.io/dango/advanced/embedding/) | Load the Cogs into an existing discord.py bot |
| [Workflow Architecture](https://zhiro-labs.github.io/dango/features/workflow/) | How the 4-step Agno pipeline works under the hood |
| [VPS Deployment](https://zhiro-labs.github.io/dango/advanced/vps/) | Run on a server safely with SSH tunneling |

## Forking & CI

The two GitHub Actions workflows (`Build and Push Docker Image`, `Deploy Docs`) are gated to the upstream repo, so they **skip on forks** by default — no failed runs and no wasted Actions minutes. To enable them on your own fork, edit the `if:` line in each workflow under `.github/workflows/` and replace the owner with your account/org:

```yaml
# .github/workflows/docker.yml and docs.yml
if: github.repository_owner == 'your-account'
```

Once enabled, the Docker image name is derived from your repo automatically (`ghcr.io/your-account/dango`), and the docs workflow turns on GitHub Pages for you — no other edits needed.

---

Built with [Agno](https://docs.agno.com) · [discord.py](https://discordpy.readthedocs.io)
