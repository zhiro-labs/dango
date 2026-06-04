"""
Call an LLM via an Agno Agent with dynamic instructions and Discord history.
Supports multiple providers: Google (Gemini/Gemma) uses a dedicated subclass;
all other providers are resolved via Agno's model-as-string format.

Agent and model are created once at module level; per-request context is passed
via session_state.
"""

import asyncio
import os

import aiohttp
from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.media import Image
from agno.models.google import Gemini
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.workflow import StepInput, StepOutput

from ..utils.build_instructions import build_instructions
from ..utils.complexity_router import URL as _URL_RE, classify
from ..utils.config_utils import env_bool, env_onoff_to_bool
from ..utils.discord_helpers import format_sysinfo, resolve_mentions
from ..utils.runtime_config import runtime_config


# ── Provider → API key env var mapping ────────────────────────────────────────
# Complete list sourced from Agno model source code.
# google is included so GOOGLE_API_KEY is set for model-as-string and other callers.
# Complex cloud providers (aws-bedrock, azure-*, vertexai-*, ibm) need their own
# multi-var auth setup and are intentionally omitted.
_PROVIDER_KEY_MAP: dict[str, str] = {
    "google":           "GOOGLE_API_KEY",
    "aimlapi":          "AIMLAPI_API_KEY",
    "anthropic":        "ANTHROPIC_API_KEY",
    "cerebras":         "CEREBRAS_API_KEY",
    "cerebras-openai":  "CEREBRAS_API_KEY",
    "cohere":           "CO_API_KEY",
    "cometapi":         "COMETAPI_KEY",
    "dashscope":        "DASHSCOPE_API_KEY",
    "deepinfra":        "DEEPINFRA_API_KEY",
    "deepseek":         "DEEPSEEK_API_KEY",
    "fireworks":        "FIREWORKS_API_KEY",
    "groq":             "GROQ_API_KEY",
    "huggingface":      "HF_TOKEN",
    "internlm":         "INTERNLM_API_KEY",
    "langdb":           "LANGDB_API_KEY",
    "litellm":          "LITELLM_API_KEY",
    "litellm-openai":   "LITELLM_API_KEY",
    "meta":             "LLAMA_API_KEY",
    "llama-openai":     "LLAMA_API_KEY",
    "mistral":          "MISTRAL_API_KEY",
    "moonshot":         "MOONSHOT_API_KEY",
    "n1n":              "N1N_API_KEY",
    "nebius":           "NEBIUS_API_KEY",
    "neosantara":       "NEOSANTARA_API_KEY",
    "nvidia":           "NVIDIA_API_KEY",
    "ollama":           "OLLAMA_API_KEY",
    "openai":           "OPENAI_API_KEY",
    "openai-chat":      "OPENAI_API_KEY",
    "openai-responses": "OPENAI_API_KEY",
    "openrouter":       "OPENROUTER_API_KEY",
    "perplexity":       "PERPLEXITY_API_KEY",
    "portkey":          "PORTKEY_API_KEY",
    "requesty":         "REQUESTY_API_KEY",
    "sambanova":        "SAMBANOVA_API_KEY",
    "siliconflow":      "SILICONFLOW_API_KEY",
    "together":         "TOGETHER_API_KEY",
    "vllm":             "VLLM_API_KEY",
    # llama-cpp and lmstudio use OpenAILike with api_key="not-provided" default,
    # no standard env var — FAST/DEEP_API_KEY is passed directly if set.
    "xai":              "XAI_API_KEY",
}


def _parse_provider(model_str: str) -> str:
    """Extract provider prefix from 'provider:model_id'."""
    return model_str.split(":", 1)[0] if ":" in model_str else "google"


def _inject_provider_key(model_str: str, api_key: str | None) -> None:
    """Map FAST/DEEP_API_KEY to the env var the provider's SDK reads.

    Uses setdefault so a pre-existing env var (e.g. set by the user directly)
    is never overwritten.
    """
    if not api_key or not model_str:
        return
    provider = _parse_provider(model_str)
    env_var = _PROVIDER_KEY_MAP.get(provider)
    if env_var:
        os.environ.setdefault(env_var, api_key)


# ── Model identity ─────────────────────────────────────────────────────────────
FAST_MODEL = os.getenv("FAST_MODEL", "google:gemma-4-26b-a4b-it")
FAST_API_KEY = os.getenv("FAST_API_KEY")
FAST_BASE_URL = os.getenv("FAST_BASE_URL")  # optional custom endpoint for local/proxied models

DEEP_MODEL = os.getenv("DEEP_MODEL")  # optional; routing is disabled when unset
DEEP_API_KEY = os.getenv("DEEP_API_KEY") or FAST_API_KEY
DEEP_BASE_URL = os.getenv("DEEP_BASE_URL")

# Inject provider keys before any model class is instantiated.
_inject_provider_key(FAST_MODEL, FAST_API_KEY)
if DEEP_MODEL:
    _inject_provider_key(DEEP_MODEL, DEEP_API_KEY)

# on/off — auto-route between fast and deep model based on message complexity.
# Has no effect when DEEP_MODEL is not set.
AUTO_ROUTE = env_onoff_to_bool(os.getenv("AUTO_ROUTE"))

# on/off — fall back to DEEP_MODEL when FAST_MODEL returns an error (e.g. 503).
# Has no effect when DEEP_MODEL is not set.
FALLBACK_ON_ERROR = env_onoff_to_bool(os.getenv("FALLBACK_ON_ERROR"))

if FALLBACK_ON_ERROR and DEEP_MODEL and _parse_provider(FAST_MODEL) == _parse_provider(DEEP_MODEL):
    print(
        f"⚠️  [config] FAST_MODEL and DEEP_MODEL share provider "
        f"'{_parse_provider(FAST_MODEL)}' — FALLBACK_ON_ERROR won't protect against provider-wide outages."
    )

ENABLE_CONTEXTUAL_SYSTEM_PROMPT = env_onoff_to_bool(
    os.getenv("ENABLE_CONTEXTUAL_SYSTEM_PROMPT")
)

# ── Workspace ─────────────────────────────────────────────────────────────────
ENABLE_WORKSPACE = env_onoff_to_bool(os.getenv("ENABLE_WORKSPACE"))
# Resolve to absolute path at startup so the scope is always unambiguous.
WORKSPACE_ROOT = os.path.abspath(os.getenv("WORKSPACE_ROOT", "workspace"))
WORKSPACE_ALLOWED: list[str] = ["read", "list", "search"]

# ── Web / search tools ────────────────────────────────────────────────────────
ENABLE_DUCKDUCKGO = env_onoff_to_bool(os.getenv("ENABLE_DUCKDUCKGO"))
ENABLE_WEBSITE_TOOLS = env_onoff_to_bool(os.getenv("ENABLE_WEBSITE_TOOLS"))

# ── Custom tools ──────────────────────────────────────────────────────────────
ENABLE_CUSTOM_APIS = env_onoff_to_bool(os.getenv("ENABLE_CUSTOM_APIS"), default=False)
ENABLE_SQL_DATABASES = env_onoff_to_bool(os.getenv("ENABLE_SQL_DATABASES"), default=False)
import json as _json
import re as _re
_CUSTOM_APIS: list[dict] = _json.loads(os.getenv("CUSTOM_APIS_JSON", "[]"))
_SQL_DATABASES: list[dict] = _json.loads(os.getenv("SQL_DATABASES_JSON", "[]"))


def _sanitize_name(raw: str, fallback: str) -> str:
    return _re.sub(r"\W+", "_", raw, flags=_re.UNICODE).strip("_") or fallback


def _check_unique_names(configs: list[dict], kind: str, fallback: str) -> None:
    seen: dict[str, int] = {}
    for i, cfg in enumerate(configs):
        safe = _sanitize_name(cfg.get("name", ""), fallback)
        if safe in seen:
            raise ValueError(
                f"{kind} config error: entries at index {seen[safe]} and {i} both resolve to "
                f"the same sanitized name '{safe}'. Give them distinct 'name' values."
            )
        seen[safe] = i


_check_unique_names(_CUSTOM_APIS, "CUSTOM_APIS_JSON", "api")
_check_unique_names(_SQL_DATABASES, "SQL_DATABASES_JSON", "db")


def _dynamic_instructions(session_state: dict) -> str:
    """Called by Agno on every arun(); reads per-request context from session_state."""
    return build_instructions(
        base_prompt=session_state.get("chat_sys_prompt", ""),
        author_name=session_state.get("author_name", "User"),
        unique_users=set(session_state.get("unique_users", [])),
        enable_contextual=ENABLE_CONTEXTUAL_SYSTEM_PROMPT,
        history_limit=session_state.get("history_limit"),
    )


# ── Gemini subclass ───────────────────────────────────────────────────────────
class _DangoGemini(Gemini):
    """Gemini with corrected error messages.

    Agno bug: ainvoke overwrites the useful str(e) error message with
    e.response.text (an aiohttp bound method, not the actual response body).
    We recover the original error string from __cause__ before it propagates.
    """

    async def ainvoke(self, messages, assistant_message, **kwargs):
        try:
            return await super().ainvoke(messages, assistant_message, **kwargs)
        except ModelProviderError as e:
            cause = e.__cause__
            if cause is not None and str(e).startswith("<"):
                raise ModelProviderError(
                    message=str(cause),
                    status_code=e.status_code,
                    model_name=e.model_name,
                    model_id=e.model_id,
                ) from cause
            raise


# ── Model factories ───────────────────────────────────────────────────────────
def _make_gemini(model_id: str, api_key: str | None, prefix: str) -> _DangoGemini:
    """Create a _DangoGemini reading params from {prefix}_* with GEMINI_* as fallback."""
    def f(key: str) -> float | None:
        v = os.getenv(f"{prefix}_{key}") or os.getenv(f"GEMINI_{key}")
        return float(v) if v else None

    def i(key: str) -> int | None:
        v = os.getenv(f"{prefix}_{key}") or os.getenv(f"GEMINI_{key}")
        return int(v) if v else None

    def b(key: str, default: str = "false") -> bool:
        v = os.getenv(f"{prefix}_{key}") or os.getenv(f"GEMINI_{key}", default)
        return env_bool(v)

    retries = i("RETRIES")
    if retries is None:
        retries = 2  # default: retry 503/5xx twice before giving up

    return _DangoGemini(
        id=model_id,
        api_key=api_key,
        search=b("SEARCH", "true"),
        grounding_dynamic_threshold=f("GROUNDING_THRESHOLD"),
        url_context=False if model_id.startswith("gemma-") else b("URL_CONTEXT", "false"),
        thinking_budget=i("THINKING_BUDGET"),
        thinking_level=os.getenv(f"{prefix}_THINKING_LEVEL") or os.getenv("GEMINI_THINKING_LEVEL") or None,
        retries=retries,
        delay_between_retries=i("RETRY_DELAY") or 1,
        exponential_backoff=True,
    )


def _make_model(model_str: str, api_key: str | None, prefix: str, base_url: str | None = None) -> _DangoGemini | str:
    """Return a model instance or string for Agno's model-as-string resolution.

    - google: → _DangoGemini (with Gemini-specific params)
    - others without base_url → model string (Agno resolves at runtime)
    - others with base_url → Agno instantiates the class, then base_url/host is patched
    """
    provider = _parse_provider(model_str)
    if provider == "google":
        model_id = model_str.split(":", 1)[1] if ":" in model_str else model_str
        return _make_gemini(model_id, api_key, prefix)

    if base_url:
        from agno.models.utils import get_model as _agno_get_model
        instance = _agno_get_model(model_str)
        if hasattr(instance, "host"):           # Ollama uses 'host'
            instance.host = base_url
        elif hasattr(instance, "base_url"):     # most OpenAI-like providers
            instance.base_url = base_url
        else:
            # Provider has no native base_url/host param — force-set as attribute.
            # The setting is NOT ignored; whether the provider honours it depends on
            # its internal client construction. A warning is printed to aid debugging.
            print(
                f"⚠️  [{prefix}_BASE_URL] provider '{provider}' has no native base_url/host param — "
                f"force-setting attribute '{base_url}'. Behaviour depends on provider implementation."
            )
            instance.base_url = base_url
        return instance

    return model_str


def _make_api_tool(name: str, base_url: str, api_key: str, description: str = ""):
    """Build a uniquely-named HTTP tool for one custom API config."""
    import asyncio
    import requests as _requests
    from agno.tools import tool

    safe = _sanitize_name(name, "api")
    tool_name = f"call_{safe}_api"
    base = base_url.rstrip("/")

    async def _fn(endpoint: str = "", method: str = "GET",
                  params: dict | None = None, json_body: dict | None = None,
                  extra_headers: dict | None = None) -> str:
        url = f"{base}/{endpoint.lstrip('/')}" if endpoint else base
        headers: dict = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if extra_headers:
            headers.update(extra_headers)
        r = await asyncio.to_thread(
            _requests.request, method, url,
            params=params, json=json_body, headers=headers, timeout=30,
        )
        return r.text

    base_desc = (
        f"Make an HTTP request to the {name} API (base URL: {base_url}). "
        "Auth is pre-configured. Leave endpoint empty to hit the base URL directly."
    )
    desc = f"{description} {base_desc}" if description else base_desc
    return tool(name=tool_name, description=desc)(_fn)


def _make_db_provider(name: str, db_url: str, description: str = "") -> list:
    """Build a read-only DatabaseContextProvider for one SQL database config."""
    try:
        from sqlalchemy import create_engine
        from agno.context.database import DatabaseContextProvider, DEFAULT_READ_INSTRUCTIONS
    except ImportError:
        print(f"⚠️  sqlalchemy not installed — SQL provider '{name}' skipped")
        return []

    safe = _sanitize_name(name, "db")

    try:
        engine = create_engine(db_url)
    except Exception as e:
        print(f"⚠️  Cannot create SQL engine for '{name}': {e}")
        return []

    read_instructions = (
        f"This database is: {description}\n\n{DEFAULT_READ_INSTRUCTIONS}"
        if description
        else None
    )

    provider = DatabaseContextProvider(
        id=safe,
        name=name,
        sql_engine=engine,
        readonly_engine=engine,
        read_instructions=read_instructions,
        write=False,
        model=_fast_model,
    )
    return provider.get_tools()


def _make_agent(model: _DangoGemini | object | str, extra_tools: list | None = None) -> Agent:
    tools = []
    if ENABLE_WORKSPACE:
        from agno.tools.workspace import Workspace
        tools.append(Workspace(WORKSPACE_ROOT, allowed=WORKSPACE_ALLOWED))
    if ENABLE_DUCKDUCKGO:
        from agno.tools.duckduckgo import DuckDuckGoTools
        tools.append(DuckDuckGoTools())
    if ENABLE_WEBSITE_TOOLS:
        from agno.tools.website import WebsiteTools
        tools.append(WebsiteTools())
    if ENABLE_CUSTOM_APIS:
        for api_cfg in _CUSTOM_APIS:
            tools.append(_make_api_tool(
                api_cfg.get("name", "api"),
                api_cfg.get("base_url", ""),
                api_cfg.get("api_key", ""),
                api_cfg.get("description", ""),
            ))
    if ENABLE_SQL_DATABASES:
        for db_cfg in _SQL_DATABASES:
            tools.extend(_make_db_provider(
                db_cfg.get("name", "db"),
                db_cfg.get("db_url", ""),
                db_cfg.get("description", ""),
            ))
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        model=model,
        tools=tools or None,
        instructions=_dynamic_instructions,
        # Time is injected inside _dynamic_instructions (reads runtime_config.timezone each call),
        # so add_datetime_to_context is intentionally off.
        add_history_to_context=False,
        markdown=False,
    )


def make_extra_agents(extra_tools: list) -> tuple["Agent", "Agent | None"]:
    """Create a (fast_agent, deep_agent) pair that includes additional tools.

    Call this once during bot setup (e.g. inside a Cog's __init__) and pass the
    returned tuple via message_data["_agents"] so call_discord_agent picks them up.
    """
    fast = _make_agent(_fast_model, extra_tools)
    deep = _make_agent(_deep_model, extra_tools) if _deep_model else None
    return fast, deep


def _context_budget(prefix: str) -> int:
    v = os.getenv(f"{prefix}_CONTEXT_TOKEN_BUDGET") or os.getenv("CONTEXT_TOKEN_BUDGET")
    return int(v) if v else 0


# ── Module-level singletons ───────────────────────────────────────────────────
_fast_model = _make_model(FAST_MODEL, FAST_API_KEY, "FAST", FAST_BASE_URL)
_fast_gemini: _DangoGemini | None = _fast_model if isinstance(_fast_model, _DangoGemini) else None
fast_agent = _make_agent(_fast_model)

_deep_model = _make_model(DEEP_MODEL, DEEP_API_KEY, "DEEP", DEEP_BASE_URL) if DEEP_MODEL else None
_deep_gemini: _DangoGemini | None = _deep_model if isinstance(_deep_model, _DangoGemini) else None
deep_agent: Agent | None = _make_agent(_deep_model) if _deep_model else None

FAST_CONTEXT_TOKEN_BUDGET = _context_budget("FAST")
DEEP_CONTEXT_TOKEN_BUDGET = _context_budget("DEEP")

# ── Agent runner with non-Gemini retry ────────────────────────────────────────
_NON_GEMINI_RETRIES = 2  # mirrors _DangoGemini default


async def _arun_agent(agent: Agent, messages: list, session_state: dict):
    """Run agent.arun with retry for non-Gemini providers.

    _DangoGemini already retries at model level (retries=2, exponential_backoff).
    All other providers have no built-in retry in Agno, so we add one here.
    """
    is_gemini = isinstance(getattr(agent, "model", None), _DangoGemini)
    attempts = 1 if is_gemini else _NON_GEMINI_RETRIES + 1
    response = None

    for attempt in range(attempts):
        response = await agent.arun(input=messages, session_state=session_state)
        if response.status != RunStatus.error or attempt == attempts - 1:
            break
        delay = 2 ** attempt  # 1 s, 2 s
        print(f"⚡ [arun] non-Gemini error on attempt {attempt + 1}/{attempts - 1}, retrying in {delay}s")
        await asyncio.sleep(delay)

    return response


def _trim_to_token_budget(messages: list[Message], budget: int) -> list[Message]:
    """Trim oldest messages until estimated token count fits within budget.

    Uses agno's tiktoken-based counter — local, no API calls, works with all providers.
    The model_id is passed to tiktoken for encoding selection; unknown models fall back
    to o200k_base which is a reasonable general-purpose estimate.
    Falls back gracefully (no trimming) if token counting itself fails.
    """
    if budget == 0 or len(messages) <= 1:
        return messages

    from agno.utils.tokens import count_tokens as _agno_count_tokens

    # Strip provider prefix so tiktoken gets a plain model id (e.g. "gpt-4o", "gemma-4-31b-it")
    _model_id = FAST_MODEL.split(":", 1)[1] if ":" in FAST_MODEL else FAST_MODEL

    def _count(msgs: list[Message]) -> int:
        return _agno_count_tokens(msgs, model_id=_model_id)

    try:
        count = _count(messages)
    except Exception:
        return messages  # counting unavailable — don't drop anything

    if count <= budget:
        return messages

    # Proportional drop: remove roughly (1 - budget/count) fraction from the front,
    # but always keep the last message (current user turn).
    drop = max(1, int(len(messages) * (1 - budget / count)))
    messages = messages[drop:]

    # Single follow-up loop in case proportional estimate was off
    try:
        while len(messages) > 1 and _count(messages) > budget:
            messages.pop(0)
    except Exception:
        pass

    return messages


def _select_agent(
    user_content: str,
    history: list[str] | None = None,
    fast: Agent | None = None,
    deep: Agent | None = None,
) -> tuple[Agent, str, int]:
    """Return (agent, model_name, context_budget) based on AUTO_ROUTE and message complexity."""
    _fast = fast if fast is not None else fast_agent
    _deep = deep if deep is not None else deep_agent
    if AUTO_ROUTE and _deep and DEEP_MODEL:
        r = classify(user_content, history=history)
        print(
            f"🔀 [route] {'deep' if r.decision == 'complex' else 'fast'}  "
            f"← band={r.band} score={r.score} "
            f"{('rules=' + ','.join(r.hard_rules) + ' ') if r.hard_rules else ''}"
            f"content: {user_content!r}"
        )
        if r.decision == "complex":
            return _deep, DEEP_MODEL, DEEP_CONTEXT_TOKEN_BUDGET
    else:
        print(f"🔀 [route] fast  ← auto_route={AUTO_ROUTE} deep_model={DEEP_MODEL!r}")
    return _fast, FAST_MODEL, FAST_CONTEXT_TOKEN_BUDGET


async def _download_current_images(attachments: list) -> list[Image]:
    """Download image attachments from the current user message."""
    images: list[Image] = []
    async with aiohttp.ClientSession() as session:
        for att in attachments:
            if "dango_replaced" in att.get("filename", ""):
                continue
            content_type = att.get("content_type", "")
            if not content_type.startswith("image/"):
                continue
            try:
                async with session.get(att["url"]) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        images.append(Image(content=data, mime_type=content_type))
            except Exception as e:
                print(f"❌ [call_discord_agent] Failed to download image: {e}")
    return images


async def call_discord_agent(step_input: StepInput) -> StepOutput:
    """Run the Discord agent with per-request context injected via session_state."""
    data = step_input.previous_step_content

    if data.get("error"):
        return StepOutput(content=data)

    message_data = data["message_data"]
    unique_users = set(data.get("unique_users", []))
    mention_map: dict[str, str] = data.get("mention_map") or {}

    # Use injected agents (from ChatCog.extra_tools) when present, else module singletons.
    _injected: tuple | None = message_data.get("_agents")
    _fast: Agent = _injected[0] if _injected else fast_agent
    _deep: Agent | None = _injected[1] if _injected else deep_agent

    current_content = resolve_mentions(message_data["content"], mention_map)
    user_content = f"{message_data['author_name']}: {current_content}"
    current_images = await _download_current_images(message_data.get("attachments", []))
    messages_to_send = list(data["formatted_history"]) + [
        Message(role="user", content=user_content, images=current_images or None)
    ]

    if message_data.get("_force_deep") and _deep and DEEP_MODEL:
        print(f"🔀 [route] deep  ← forced via !! prefix")
        agent, model_name, context_budget = _deep, DEEP_MODEL, DEEP_CONTEXT_TOKEN_BUDGET
    else:
        history_texts = [
            m.content
            for m in data["formatted_history"]
            if isinstance(m.content, str) and m.content
        ]
        agent, model_name, context_budget = _select_agent(
            current_content, history_texts, fast=_fast, deep=_deep
        )

    # URL upgrade: fast Gemini lacks url_context but deep Gemini has it → use deep.
    # Intentionally Gemini-only: url_context is a Gemini-specific fetch feature.
    # Non-Gemini fast models are not upgraded — the user chose that provider
    # deliberately and it can still process URLs as plain text.
    if (
        agent is _fast
        and _deep is not None
        and _fast_gemini is not None
        and not getattr(_fast_gemini, "url_context", False)
        and _deep_gemini is not None
        and getattr(_deep_gemini, "url_context", False)
        and _URL_RE.search(current_content)
    ):
        print("🔀 [route] deep  ← URL in message, fast model lacks url_context")
        agent, model_name, context_budget = _deep, DEEP_MODEL, DEEP_CONTEXT_TOKEN_BUDGET

    if context_budget:
        before = len(messages_to_send)
        messages_to_send = _trim_to_token_budget(messages_to_send, context_budget)
        trimmed = before - len(messages_to_send)
        if trimmed:
            print(f"✂️ [call_discord_agent] Trimmed {trimmed} messages to fit token budget ({context_budget})")

    print(f"🤖 [call_discord_agent] Sending {len(messages_to_send)} messages to {model_name}")

    session_state = {
        "author_name": message_data["author_name"],
        "unique_users": list(unique_users),
        "chat_sys_prompt": message_data["_chat_sys_prompt"],
        "history_limit": message_data.get("_history_limit"),
        # Discord context — accessible inside tools via run_context.session_state
        "author_id": message_data.get("author_id"),
        "author_roles": message_data.get("author_roles", []),
        "_author_permissions": message_data.get("author_permissions", set()),
        "channel_id": message_data.get("channel_id"),
        "channel_name": message_data.get("channel_name", ""),
        "guild_id": message_data.get("guild_id"),
        "guild_name": message_data.get("guild_name", ""),
        # Discord objects — use get_discord_bot() / get_discord_interaction() helpers
        "_bot": message_data.get("_bot"),
        "_interaction": message_data.get("_interaction"),
    }

    fallback_name: str | None = None
    response = await _arun_agent(agent, messages_to_send, session_state)

    # Bidirectional fallback on error: fast→deep or deep→fast.
    if FALLBACK_ON_ERROR and response.status == RunStatus.error:
        fallback_agent: Agent | None = None
        if agent is _fast and _deep is not None:
            fallback_agent, fallback_name = _deep, DEEP_MODEL
        elif agent is _deep:
            fallback_agent, fallback_name = _fast, FAST_MODEL

        if fallback_agent is not None:
            print(f"⚡ [call_discord_agent] {model_name} failed, falling back to {fallback_name}")
            response = await _arun_agent(fallback_agent, messages_to_send, session_state)

    if response.status == RunStatus.error:
        tried = f"{model_name} and {fallback_name}" if fallback_name else model_name
        print(f"❌ [call_discord_agent] All models failed ({tried})")
        error_detail = (response.content or "").strip() or None
        body = f"⚠️ The model is currently overloaded ({tried} unavailable). Please try again later."
        if error_detail:
            body += f"\n{error_detail}"
        return StepOutput(
            content={
                "error": True,
                "error_message": format_sysinfo(body),
                "message_data": message_data,
                "ephemeral": session_state.get("_ephemeral", False),
                "discord_response": session_state.get("_discord_response"),
            }
        )

    llm_response = response.content or ""
    print(f"📥 [call_discord_agent] Received response ({len(llm_response)} chars)")

    return StepOutput(
        content={
            "llm_response": llm_response,
            "message_data": message_data,
            "ephemeral": session_state.get("_ephemeral", False),
            "discord_response": session_state.get("_discord_response"),
            "fallback_sysinfo": (
                format_sysinfo(f"⚡ {model_name} failed — response served by {fallback_name}.")
                if fallback_name else None
            ),
        }
    )
