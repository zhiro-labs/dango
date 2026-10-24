---
summary: "All env vars — model selection, routing, tools, skills, Gemini-specific settings, per-model overrides."
description: "Complete reference for all Dango environment variables — model provider settings, dual-model routing, tool toggles, skills (ENABLE_SKILLS), Gemini thinking mode, history limits, and more."
tags:
  - Configuration
  - Environment Variables
  - Skills
  - Reference
---

# Environment Variables

Configuration lives in `.env` (uv path) or `data/config.yaml` (Docker / web dashboard). Both map to the same environment variables described here.

The `data/config.yaml` file is normally written by the web setup wizard, but for headless deploys you can hand-write it: copy [`config.yaml.example`](https://github.com/zhiro-labs/dango/blob/main/config.yaml.example) to `data/config.yaml` and edit. (The uv path uses [`.env.example`](https://github.com/zhiro-labs/dango/blob/main/.env.example) instead.)

::: warning `on`/`off` vs `true`/`false`
Most variables use `on`/`off`. The `GEMINI_*` variables use `true`/`false` because they are passed directly to the Google SDK.

**Mixing them up silently disables the feature** — `ENABLE_DUCKDUCKGO=true` will not report an error but the tool will not be registered.

Each variable in the tables below shows its accepted values.
:::

## Required

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Your Discord bot token |
| `FAST_MODEL` | Model in `provider:model_id` format (e.g. `google:gemini-2.5-flash`) |
| `FAST_API_KEY` | API key for the fast model's provider. For local servers (Ollama, LM Studio) that require no authentication, set this to any non-empty string (e.g. `local`). |

## uv path only

| Variable | Description |
|---|---|
| `CHAT_SYS_PROMPT_PATH` | Path to the system prompt file (e.g. `config/chat_sys_prompt.txt`). Docker users configure the system prompt through the web dashboard instead. |

## Dual-model routing

| Variable | Default | Description |
|---|---|---|
| `DEEP_MODEL` | _(off)_ | Second model in `provider:model_id` format. Leave blank to disable routing. |
| `DEEP_API_KEY` | same as `FAST_API_KEY` | API key for the deep model (only needed for a different provider) |
| `AUTO_ROUTE` | `off` | **`on`/`off`** — send complex messages to `DEEP_MODEL` automatically |
| `FALLBACK_ON_ERROR` | `off` | **`on`/`off`** — fall back to the other model when one returns an error |

See [Model Providers & Routing](../features/models.md) for details on how routing works.

## Custom endpoints

Useful for local inference servers (Ollama, LM Studio, vLLM) or API gateways.

| Variable | Description |
|---|---|
| `FAST_BASE_URL` | Custom endpoint for the fast model |
| `DEEP_BASE_URL` | Custom endpoint for the deep model |

When the bot runs in Docker and the model server runs on the host, use `host.docker.internal` instead of `localhost`:

| Server | Model string | Base URL |
|---|---|---|
| Ollama | `ollama:llama3.2` | `http://host.docker.internal:11434` |
| LM Studio | `lmstudio:model-name` | `http://host.docker.internal:1234/v1` |
| vLLM | `vllm:model-name` | `http://host.docker.internal:8000/v1` |
| Any OpenAI-compatible | `openai-chat:model-name` | `http://host.docker.internal:<port>/v1` |

## Bot behaviour

| Variable | Default | Description |
|---|---|---|
| `ENABLE_CONTEXTUAL_SYSTEM_PROMPT` | `on` | **`on`/`off`** — inject user display names and current time into the system prompt |
| `CONTEXT_TOKEN_BUDGET` | `0` | Max input tokens per request; oldest messages are dropped when exceeded. `0` = no limit. |
| `ENABLE_MESSAGE_BATCHING` | `off` | **`on`/`off`** — merge rapid consecutive messages from the same person into one reply (Discord-style grouping) |
| `MESSAGE_BATCH_WINDOW` | `5` | Seconds to wait for the next message before replying; each new message resets the window |
| `MESSAGE_BATCH_MAX_WAIT` | `15` | Hard cap (seconds) on how long one burst is held, measured from its first message |

## Web search & browsing

| Variable | Default | Description |
|---|---|---|
| `ENABLE_DUCKDUCKGO` | `off` | **`on`/`off`** — free DuckDuckGo search, works with any provider |
| `ENABLE_BRAVE_SEARCH` | `off` | **`on`/`off`** — web search via the Brave Search API (requires `BRAVE_API_KEY`) |
| `BRAVE_API_KEY` | — | Brave Search API key; free tier at [brave.com/search/api](https://brave.com/search/api/) |
| `ENABLE_WEBSITE_TOOLS` | `off` | **`on`/`off`** — let the bot fetch and read URLs from the conversation |

## Workspace

| Variable | Default | Description |
|---|---|---|
| `ENABLE_WORKSPACE` | `off` | **`on`/`off`** — give the bot read access to a local folder |
| `WORKSPACE_ROOT` | `workspace/` | Root folder the bot can access |
| `WORKSPACE_SYS_PROMPT_PATH` | `config/workspace_sys_prompt.txt` | Where to store the generated workspace context |

See [Tools](../features/tools.md) for more on workspace behaviour.

## Skills

| Variable | Default | Description |
|---|---|---|
| `ENABLE_SKILLS` | `off` | **`on`/`off`** — let the bot load skills from `SKILLS_ROOT` on demand |
| `SKILLS_ROOT` | `skills/` | Folder holding skill subfolders, each with a `SKILL.md` |

A malformed `SKILL.md` aborts startup with a clear error rather than being silently skipped. See [Tools](../features/tools.md) for the skill folder layout.

## Custom tools

| Variable | Default | Description |
|---|---|---|
| `ENABLE_CUSTOM_APIS` | `off` | **`on`/`off`** — enable HTTP API tools defined in `CUSTOM_APIS_JSON` |
| `CUSTOM_APIS_JSON` | `[]` | JSON array of REST API configs (`name`, `base_url`, `api_key`, `description`). **Must be a single line** — see [Tools](../features/tools.md#custom-api-tools) |
| `ENABLE_SQL_DATABASES` | `off` | **`on`/`off`** — enable SQL tools defined in `SQL_DATABASES_JSON` |
| `SQL_DATABASES_JSON` | `[]` | JSON array of database configs (`name`, `db_url`, `description`) |
| `CUSTOM_DIR` | `custom` | Directory scanned for Python extension files (`*.py`) — see [Custom Commands & Tools](../features/extensions.md) |

For writing your own commands and agent tools in Python (no env var needed — just
drop files into `custom/`), see [Custom Commands & Tools](../features/extensions.md).

## Large tool results

| Variable | Default | Description |
|---|---|---|
| `TOOL_RESULT_OFFLOAD_CHARS` | `16000` | Tool results longer than this many characters reach the model as a preview it can read further into; the full text sits in a temporary SQLite database deleted when the bot stops. `0` = always send results in full. See [Large Tool Results](../features/tools.md#large-tool-results). |
| `TOOL_RESULT_TTL_SECONDS` | `3600` | How long a stored result stays readable. `0` = until the bot stops. |

Both must be whole numbers of 0 or more; anything else stops the bot at startup with an error naming the variable.

## Web dashboard

Set these on the `web` service, not the bot.

| Variable | Default | Description |
|---|---|---|
| `WEB_ALLOWED_HOSTS` | _(empty)_ | Comma-separated extra hostnames or IPs the dashboard may be opened at, e.g. `192.168.1.50,dango.lan`. `localhost`, `127.0.0.1` and `::1` are always allowed. Requests for any other `Host` get `400` — this blocks DNS-rebinding attacks. See [VPS Deployment](../advanced/vps.md#accessing-from-another-device) before adding one. |

## Google / Gemini-specific

These apply to `google:` models only. Ignored for all other providers.

### Search & grounding

| Variable | Default | Description |
|---|---|---|
| `GEMINI_SEARCH` | `true` | **`true`/`false`** — enable Google Search grounding |
| `GEMINI_GROUNDING_THRESHOLD` | model default | Apply grounding only when confidence is below this value (0.0–1.0) |
| `GEMINI_URL_CONTEXT` | `false` | **`true`/`false`** — let the model fetch URLs mentioned in the conversation (Gemini only; not `gemma-*`) |

### Thinking (Gemini 2.5+ / Gemma 4)

| Variable | Default | Description |
|---|---|---|
| `GEMINI_THINKING_BUDGET` | model default | Token budget for reasoning; `0` disables thinking |
| `GEMINI_THINKING_LEVEL` | model default | `low` or `high` |

### Per-model overrides

Any `GEMINI_*` variable can be overridden for just one model using the `FAST_` or `DEEP_` prefix. `CONTEXT_TOKEN_BUDGET` (defined under [Bot behaviour](#bot-behaviour) above) also supports per-model overrides:

| Shared default | Fast override | Deep override |
|---|---|---|
| `GEMINI_SEARCH` | `FAST_SEARCH` | `DEEP_SEARCH` |
| `GEMINI_GROUNDING_THRESHOLD` | `FAST_GROUNDING_THRESHOLD` | `DEEP_GROUNDING_THRESHOLD` |
| `GEMINI_URL_CONTEXT` | `FAST_URL_CONTEXT` | `DEEP_URL_CONTEXT` |
| `GEMINI_THINKING_BUDGET` | `FAST_THINKING_BUDGET` | `DEEP_THINKING_BUDGET` |
| `GEMINI_THINKING_LEVEL` | `FAST_THINKING_LEVEL` | `DEEP_THINKING_LEVEL` |
| `CONTEXT_TOKEN_BUDGET` | `FAST_CONTEXT_TOKEN_BUDGET` | `DEEP_CONTEXT_TOKEN_BUDGET` |
