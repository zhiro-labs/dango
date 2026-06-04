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

**File:** `dango/steps/call_agent.py`

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
- Attaches rendered table PNG files
- Prepends any `[dango-sysinfo]` notes (e.g. fallback notifications)
- Handles error messages from earlier steps

## Step 4 — SendResponse

**File:** `dango/steps/send_response.py`

Sends the final response back to Discord:

- Splits messages longer than Discord's 2000-character limit across multiple messages
- Attaches rendered table PNG files and any `discord.Embed` objects set by tools via `set_discord_response()`
- Respects the `suppress_text` flag — when a tool has already sent content directly (e.g. a native `discord.ui.View`), the LLM text is silently dropped
- For interaction-triggered runs (button, modal, context menu), uses `interaction.followup.send()` instead of `channel.send()`; respects the `ephemeral` flag set by `set_ephemeral()`
- Prepends any `[dango-sysinfo]` notes (e.g. fallback notifications)

## Entry points

The workflow is invoked from two discord.py Cogs:

| Cog | File | Triggers |
|---|---|---|
| `ChatCog` | `dango/commands/chat_commands.py` | `on_message`, `on_interaction`, `/newchat`, `/deep` |
| `AdminCog` | `dango/commands/admin_commands.py` | All admin slash commands |

`ChatCog` has two entry paths into the workflow:

**`on_message`** — the standard path. Fires for every Discord message; the Cog checks whether the bot should respond (mention, allowed channel, or allowed DM user), then calls `workflow.arun()`.

**`on_interaction`** — fires for Discord Interactions not handled by app_commands. Dango routes two kinds through the workflow:

- **Modal submits** whose `custom_id` starts with `dango_modal:` — the modal fields are assembled into a natural-language string the agent reads as a user message
- **Component interactions** (button clicks, select menus) whose `custom_id` starts with `dango_component:` — the component's value and the original message context are passed to the agent

Context menu commands registered via `ContextMenuDef` are handled similarly: the right-clicked content is formatted and sent through the workflow.

All entry points build the same `message_data` structure and call the same `workflow.arun()`, so tools see a consistent `session_state` regardless of how the request arrived.
