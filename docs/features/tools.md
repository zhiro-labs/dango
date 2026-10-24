---
summary: "DuckDuckGo search, website fetching, workspace file access, on-demand skills, custom HTTP APIs, SQL databases, and keeping large tool results out of context."
description: "Extend Dango with web search (DuckDuckGo, Brave Search), URL fetching, workspace file access, on-demand skills (SKILL.md folders), custom HTTP API tools, and SQL database queries — all configurable from the web dashboard."
tags:
  - Tools
  - Skills
  - Web search
  - SQL
  - Custom APIs
---

# Tools

The tools on this page are **no-code** — turn them on with an env var or in the
dashboard, no Python required. To write your own commands and agent tools in
Python instead, see [Custom Commands & Tools](extensions.md).

## Web Search (DuckDuckGo)

Free web search that works with any model provider — no API key required.

```env
ENABLE_DUCKDUCKGO=on
```

The bot gets a `duckduckgo_search` tool and uses it when the model decides a web search would help answer a question.

## Web Search (Brave Search API)

Higher-quality web search via the official [Brave Search API](https://brave.com/search/api/). Requires an API key — a free tier (2,000 queries/month) is available.

```env
ENABLE_BRAVE_SEARCH=on
BRAVE_API_KEY=your-key-here
```

The bot gets a `brave_search` tool. Both search tools can be enabled at the same time; the model picks per query. In the web dashboard, the toggle and API key field are under **Models → Features**.

## Website Tool

Lets the bot fetch and read URLs that appear in the conversation.

```env
ENABLE_WEBSITE_TOOLS=on
```

Works with any provider. For Google Gemini, there's also a native alternative — `GEMINI_URL_CONTEXT=true` — which is more tightly integrated with the model but only works for `google:` providers and not `gemma-*` models.

## Workspace File Access

Mount a local folder and the bot can read, list, and search files inside it. Good for custom game data, knowledge bases, or any content you want the bot to look up on demand.

```env
ENABLE_WORKSPACE=on
WORKSPACE_ROOT=workspace    # relative or absolute path
```

The default `workspace/` folder is inside the project directory. Its contents are gitignored.

```
dango/
└── workspace/
    ├── items.json
    ├── rules.md
    └── characters.csv
```

**What files can it read?** Any file under 100,000 lines or 10 MB. Plain-text formats (`.txt`, `.json`, `.yaml`, `.md`, `.csv`) are most useful — binary files come out as raw bytes. Files over 10 MB are silently skipped.

### Workspace context injection

On startup, the bot uses the LLM to write a short description of `WORKSPACE_ROOT` contents and injects it into the system prompt. That way the bot knows when to reach for the workspace tool.

- **First run**: the context is generated and saved to `WORKSPACE_SYS_PROMPT_PATH` (default: `config/workspace_sys_prompt.txt`)
- **Later runs**: the saved file is used as-is; edit it freely and your changes stick
- **Live reload**: a background task checks the workspace every 30 seconds and reloads if files change

### Edge cases

| Situation | Behaviour |
|---|---|
| Workspace folder is empty | Context generation is skipped; workspace context is not injected. Bot starts normally. |
| LLM returns an empty response during generation | A warning is printed (`⚠️ Workspace context generation returned empty`) and the context file is not written. Bot continues without workspace context. |
| File exceeds 10 MB | The file is silently skipped by the workspace tool. |

## Skills

A **skill** is a self-contained folder that packages instructions (and optional scripts/references) for a specific capability. Unlike a regular tool, a skill's instructions are loaded *on demand* — the bot reads them only when it decides the skill is relevant, keeping the base context lean.

```env
ENABLE_SKILLS=on
SKILLS_ROOT=skills          # relative or absolute path
```

Drop one folder per skill into `SKILLS_ROOT`. The default `skills/` folder lives inside the project directory and its contents are gitignored.

```
dango/
└── skills/
    └── my-skill/
        ├── SKILL.md          # required: when & how to use the skill (YAML frontmatter + body)
        ├── scripts/          # optional: runnable script templates
        └── references/       # optional: supporting docs
```

Each `SKILL.md` must start with YAML frontmatter, for example:

```markdown
---
name: greet
description: Greet a user warmly in their own language.
---

When the user says hello, reply with a warm greeting that matches their language.
```

At runtime the bot gains Agno's built-in `get_skill_instructions`, `get_skill_reference`, and `get_skill_script` tools to pull skill content as needed.

### How a skill gets used

- **Automatically** — the model sees every skill's `name` + `description` in its
  system prompt and decides on its own to load a skill when a message matches.
  Users type nothing special; they just phrase their request naturally. Write
  the `description` like a trigger ("what it does + when to use it") — vague
  descriptions never fire.
- **Explicitly with [`/skill`](../usage/commands.md)** — pick a skill from the
  autocomplete and the bot hard-applies that skill's instructions to the
  response, no guessing involved.

::: warning Validation is strict
A malformed `SKILL.md` (e.g. missing frontmatter) **aborts startup** with a clear error such as `Failed to load skills from '…': SKILL.md must start with YAML frontmatter (---)`. This is intentional — broken skills are never silently dropped. Fix the file or set `ENABLE_SKILLS=off`.
:::

## Custom API Tools

Plug any HTTP API into the bot through the web dashboard — no code changes needed.

```env
ENABLE_CUSTOM_APIS=on
CUSTOM_APIS_JSON=[{"name": "weather", "base_url": "https://api.example.com", "api_key": "secret", "description": "Weather API"}]
```

::: warning Single-line requirement
`CUSTOM_APIS_JSON` must be a single line in `.env`. Multi-line JSON silently fails — the variable is empty and no tools are created, with no error message.

Compress your JSON to a single line before pasting:
```bash
echo '[{"name":"weather",...}]' | jq -c '.'
```

The Docker web dashboard handles this automatically — use it if you want to avoid the formatting entirely.
:::

Each entry creates a tool named `call_<name>_api`. The model decides when to call it based on the `description` field — be descriptive about what the API does and what kind of questions should trigger it. When the bot calls the tool, it can send `GET` or `POST` to any path under `base_url`, pass query parameters and a JSON body, with Bearer auth automatically added if `api_key` is set.

Fields per entry:

| Field | Required | Description |
|---|---|---|
| `name` | yes | Unique name; becomes part of the tool function name |
| `base_url` | yes | Base URL of the API |
| `api_key` | no | Sent as `Authorization: Bearer <key>` |
| `description` | no | Shown to the model to help it decide when to call this tool |

The Docker dashboard provides a UI for managing these without editing JSON directly.

## SQL Databases

Add a database connection string and the bot gets `list_tables` and `run_query` tools automatically. Queries are read-only.

```env
ENABLE_SQL_DATABASES=on
SQL_DATABASES_JSON=[{"name": "analytics", "db_url": "postgresql://user:pass@host/dbname", "description": "Analytics DB"}]
```

Supported databases: PostgreSQL, MySQL, SQLite, and anything SQLAlchemy supports.

Fields per entry:

| Field | Required | Description |
|---|---|---|
| `name` | yes | Unique name for this database |
| `db_url` | yes | SQLAlchemy connection string |
| `description` | no | Helps the model understand what data is available |

## Custom Code (Commands & Tools)

Need something the no-code tools above can't express? Write it in Python. Drop a
file into the gitignored `custom/` directory and a single function can become a
Discord slash command, an agent tool, or both at once:

```python
from dango.extensions import command_and_tool, Ctx

@command_and_tool(name="stock", description="Get a stock quote by ticker")
async def stock(ctx: Ctx, ticker: str) -> str:
    ...
```

See [Custom Commands & Tools](extensions.md) for the full guide.

## Large Tool Results

A single tool call can return far more text than the model needs: a long web
page, a crawl of several pages, a verbose API response. Sent in full, that text
is paid for on every model call that follows in the same reply, and it can
overflow a small local model's context window.

So a result longer than `TOOL_RESULT_OFFLOAD_CHARS` (default 16,000 characters,
about 4,000 tokens) reaches the model as a short preview — the first lines, the
total size and a result id. The model gets two extra tools to go back for more:

- `read_result` reads any range of lines (up to 16,000 characters per call)
- `search_result` finds the passages matching a pattern

This applies to every tool, including your own [custom tools](extensions.md).
Nothing is summarized away; the full text stays readable.

**Where the full text lives.** In a SQLite file inside a fresh temporary
directory (`dango-tool-results-*` in the system temp folder; inside Docker,
the container's own `/tmp`, not the `data/` volume). It is created when the bot
starts and deleted when it stops; while running, results expire after
`TOOL_RESULT_TTL_SECONDS` (default one hour). The agents themselves keep no
database, so conversations are never stored. If the process is killed outright,
the directory is left behind with at most the last hour of results.

**Tuning.** Reading a long result piece by piece costs more than sending it
once, because every earlier piece is resent with each later call. So:

| Model | Suggested `TOOL_RESULT_OFFLOAD_CHARS` |
|---|---|
| Large-context cloud model (Gemini, GPT, Claude) | Raise it, e.g. `60000`, so most pages arrive whole |
| Small local model (Ollama, LM Studio) | Keep the default or lower it, e.g. `8000` |
| Always send results in full | `0` |

Both values are also under **Models → Advanced** in the dashboard.
