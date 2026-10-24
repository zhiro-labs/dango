---
summary: "Four-step Agno Workflow — FetchHistory → LLMChat → ExtractRenderTables → SendResponse. Entry point: `on_message` in ChatCog (and the `/deep` command), which builds message_data and calls workflow.arun()."
description: "How Dango processes Discord messages: a four-step Agno Workflow that fetches history, calls the AI agent, renders tables as images, and sends the response back."
tags:
  - Architecture
  - Agno
  - Workflow
---

# Workflow Architecture

Every message runs through a four-step [Agno Workflow](https://docs.agno.com/workflows/overview):

```
on_message (ChatCog)
    └── Workflow.arun()
            ├── Step 1: FetchHistory
            ├── Step 2: LLMChat
            ├── Step 3: ExtractRenderTables
            └── Step 4: SendResponse
```

The workflow is defined in [`dango/workflow.py`](https://github.com/zhiro-labs/dango/blob/main/dango/workflow.py) and created once at startup via `create_discord_workflow()`.

## Step 1 — FetchHistory

**File:** `dango/steps/fetch_history.py`

Pulls recent messages from the channel using the Discord API and converts them to Agno `Message` objects. Key behaviours:

- Stops at a `[new chat]` marker (dropped by `/newchat`)
- Respects `history_limit` from `runtime.yml`
- Resolves `dango_deep_*.json` attachments back to proper user turns (used by `/deep`)
- Builds a `mention_map` (`<@123>` → `"Alice"`) for mention resolution in the next step

## Step 2 — LLMChat

**File:** `dango/steps/call_agent.py` (the agents themselves — settings, models, tools, skills, routing and retries — live in `dango/agent/`)

Runs the Agno Agent against the formatted history plus the current message. Key behaviours:

- Selects fast or deep agent based on `AUTO_ROUTE`, `_force_deep` flag, or URL-upgrade logic
- Resolves `@mention` tokens in message content using the `mention_map`
- Downloads image attachments and passes them to the model
- Trims history to `CONTEXT_TOKEN_BUDGET` before sending
- Handles retries (Gemini: model-level; others: 2× at agent level) and bidirectional fallback

The Agno `Agent` uses a dynamic `instructions` callback that reads `session_state` on every call, injecting the user's display name and current time into the system prompt when `ENABLE_CONTEXTUAL_SYSTEM_PROMPT=on`.

## Step 3 — ExtractRenderTables

**File:** `dango/steps/table_steps.py`

Scans the LLM response for Markdown tables and renders each one as a PNG using Pillow. Noto Sans CJK fonts are used so Chinese, Japanese, and Korean text renders correctly.

If no tables are found, this step passes through transparently.

## Step 4 — SendResponse

**File:** `dango/steps/send_response.py`

Sends the final response back to Discord:

- Splits messages longer than Discord's 2000-character limit across multiple messages
- Attaches rendered table PNG files (and cleans up the temp files afterward)
- Replies to the original message when it can still be fetched, otherwise falls back to `channel.send()`
- Appends any `[dango-sysinfo]` notes (e.g. fallback notifications)
- Handles error messages forwarded from earlier steps

## Entry points

The workflow is invoked from two discord.py Cogs:

| Cog | File | Triggers |
|---|---|---|
| `ChatCog` | `dango/commands/chat_commands.py` | `on_message`, `/newchat`, `/deep` |
| `AdminCog` | `dango/commands/admin_commands.py` | All admin slash commands |

The workflow is driven by `ChatCog.on_message`: it fires for every Discord message, checks whether the bot should respond (mention, allowed channel, or allowed DM user), builds the `message_data` structure, and calls `workflow.arun()`. The `/deep` command runs the same pipeline with the deep model forced on.

Custom slash commands and agent tools added via `dango.extensions` plug in separately — see [Custom Commands & Tools](extensions.md).
