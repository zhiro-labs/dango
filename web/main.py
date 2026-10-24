import asyncio
import os
import re
import signal
import tomllib
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from collections.abc import Callable

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from dango.utils.runtime_config import DEFAULT_SETTINGS, RuntimeConfig, RuntimeConfigError

from . import docker_api
from .config_store import is_setup_complete, load_config, save_config
from .security import DashboardGuard

WEB_PORT = os.getenv("WEB_PORT", "17860")
_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
_LOG_PATH = _DATA_DIR / "bot.log"
_CONFIG_DIR = Path("config")
_WORKSPACE_PROMPT_PATH = _CONFIG_DIR / "workspace_sys_prompt.txt"
_RUNTIME_PATH = _CONFIG_DIR / "runtime.yml"


# ── Runtime config helpers ─────────────────────────────────────────────────────
# runtime.yml is shared with the bot process. Both edit it through the bot's
# RuntimeConfig, which re-reads the file before every change.

_EMPTY_RUNTIME = {
    "allowed_channels": [], "allowed_users": [], "channel_metadata": {}, "user_metadata": {},
    **DEFAULT_SETTINGS,
}


def _runtime() -> RuntimeConfig:
    return RuntimeConfig(str(_RUNTIME_PATH))


def _runtime_error(error: Exception) -> str:
    return f'<span class="text-error text-xs">{_esc(error)}</span>'


def _change_runtime(change: Callable[[RuntimeConfig], object], render: Callable[[dict], str]) -> str:
    """Apply a change to runtime.yml and render the updated list (or the error)."""
    try:
        rc = _runtime()
        change(rc)
        return render(rc.snapshot())
    except RuntimeConfigError as e:
        return _runtime_error(e)


def _esc(value) -> str:
    """HTML-escape a value for the hand-built fragments below.

    Unlike Jinja templates these f-strings are not auto-escaped, and they show
    data from outside the dashboard: Discord server/channel/user names and
    whatever is in config.yaml or runtime.yml.
    """
    return escape("" if value is None else str(value))


def _render_channel_list(rt: dict) -> str:
    channels = rt.get("allowed_channels") or []
    meta     = rt.get("channel_metadata") or {}
    if not channels:
        return '<p class="text-sm text-base-content/40 py-3 text-center italic">No channels added yet</p>'
    rows = ""
    for ch in channels:
        m = meta.get(str(ch), {})
        label = _esc(f"{m.get('server', '')} / #{m.get('channel', '')}") if m else ""
        rows += f"""
<div class="flex justify-between items-center py-2.5 border-b border-base-200 last:border-0">
  <div>
    <p class="text-sm font-mono">{_esc(ch)}</p>
    {"" if not label else f'<p class="text-xs text-base-content/45">{label}</p>'}
  </div>
  <form hx-post="/api/runtime/channels/{_esc(ch)}/delete" hx-target="#channel-list" hx-swap="innerHTML">
    <button type="submit" class="btn btn-ghost btn-xs text-error">Remove</button>
  </form>
</div>"""
    return rows


def _render_user_list(rt: dict) -> str:
    users = rt.get("allowed_users") or []
    meta  = rt.get("user_metadata") or {}
    if not users:
        return '<p class="text-sm text-base-content/40 py-3 text-center italic">No users added yet</p>'
    rows = ""
    for uid in users:
        m = meta.get(str(uid), {})
        label = _esc(m.get("username") or m.get("name") or "")
        rows += f"""
<div class="flex justify-between items-center py-2.5 border-b border-base-200 last:border-0">
  <div>
    <p class="text-sm font-mono">{_esc(uid)}</p>
    {"" if not label else f'<p class="text-xs text-base-content/45">{label}</p>'}
  </div>
  <form hx-post="/api/runtime/users/{_esc(uid)}/delete" hx-target="#user-list" hx-swap="innerHTML">
    <button type="submit" class="btn btn-ghost btn-xs text-error">Remove</button>
  </form>
</div>"""
    return rows

try:
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as _f:
        VERSION = tomllib.load(_f)["project"]["version"]
except Exception:
    VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"\n🍡 Dango Web GUI started", flush=True)
    print(f"   ➜  http://localhost:{WEB_PORT}\n", flush=True)
    yield


app = FastAPI(title="Dango", lifespan=lifespan)
app.add_middleware(DashboardGuard)
templates = Jinja2Templates(directory="web/templates")
templates.env.filters["mask_db_url"] = lambda url: re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _ctx(active_page: str, **kwargs) -> dict:
    return {"active_page": active_page, "version": VERSION, **kwargs}


# ── Page routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/setup" if not is_setup_complete() else "/overview")


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if is_setup_complete():
        return RedirectResponse("/overview")
    return templates.TemplateResponse(request, "setup.html")


@app.post("/setup/complete", response_class=HTMLResponse)
async def setup_complete(
    discord_token: str = Form(...),
    fast_api_key: str = Form(...),
    fast_model: str = Form(...),
    chat_sys_prompt: str = Form(...),
):
    config = load_config()
    config.discord_token = discord_token
    config.fast_api_key = fast_api_key
    config.fast_model = fast_model
    config.chat_sys_prompt = chat_sys_prompt
    save_config(config)
    return RedirectResponse("/overview", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_redirect():
    return RedirectResponse("/overview")


@app.get("/overview", response_class=HTMLResponse)
async def overview_page(request: Request):
    if not is_setup_complete():
        return RedirectResponse("/setup")
    config = load_config()
    return templates.TemplateResponse(
        request, "overview.html",
        _ctx("overview", config=config.model_dump(), docker_available=docker_api.available()),
    )


@app.get("/prompt", response_class=HTMLResponse)
async def prompt_page(request: Request):
    if not is_setup_complete():
        return RedirectResponse("/setup")
    config = load_config()
    return templates.TemplateResponse(
        request, "prompt.html",
        _ctx("prompt", config=config.model_dump()),
    )


@app.get("/models", response_class=HTMLResponse)
async def models_page(request: Request):
    if not is_setup_complete():
        return RedirectResponse("/setup")
    config = load_config()
    return templates.TemplateResponse(
        request, "models.html",
        _ctx("models", config=config.model_dump()),
    )


@app.get("/discord", response_class=HTMLResponse)
async def discord_page(request: Request):
    if not is_setup_complete():
        return RedirectResponse("/setup")
    config = load_config()
    try:
        rt = _runtime().snapshot()
        channel_list, user_list = _render_channel_list(rt), _render_user_list(rt)
    except RuntimeConfigError as e:
        # Show the problem instead of an empty list that a save would then write.
        rt = _EMPTY_RUNTIME
        channel_list = user_list = f'<p class="text-sm text-error py-3">{_esc(e)}</p>'
    return templates.TemplateResponse(
        request, "discord.html",
        _ctx("discord", config=config.model_dump(), rt=rt,
             channel_list=channel_list,
             user_list=user_list),
    )


@app.get("/tools", response_class=HTMLResponse)
async def tools_page(request: Request):
    if not is_setup_complete():
        return RedirectResponse("/setup")
    config = load_config()
    workspace_prompt = ""
    if _WORKSPACE_PROMPT_PATH.exists():
        workspace_prompt = _WORKSPACE_PROMPT_PATH.read_text(encoding="utf-8")
    return templates.TemplateResponse(
        request, "tools.html",
        _ctx("tools", config=config.model_dump(), workspace_prompt=workspace_prompt),
    )


# ── Log endpoint ───────────────────────────────────────────────────────────────

@app.post("/api/logs/clear")
async def clear_logs():
    if _LOG_PATH.exists():
        _LOG_PATH.write_text("", encoding="utf-8")
    return Response(status_code=204)


@app.get("/api/logs", response_class=HTMLResponse)
async def get_logs():
    if not _LOG_PATH.exists():
        return '<div class="font-mono text-xs text-base-content/40 italic p-2">No logs yet — waiting for bot to start...</div>'
    try:
        text = _LOG_PATH.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()[-150:]
    except Exception:
        return '<div class="font-mono text-xs text-error p-2">Failed to read log file</div>'
    if not lines:
        return '<div class="font-mono text-xs text-base-content/40 italic p-2">Log is empty</div>'

    parts = []
    for line in lines:
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if any(x in line for x in ("ERROR", "❌", "Exception", "Traceback", "error")):
            css = "text-error"
        elif any(x in line for x in ("WARNING", "⚠", "warn")):
            css = "text-warning"
        elif any(x in line for x in ("✅", "🚀", "connected", "Synced")):
            css = "text-success"
        elif any(x in line for x in ("🍡", "📝", "📂", "📦", "🔤", "💬", "🤖", "🔑", "🔧", "🌡")):
            css = "text-info"
        else:
            css = "text-base-content/65"
        parts.append(f'<div class="leading-[1.6] {css}">{esc}</div>')

    return "\n".join(parts)


# ── Bot control endpoints ──────────────────────────────────────────────────────

def _status_pill(color: str, label: str, pulse: bool = False) -> str:
    dot = f'<span class="status-dot{"  animate-pulse" if pulse else ""}"></span>'
    return f'<span class="status-pill s-{color}">{dot}{_esc(label)}</span>'


_STATE_PILL = {
    "running":    _status_pill("green",  "running",    pulse=True),
    "restarting": _status_pill("cream",  "restarting", pulse=True),
    "created":    _status_pill("cream",  "created"),
    "paused":     _status_pill("cream",  "paused"),
    "exited":     _status_pill("pink",   "exited"),
    "dead":       _status_pill("bamboo", "dead"),
}


@app.get("/api/bot/status", response_class=HTMLResponse)
async def bot_status():
    if not docker_api.available():
        return _status_pill("bamboo", "No Docker")
    ct = await docker_api.find_service("bot")
    if not ct:
        return _status_pill("bamboo", "not found")
    state: str = ct.get("State", "unknown")
    return _STATE_PILL.get(state, _status_pill("bamboo", state))


_OK   = '<span class="badge badge-success badge-sm">✓ OK</span>'
_FAIL = '<span class="badge badge-error badge-sm">✗ Failed</span>'
_NOT_FOUND = '<span class="badge badge-warning badge-sm">Not found</span>'


@app.post("/api/bot/start", response_class=HTMLResponse)
async def bot_start():
    ct = await docker_api.find_service("bot")
    if not ct:
        return _NOT_FOUND
    ok = await docker_api.action(ct["Id"], "start")
    return _OK if ok else _FAIL


@app.post("/api/bot/stop", response_class=HTMLResponse)
async def bot_stop():
    ct = await docker_api.find_service("bot")
    if not ct:
        return _NOT_FOUND
    ok = await docker_api.action(ct["Id"], "stop")
    return _OK if ok else _FAIL


@app.post("/api/bot/restart", response_class=HTMLResponse)
async def bot_restart():
    ct = await docker_api.find_service("bot")
    if not ct:
        return _NOT_FOUND
    ok = await docker_api.action(ct["Id"], "restart")
    return _OK if ok else _FAIL


@app.post("/api/shutdown", response_class=HTMLResponse)
async def shutdown_all():
    """Stop bot then web container via Docker API (proper shutdown, no auto-restart)."""
    async def _shutdown():
        await asyncio.sleep(0.3)
        bot_ct = await docker_api.find_service("bot")
        if bot_ct:
            await docker_api.action(bot_ct["Id"], "stop")
        await asyncio.sleep(3)
        web_ct = await docker_api.find_service("web")
        if web_ct:
            await docker_api.action(web_ct["Id"], "stop")
        else:
            # Fallback: not running inside Docker, just exit the process
            os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_shutdown())
    return '<span class="text-warning text-xs">Shutting down all services…</span>'


# ── Validation endpoints ───────────────────────────────────────────────────────

@app.post("/api/validate/discord", response_class=HTMLResponse)
async def validate_discord(token: str = Form(...)):
    if not token.strip():
        return '<span class="text-error text-sm">Please enter a token</span>'
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=8,
            )
            if r.status_code == 200:
                name = r.json().get("username", "Bot")
                return f'<span class="badge badge-success gap-1">✓ {_esc(name)}</span>'
            return '<span class="badge badge-error gap-1">✗ Invalid token</span>'
        except httpx.RequestError:
            return '<span class="badge badge-error gap-1">✗ Connection failed</span>'


@app.post("/api/validate/google", response_class=HTMLResponse)
async def validate_google(key: str = Form(...)):
    if not key.strip():
        return '<span class="text-error text-sm">Please enter an API key</span>'
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                timeout=8,
            )
            if r.status_code == 200:
                return '<span class="badge badge-success gap-1">✓ Valid</span>'
            return '<span class="badge badge-error gap-1">✗ Invalid key</span>'
        except httpx.RequestError:
            return '<span class="badge badge-error gap-1">✗ Connection failed</span>'


# ── Save status snippets ───────────────────────────────────────────────────────

_SAVED = '<span class="badge badge-success badge-sm">✓ Saved</span>'
_RESTART = ' <span class="badge badge-warning badge-sm">Restart bot to apply</span>'
_SAVED_R = _SAVED + _RESTART
# runtime.yml is re-read by the bot on the next message; only the activity
# (Discord presence) is applied at startup.
_SAVED_RUNTIME = _SAVED + ' <span class="badge badge-warning badge-sm">Activity applies after restart</span>'


# ── Config endpoints ───────────────────────────────────────────────────────────

@app.post("/api/config/prompt", response_class=HTMLResponse)
async def save_prompt(chat_sys_prompt: str = Form(...)):
    config = load_config()
    config.chat_sys_prompt = chat_sys_prompt
    save_config(config)
    return _SAVED


@app.post("/api/config/discord", response_class=HTMLResponse)
async def save_discord(discord_token: str = Form("")):
    if discord_token.strip():
        config = load_config()
        config.discord_token = discord_token.strip()
        save_config(config)
    return _SAVED_R


@app.post("/api/config/models/fast", response_class=HTMLResponse)
async def save_fast_model(
    fast_model: str = Form(...),
    fast_api_key: str = Form(""),
    fast_base_url: str = Form(""),
):
    config = load_config()
    config.fast_model = fast_model.strip()
    if fast_api_key.strip():
        config.fast_api_key = fast_api_key.strip()
    config.fast_base_url = fast_base_url.strip()
    save_config(config)
    return _SAVED_R


@app.post("/api/config/models/deep", response_class=HTMLResponse)
async def save_deep_model(
    deep_model: str = Form(""),
    deep_api_key: str = Form(""),
    deep_base_url: str = Form(""),
):
    config = load_config()
    config.deep_model = deep_model.strip()
    if deep_api_key.strip():
        config.deep_api_key = deep_api_key.strip()
    config.deep_base_url = deep_base_url.strip()
    save_config(config)
    return _SAVED_R


@app.post("/api/config/features", response_class=HTMLResponse)
async def save_features(
    auto_route: str = Form("off"),
    fallback_on_error: str = Form("off"),
    enable_contextual_system_prompt: str = Form("off"),
    enable_message_batching: str = Form("off"),
    message_batch_window: str = Form(""),
    message_batch_max_wait: str = Form(""),
    enable_duckduckgo: str = Form("off"),
    enable_brave_search: str = Form("off"),
    brave_api_key: str = Form(""),
    enable_website_tools: str = Form("off"),
):
    config = load_config()
    config.auto_route = auto_route == "on"
    config.fallback_on_error = fallback_on_error == "on"
    config.enable_contextual_system_prompt = enable_contextual_system_prompt == "on"
    config.enable_message_batching = enable_message_batching == "on"
    if message_batch_window.strip():
        config.message_batch_window = float(message_batch_window)
    if message_batch_max_wait.strip():
        config.message_batch_max_wait = float(message_batch_max_wait)
    config.enable_duckduckgo = enable_duckduckgo == "on"
    config.enable_brave_search = enable_brave_search == "on"
    if brave_api_key.strip():
        config.brave_api_key = brave_api_key.strip()
    config.enable_website_tools = enable_website_tools == "on"
    save_config(config)
    return _SAVED_R


@app.post("/api/config/google", response_class=HTMLResponse)
async def save_google_settings(
    gemini_search: str = Form("off"),
    gemini_url_context: str = Form("off"),
    gemini_grounding_threshold: str = Form(""),
    gemini_thinking_budget: str = Form(""),
    gemini_thinking_level: str = Form(""),
    fast_search: str = Form(""),
    fast_url_context: str = Form(""),
    fast_grounding_threshold: str = Form(""),
    fast_thinking_budget: str = Form(""),
    fast_thinking_level: str = Form(""),
    deep_search: str = Form(""),
    deep_url_context: str = Form(""),
    deep_grounding_threshold: str = Form(""),
    deep_thinking_budget: str = Form(""),
    deep_thinking_level: str = Form(""),
):
    config = load_config()
    config.gemini_search = gemini_search == "on"
    config.gemini_url_context = gemini_url_context == "on"
    config.gemini_grounding_threshold = gemini_grounding_threshold
    config.gemini_thinking_budget = gemini_thinking_budget
    config.gemini_thinking_level = gemini_thinking_level
    config.fast_search = fast_search
    config.fast_url_context = fast_url_context
    config.fast_grounding_threshold = fast_grounding_threshold
    config.fast_thinking_budget = fast_thinking_budget
    config.fast_thinking_level = fast_thinking_level
    config.deep_search = deep_search
    config.deep_url_context = deep_url_context
    config.deep_grounding_threshold = deep_grounding_threshold
    config.deep_thinking_budget = deep_thinking_budget
    config.deep_thinking_level = deep_thinking_level
    save_config(config)
    return _SAVED_R


@app.post("/api/config/advanced", response_class=HTMLResponse)
async def save_advanced(
    context_token_budget: str = Form("8192"),
    fast_context_token_budget: str = Form(""),
    deep_context_token_budget: str = Form(""),
):
    config = load_config()
    config.context_token_budget = context_token_budget
    config.fast_context_token_budget = fast_context_token_budget
    config.deep_context_token_budget = deep_context_token_budget
    save_config(config)
    return _SAVED_R


@app.post("/api/config/workspace", response_class=HTMLResponse)
async def save_workspace(
    enable_workspace: str = Form("off"),
    workspace_root: str = Form("workspace"),
):
    config = load_config()
    config.enable_workspace = enable_workspace == "on"
    config.workspace_root = workspace_root.strip() or "workspace"
    save_config(config)
    return _SAVED_R


@app.post("/api/config/skills", response_class=HTMLResponse)
async def save_skills(
    enable_skills: str = Form("off"),
    skills_root: str = Form("skills"),
):
    config = load_config()
    config.enable_skills = enable_skills == "on"
    config.skills_root = skills_root.strip() or "skills"
    save_config(config)
    return _SAVED_R


@app.post("/api/runtime/settings", response_class=HTMLResponse)
async def save_runtime_settings(
    timezone: str = Form("UTC"),
    discord_activity: str = Form(""),
    history_limit: str = Form("12"),
):
    try:
        limit = int(history_limit)
    except ValueError:
        return '<span class="text-error text-xs">History limit must be a whole number.</span>'
    try:
        _runtime().update_settings(
            timezone=timezone.strip() or "UTC",
            discord_activity=discord_activity.strip(),
            history_limit=limit,
        )
    except (ValueError, RuntimeConfigError) as e:
        return _runtime_error(e)
    return _SAVED_RUNTIME


@app.post("/api/runtime/channels/add", response_class=HTMLResponse)
async def add_runtime_channel(channel_id: str = Form(...)):
    try:
        ch = int(channel_id.strip())
    except ValueError:
        return '<span class="text-error text-xs">Invalid channel ID</span>'
    return _change_runtime(lambda rc: rc.add_channel(ch), _render_channel_list)


@app.post("/api/runtime/channels/{channel_id}/delete", response_class=HTMLResponse)
async def delete_runtime_channel(channel_id: int):
    return _change_runtime(lambda rc: rc.remove_channel(channel_id), _render_channel_list)


@app.post("/api/runtime/users/add", response_class=HTMLResponse)
async def add_runtime_user(user_id: str = Form(...)):
    try:
        uid = int(user_id.strip())
    except ValueError:
        return '<span class="text-error text-xs">Invalid user ID</span>'
    return _change_runtime(lambda rc: rc.add_user(uid), _render_user_list)


@app.post("/api/runtime/users/{user_id}/delete", response_class=HTMLResponse)
async def delete_runtime_user(user_id: int):
    return _change_runtime(lambda rc: rc.remove_user(user_id), _render_user_list)


@app.post("/api/workspace-prompt", response_class=HTMLResponse)
async def save_workspace_prompt(workspace_sys_prompt: str = Form(default="")):
    content = workspace_sys_prompt.strip()
    if not content:
        # Empty = let the bot auto-generate it on next startup
        _WORKSPACE_PROMPT_PATH.unlink(missing_ok=True)
        return _SAVED + ' <span class="badge badge-info badge-sm">Will auto-generate on next start</span>'
    _WORKSPACE_PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WORKSPACE_PROMPT_PATH.write_text(content, encoding="utf-8")
    return _SAVED_R


# ── Custom tool helpers ────────────────────────────────────────────────────────

def _render_api_list(apis: list) -> str:
    if not apis:
        return '<p class="text-sm text-base-content/40 py-3 text-center">No APIs added yet</p>'
    rows = ""
    for i, a in enumerate(apis):
        desc = _esc(a.get("description", ""))
        rows += f"""
<div class="flex justify-between items-center py-3 border-b border-base-200 last:border-0">
  <div>
    <p class="text-sm font-medium">{_esc(a.get("name", ""))}</p>
    <p class="text-xs text-base-content/45 font-mono">{_esc(a.get("base_url", ""))}</p>
    {"" if not desc else f'<p class="text-xs text-base-content/55 mt-0.5">{desc}</p>'}
  </div>
  <form hx-post="/api/config/tools/api/{i}/delete" hx-target="#api-list" hx-swap="innerHTML">
    <button type="submit" class="btn btn-ghost btn-xs text-error">Delete</button>
  </form>
</div>"""
    return rows


def _render_db_list(dbs: list) -> str:
    if not dbs:
        return '<p class="text-sm text-base-content/40 py-3 text-center">No databases added yet</p>'
    rows = ""
    for i, d in enumerate(dbs):
        display_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", d.get("db_url", ""))
        desc = _esc(d.get("description", ""))
        rows += f"""
<div class="flex justify-between items-center py-3 border-b border-base-200 last:border-0">
  <div>
    <p class="text-sm font-medium">{_esc(d.get("name", ""))}</p>
    <p class="text-xs text-base-content/45 font-mono">{_esc(display_url)}</p>
    {"" if not desc else f'<p class="text-xs text-base-content/55 mt-0.5">{desc}</p>'}
  </div>
  <form hx-post="/api/config/tools/db/{i}/delete" hx-target="#db-list" hx-swap="innerHTML">
    <button type="submit" class="btn btn-ghost btn-xs text-error">Delete</button>
  </form>
</div>"""
    return rows


@app.post("/api/config/tools/apis/enable", response_class=HTMLResponse)
async def save_apis_enable(enable_custom_apis: str = Form("off")):
    config = load_config()
    config.enable_custom_apis = enable_custom_apis == "on"
    save_config(config)
    return _SAVED_R


@app.post("/api/config/tools/api", response_class=HTMLResponse)
async def add_custom_api(
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    description: str = Form(""),
):
    config = load_config()
    config.custom_apis = list(config.custom_apis)
    config.custom_apis.append({
        "name": name.strip(),
        "base_url": base_url.strip(),
        "api_key": api_key.strip(),
        "description": description.strip(),
    })
    save_config(config)
    return _render_api_list(config.custom_apis)


@app.post("/api/config/tools/api/{index}/delete", response_class=HTMLResponse)
async def delete_custom_api(index: int):
    config = load_config()
    apis = list(config.custom_apis)
    if 0 <= index < len(apis):
        apis.pop(index)
    config.custom_apis = apis
    save_config(config)
    return _render_api_list(config.custom_apis)


@app.post("/api/config/tools/dbs/enable", response_class=HTMLResponse)
async def save_dbs_enable(enable_sql_databases: str = Form("off")):
    config = load_config()
    config.enable_sql_databases = enable_sql_databases == "on"
    save_config(config)
    return _SAVED_R


@app.post("/api/config/tools/db", response_class=HTMLResponse)
async def add_sql_database(
    name: str = Form(...),
    db_url: str = Form(...),
    description: str = Form(""),
):
    config = load_config()
    config.sql_databases = list(config.sql_databases)
    config.sql_databases.append({
        "name": name.strip(),
        "db_url": db_url.strip(),
        "description": description.strip(),
    })
    save_config(config)
    return _render_db_list(config.sql_databases)


@app.post("/api/config/tools/db/{index}/delete", response_class=HTMLResponse)
async def delete_sql_database(index: int):
    config = load_config()
    dbs = list(config.sql_databases)
    if 0 <= index < len(dbs):
        dbs.pop(index)
    config.sql_databases = dbs
    save_config(config)
    return _render_db_list(config.sql_databases)
