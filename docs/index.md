# Dango

**Dango** is a Discord bot built on [Agno](https://docs.agno.com) that connects to virtually any AI model provider — Google Gemini/Gemma, OpenAI, Anthropic, Groq, Ollama, and more. Drop it into a channel and it will chat, answer questions, render tables as images, and let you tweak everything on the fly with slash commands — no restarts needed.

## Highlights

| Feature | Description |
|---|---|
| **Any AI provider** | `provider:model_id` format — the bot sets up the right SDK and API key automatically |
| **Dual-model routing** | Pair a fast model for simple messages and a deep model for complex ones; `AUTO_ROUTE=on` switches automatically |
| **Local models** | Point `FAST_BASE_URL` at Ollama, LM Studio, or vLLM and run everything offline |
| **Table rendering** | Markdown tables in replies are auto-converted to PNG images (CJK font support included) |
| **Web dashboard** | Browser-based setup wizard and admin UI — no config file editing needed |
| **No restarts** | Channels, users, history limit, timezone, and activity are all adjustable live via slash commands |
| **Image support** | Attach images to messages; the bot passes them straight to the model |
| **Tools** | Web search (DuckDuckGo), URL fetching, workspace file access, custom APIs, SQL databases |
| **Embeddable** | Drop the Cogs into any existing discord.py bot in a few lines |

## Before you start

You need:

- A **Discord bot token** — follow [Discord Setup](getting-started/discord-setup.md) to create one (~5 minutes)
- An **API key** for your model provider ([Google AI Studio](https://aistudio.google.com/apikey), [OpenAI](https://platform.openai.com/api-keys), [Anthropic](https://console.anthropic.com/), [Groq](https://console.groq.com/), etc.) — or a local [Ollama](https://ollama.com) instance (no key needed)

| Method | Also requires |
|---|---|
| **Docker** (recommended) | [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Windows), [OrbStack](https://orbstack.dev) (Mac), or [Docker Engine](https://docs.docker.com/engine/install/) (Linux) |
| **uv** (developers) | Python 3.12+, [uv](https://github.com/astral-sh/uv) |

??? tip "First time running commands on a computer? Start here."

    Every method below requires typing a few commands into a terminal window. Open one like this:

    | System | How |
    |---|---|
    | macOS | ⌘ Space → type `Terminal` → Enter |
    | Windows | Win key → type `Terminal` or `PowerShell` → Enter |
    | Linux | Ctrl + Alt + T |

    The only command you need to know is `cd` — it moves you between folders:

    | Action | macOS / Linux | Windows (PowerShell) |
    |---|---|---|
    | Go into a folder | `cd Downloads` | `cd Downloads` |
    | Go up one level | `cd ..` | `cd ..` |
    | Jump straight there | `cd ~/Downloads/dango` | `cd ~\Downloads\dango` |

    That's it — `cd` to the right folder, then copy-paste the commands.

## Quick Start

=== "AI-assisted (easiest)"

    No special tools needed — paste a prompt into any AI assistant and it will walk you through installation step by step.

    | Assistant | What it does |
    |---|---|
    | [Claude](https://claude.ai), [ChatGPT](https://chatgpt.com), [Grok](https://grok.com) | Guides you through each command — you copy-paste into your terminal |
    | [Claude Code](https://claude.ai/code), Codex | Runs the commands on your computer directly |

    ??? example "Docker setup prompt (click to expand)"

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

    ??? example "uv setup prompt (click to expand)"

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

=== "Docker (recommended)"

    No Python required — everything runs in a container; configure from the browser.

    **1. Download `docker-compose.yml`**

    ```bash
    cd ~/Downloads       # or wherever you'd like
    curl -O https://raw.githubusercontent.com/zhiro-labs/dango/main/docker-compose.yml
    ```

    **2. Start the containers**

    ```bash
    docker compose up -d && docker compose logs -f
    ```

    `-d` runs in the background. `logs -f` streams output to your terminal — press **Ctrl+C** to stop watching; the containers keep running.

    **3. Open the setup wizard**

    Go to `http://localhost:17860`. The wizard asks for your Discord token, model API key, and bot personality. Save, and the bot connects to Discord automatically.

    **4. Test the bot**

    Mention the bot in Discord: `@YourBotName hello!` — it should reply within a few seconds.

    [→ Full Docker guide](getting-started/docker.md)

=== "uv (developers)"

    For developers or anyone who prefers running directly without Docker.

    **1. Clone and install**

    ```bash
    git clone https://github.com/zhiro-labs/dango
    cd dango
    uv sync
    ```

    **2. Copy config files**

    ```bash
    cp .env.example .env
    cp config/runtime.yml.example config/runtime.yml
    cp config/chat_sys_prompt.txt.example config/chat_sys_prompt.txt
    ```

    **3. Fill in `.env`**

    Open `.env` and set at minimum:

    ```env
    DISCORD_BOT_TOKEN=your_discord_token
    FAST_API_KEY=your_api_key
    FAST_MODEL=google:gemini-2.5-flash   # format: provider:model_id
    CHAT_SYS_PROMPT_PATH=config/chat_sys_prompt.txt
    ```

    **4. Edit the system prompt**

    Open `config/chat_sys_prompt.txt` and give the bot its personality.

    **5. Run**

    ```bash
    uv run main.py
    ```

    On first run, Noto Sans CJK fonts (~100 MB) download automatically for table rendering.

    **6. Test the bot**

    Mention the bot in Discord: `@YourBotName hello!` — it should reply within a few seconds.

    [→ Full uv guide](getting-started/uv.md)

## Project Structure

```
dango/                         # repo root
├── main.py                    # Entry point
├── dango/                     # Python package
│   ├── app_config.py          # Web UI config injection
│   ├── workflow.py            # Agno Workflow definition
│   ├── steps/                 # 4-step pipeline
│   │   ├── fetch_history.py
│   │   ├── call_agent.py      # Multi-provider LLM call
│   │   ├── table_steps.py     # Table → PNG rendering
│   │   └── send_response.py   # Discord send (channel + interaction followup)
│   ├── commands/
│   │   ├── chat_commands.py   # ChatCog: on_message, on_interaction, /newchat, /deep
│   │   └── admin_commands.py  # AdminCog: all admin slash commands
│   ├── tools/
│   │   ├── __init__.py        # Public API: discord_tool, check_roles, set_ephemeral, …
│   │   └── discord_tool.py    # Tool helpers and ContextMenuDef
│   └── utils/
├── web/                       # FastAPI dashboard
├── config/                    # System prompt & runtime config
└── tests/
```
