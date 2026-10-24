---
summary: "Fixes for common issues — Dango system messages like [dango-sysinfo] and [dango_replaced_table_…_as_image], bot not responding, `/addchannel` having no effect, `on`/`off` vs `true`/`false` env-var formats, Gemini Search vs DuckDuckGo, error-fallback messages, `CUSTOM_APIS_JSON` parsing, testing custom tools, and workspace context."
tags:
  - Troubleshooting
  - dango-sysinfo
  - dango_replaced_table
  - Dango system messages
---

# Troubleshooting

## Dango system messages in Discord (`[dango-sysinfo]`, `[dango_replaced_table_…_as_image]`)

If you see a `[dango-sysinfo]` or `[dango_replaced_table_…_as_image]` marker in a Dango message, these are normal **Dango** system tokens — not errors or spam. Here is what each one means.

### `[dango-sysinfo]`

Dango prefixes its own status notes in the channel with a `> [dango-sysinfo]` blockquote. They are visible to users but stripped from the model's conversation history, so they never affect later replies. The most common one is the [error-fallback](#fallback-on-error-fires-what-does-the-message-look-like) notice:

```
> [dango-sysinfo] ⚡ google:gemini-2.0-flash failed — response served by google:gemini-2.5-pro.
```

### `[dango_replaced_table_…_as_image]`

When a reply contains a Markdown table, Dango renders it as a PNG image (CJK fonts included) so it stays readable on mobile, and leaves a placeholder in the text where the table was:

```
> `[dango_replaced_table_1399812345678901234_1_as_image]`
```

The two numbers are the Discord **message ID** and the table's position in the reply (`_1_` for the first table, `_2_` for the second, and so on). The rendered table is attached to the same message as an image — nothing is lost.

---

## Bot doesn't respond at all

**Check 1 — `DISCORD_BOT_TOKEN`**

Look for a login error in the startup logs. A wrong token produces:

```
discord.errors.LoginFailure: Improper token has been passed.
```

Double-check the token in `.env` (no extra spaces, no quotes).

**Check 2 — channel not added**

By default the bot only responds when `@mentioned`. Run `/addchannel` in the channel where you want it to respond to all messages.

**Check 3 — `FAST_API_KEY` error**

A bad API key produces an HTTP 401 or 403 from the model provider. Look for lines like:

```
⚠️  [call_discord_agent] google:gemini-2.0-flash failed ...
```

followed by the provider's error message. Verify the key in `.env` and that it matches the provider used in `FAST_MODEL`.

---

## `/addchannel` has no visible effect

`AdminCog` responds to slash commands with an ephemeral reply — the confirmation is visible **only to you** and disappears after a few seconds. If you don't see the reply at all:

- Confirm the bot has the `applications.commands` scope in Discord
- Confirm the user running the command has the **Administrator** permission
- Try `/listchannels` to verify whether the channel was added

---

## Feature doesn't turn on despite setting the env var

The most common cause is using `true`/`false` for a variable that expects `on`/`off`, or vice versa.

| Variable group | Correct format |
|---|---|
| `ENABLE_*`, `AUTO_ROUTE`, `FALLBACK_ON_ERROR`, `ENABLE_CONTEXTUAL_SYSTEM_PROMPT` | `on` / `off` |
| `GEMINI_SEARCH`, `GEMINI_URL_CONTEXT`, `GEMINI_THINKING_*` | `true` / `false` |

Incorrect values fail **silently** — no error is logged and the feature is simply not enabled.

---

## Gemini Search and DuckDuckGo both enabled

`GEMINI_SEARCH=true` (Google Search grounding) and `ENABLE_DUCKDUCKGO=on` (DuckDuckGo tool) can coexist, but they operate differently:

- **Gemini Search grounding** is applied by the Gemini API server; the model blends web results automatically into its response.
- **DuckDuckGo** is a tool the model can call; it returns raw search results that the model then synthesises.

When both are active, the model may call DuckDuckGo even when grounding is already enabled, potentially increasing latency. For `google:` models, prefer `GEMINI_SEARCH=true` alone and leave `ENABLE_DUCKDUCKGO=off`.

---

## `FALLBACK_ON_ERROR` fires — what does the message look like?

When fallback is triggered, a `[dango-sysinfo]` blockquote is prepended to the response in Discord:

```
> [dango-sysinfo] ⚡ google:gemini-2.0-flash failed — response served by google:gemini-2.5-pro.
```

This message is visible to users but is stripped from LLM history so it does not affect subsequent conversation context.

---

## The bot replies with a ⚠️ model error

When every model it tried has failed, Dango replies with a `[dango-sysinfo]` note that names the model(s) and says what went wrong, followed by the provider's own error text. The first line tells you where to look:

| Reply starts with | Cause | What to do |
|---|---|---|
| `The model is currently overloaded` | Provider returned a 5xx | Wait and retry; set a `DEEP_MODEL` on another provider with `FALLBACK_ON_ERROR=on` to ride out outages |
| `The model's rate limit or quota has been reached` | 429 / quota exhausted | Wait, or raise the plan limits with your provider |
| `The model provider rejected the API key or denied access` | Invalid key or no access (401/403) | Fix `FAST_API_KEY` / `DEEP_API_KEY` (Models tab in the dashboard) |
| `The configured model was not found` | Wrong model name (404) | Check `FAST_MODEL` / `DEEP_MODEL` against the provider's model list |
| `This conversation is too long for the model` | Input exceeds the context window | Run `/newchat`, or set `CONTEXT_TOKEN_BUDGET` so history is trimmed |
| `Could not reach the model provider` | Network error or timeout | Check connectivity; for local models, that the server is running at `FAST_BASE_URL` |
| `The model provider rejected the request` | Other 4xx | Read the provider's error text below the reply |
| `The model returned an error` | Anything else | Read the provider's error text and the bot logs |

---

## `CUSTOM_APIS_JSON` tool is not registered

The most common cause is a multi-line JSON value in `.env`. The parser reads the variable as a single line and cannot parse fragmented JSON.

Compress to one line:

```bash
echo '[{"name":"weather","base_url":"https://api.example.com","description":"Weather"}]' | jq -c '.'
```

Then paste the output as the value in `.env`. See [Tools — Custom API Tools](features/tools.md#custom-api-tools) for details.

---

## Testing custom commands and tools without starting the bot

Functions you write in `custom/*.py` ([Custom Commands & Tools](features/extensions.md)) are plain Python functions — call them directly in a test script. If a function declares `ctx`, construct a `Ctx`; its `source` field (`"agent"` or `"discord_command"`) is what your code branches on:

```python
import asyncio
from dango.extensions import Ctx
from custom.commands import stock   # your own custom file

async def test():
    ctx = Ctx(source="agent", author_name="tester")
    print(await stock(ctx, ticker="AAPL"))

asyncio.run(test())
```

Functions without a `ctx` parameter are simpler still — call them with their arguments directly. Testing the logic in isolation means you do not need a running Discord bot for most development iterations.

---

## Workspace context not injected

If `ENABLE_WORKSPACE=on` is set but the workspace instructions never appear in the system prompt:

1. **Empty folder** — if `WORKSPACE_ROOT` contains no `.md` or `.txt` files, context generation is skipped entirely.
2. **Generation failed** — look for `⚠️ Workspace context generation returned empty` in the startup logs. This means the LLM returned an empty response; the context file was not written.
3. **Cache is stale** — edit or touch a file in the workspace folder; the background watcher regenerates the context within 30 seconds.
