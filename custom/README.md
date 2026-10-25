# Custom extensions

Drop your own Discord commands and agent tools in this directory. Everything
here (except this `README.md` and the `*.example` templates) is **gitignored**,
so your code never affects `git status` and survives `git pull`.

## Quick start

```bash
cp custom/commands.py.example custom/commands.py
cp custom/tools.py.example    custom/tools.py
# edit them, then restart the bot
```

Any `*.py` file in `custom/` is auto-loaded at startup. Use any filenames and
split across as many files as you like.

## The three decorators

```python
from dango.extensions import command, agent_tool, command_and_tool, Ctx
```

| Decorator           | Discord slash command | Callable by the agent |
| ------------------- | :-------------------: | :-------------------: |
| `@command`          | ✅                    | ❌                    |
| `@agent_tool`       | ❌                    | ✅                    |
| `@command_and_tool` | ✅                    | ✅                    |

Whether the agent can call your function is decided **only** by the decorator —
exposure is always an explicit, per-function opt-in.

## Writing a function

- Return a string. As a command it is sent as the reply; as a tool it is
  returned to the model.
- Declare `ctx: Ctx` as the **first** parameter (optional) to receive call
  context: `ctx.source` (`"discord_command"` | `"agent"`), `ctx.author_name`,
  `ctx.channel_id`, `ctx.channel_name`, `ctx.guild_id`, `ctx.guild_name`, and
  `ctx.interaction` (Discord only).
- For `@command_and_tool`, keep parameters to simple scalars (`str`, `int`,
  `bool`, `float`) so both worlds can represent them. `@command`-only functions
  may use richer Discord types.
- Write a docstring with an `Args:` section — the agent reads it to decide when
  and how to call your tool.
- `async def` and `def` are both supported.

## Restricting access and Agno options

```python
@agent_tool(name="delete_event", requires_permissions="manage_events")
async def delete_event(ctx: Ctx, title: str) -> str: ...
```

- `requires_permissions` (all three decorators): Discord permission name(s)
  the caller must hold, checked on every call from chat and from Discord.
- `@agent_tool` / `@command_and_tool` pass other keyword arguments to Agno's
  `@tool` (`show_result`, `tool_hooks`, `cache_results`, …). Human-in-the-loop
  options such as `requires_confirmation` are rejected: the Discord flow never
  resumes a paused run.

Details: `docs/features/extensions.md`.

## Notes

- A missing or broken file is logged and skipped; it never crashes the bot.
- New slash commands are synced to Discord on the next startup (`on_ready`).
- Configure a different directory with the `CUSTOM_DIR` environment variable.
