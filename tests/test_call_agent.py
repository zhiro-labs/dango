"""
Characterization tests for the LLMChat step (dango/steps/call_agent.py).

They drive the step only through its public entry point, call_discord_agent,
with configuration supplied as environment variables (exactly as the bot gets
it) and Agno's Agent.arun replaced by a recorder. Nothing here depends on how
the step is organized internally, so the same tests hold across refactors.
"""

import asyncio
import importlib
import json
import os
import sys
from types import SimpleNamespace

import aiohttp
import httpx
import pytest
from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.workflow import StepInput

BASE_ENV = {"FAST_MODEL": "google:gemini-2.5-flash", "FAST_API_KEY": "fast-key"}
DEEP_GEMINI = {"DEEP_MODEL": "google:gemini-2.5-pro", "DEEP_API_KEY": "deep-key"}

_CONFIG_PREFIXES = (
    "FAST_", "DEEP_", "GEMINI_", "ENABLE_", "WORKSPACE_", "SKILLS_", "BRAVE_",
    "CUSTOM_APIS", "SQL_DATABASES", "CONTEXT_TOKEN_BUDGET", "AUTO_ROUTE", "FALLBACK_ON_ERROR",
)


# ── Harness ───────────────────────────────────────────────────────────────────

def _ok(content="reply"):
    return SimpleNamespace(status=RunStatus.completed, content=content)


def _err(content="boom"):
    return SimpleNamespace(status=RunStatus.error, content=content)


@pytest.fixture(autouse=True)
def isolated_env():
    """Start from no agent config and restore os.environ afterwards.

    The step writes provider keys (e.g. OPENAI_API_KEY) straight into
    os.environ, so monkeypatch alone cannot undo them.
    """
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(_CONFIG_PREFIXES) or key.endswith(("_API_KEY", "_TOKEN")) or key == "COMETAPI_KEY":
            del os.environ[key]
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def no_custom_extensions(monkeypatch):
    """Keep custom/*.py tools out of these tests."""
    from dango.extensions import loader, registry

    monkeypatch.setattr(loader, "_loaded", True)
    monkeypatch.setattr(registry, "_REGISTRY", [])
    monkeypatch.setattr(registry, "_RAW_TOOLS", [])


@pytest.fixture
def runs(monkeypatch):
    """Replace Agent.arun; queue outcomes in `runs.queue` (default: success).

    A queued response is returned as is. A queued exception is raised by the
    provider inside the agent's model.ainvoke, and the run fails the way Agno
    reports it: status=error, content=str(exception).
    """
    from agno.models.openai import OpenAIResponses

    from dango.extensions.context import Ctx

    rec = SimpleNamespace(calls=[], queue=[], sleeps=[], raising=None)

    async def fake_arun(self, input=None, session_state=None, **kwargs):
        rec.calls.append(SimpleNamespace(
            agent=self, input=input, session_state=session_state, ctx=Ctx.from_agent(),
        ))
        outcome = rec.queue.pop(0) if rec.queue else _ok()
        if isinstance(outcome, BaseException):
            rec.raising = outcome
            try:
                await self.model.ainvoke(messages=[], assistant_message=None)
            except Exception as e:
                return _err(str(e))
        return outcome

    async def provider_ainvoke(self, *args, **kwargs):
        raise rec.raising

    async def fake_sleep(delay, *args, **kwargs):
        rec.sleeps.append(delay)

    monkeypatch.setattr(Agent, "arun", fake_arun)
    monkeypatch.setattr(Gemini, "ainvoke", provider_ainvoke)
    monkeypatch.setattr(OpenAIResponses, "ainvoke", provider_ainvoke)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return rec


def _load_step(env: dict):
    """Re-import the step (and anything it owns) under the given env."""
    os.environ.update(env)
    for name in list(sys.modules):
        if name == "dango.steps.call_agent" or name == "dango.agent" or name.startswith("dango.agent."):
            del sys.modules[name]
    return importlib.import_module("dango.steps.call_agent")


def _message_data(**overrides) -> dict:
    data = {
        "content": "hello",
        "author_id": 42,
        "author_name": "Alice",
        "channel_id": 7,
        "channel_name": "general",
        "guild_id": 9,
        "guild_name": "Dango HQ",
        "author_permissions": ["send_messages"],
        "mentioned_users": [{"id": 5, "name": "Bob"}],
        "mentioned_roles": [],
        "attachments": [],
        "stickers": [],
        "_chat_sys_prompt": "You are Dango.",
        "_history_limit": 12,
        "_timezone": "UTC",
    }
    data.update(overrides)
    return data


def _step_input(message_data=None, history=None, mention_map=None) -> StepInput:
    return StepInput(previous_step_content={
        "formatted_history": history or [],
        "unique_users": ["Alice"],
        "mention_map": mention_map or {},
        "message_data": message_data or _message_data(),
    })


def run_steps(env: dict, *step_inputs: StepInput) -> list[dict]:
    """Load the step once under env and run it for each input in turn."""
    step = _load_step(env)
    return [asyncio.run(step.call_discord_agent(si)).content for si in step_inputs]


def run_step(env: dict, step_input: StepInput | None = None) -> dict:
    return run_steps(env, step_input or _step_input())[0]


def _tool_names(agent) -> list[str]:
    return [t.name for t in agent.tools or []]


# ── Model construction ────────────────────────────────────────────────────────

class TestModels:
    def test_google_fast_model_defaults(self, runs):
        run_step(BASE_ENV)
        model = runs.calls[0].agent.model
        assert isinstance(model, Gemini)
        assert model.id == "gemini-2.5-flash"
        assert model.api_key == "fast-key"
        assert (model.search, model.url_context) == (True, False)
        assert (model.retries, model.delay_between_retries, model.exponential_backoff) == (2, 1, True)
        assert (model.thinking_budget, model.thinking_level, model.grounding_dynamic_threshold) == (None, None, None)
        assert os.environ["GOOGLE_API_KEY"] == "fast-key"

    def test_gemini_params_prefer_model_prefix_over_shared(self, runs):
        run_step({
            **BASE_ENV,
            "FAST_SEARCH": "false", "GEMINI_SEARCH": "true",
            "GEMINI_URL_CONTEXT": "true",
            "FAST_THINKING_BUDGET": "128", "GEMINI_THINKING_BUDGET": "999",
            "GEMINI_THINKING_LEVEL": "low",
            "GEMINI_GROUNDING_THRESHOLD": "0.3",
            "FAST_RETRIES": "5", "FAST_RETRY_DELAY": "3",
        })
        model = runs.calls[0].agent.model
        assert (model.search, model.url_context) == (False, True)
        assert (model.thinking_budget, model.thinking_level) == (128, "low")
        assert model.grounding_dynamic_threshold == 0.3
        assert (model.retries, model.delay_between_retries) == (5, 3)

    def test_gemma_never_gets_url_context(self, runs):
        run_step({"FAST_MODEL": "google:gemma-3-27b-it", "FAST_API_KEY": "k", "GEMINI_URL_CONTEXT": "true"})
        assert runs.calls[0].agent.model.url_context is False

    def test_bare_model_id_means_google(self, runs):
        run_step({"FAST_MODEL": "gemini-2.5-flash", "FAST_API_KEY": "k"})
        assert isinstance(runs.calls[0].agent.model, Gemini)

    def test_other_providers_resolved_by_agno_with_injected_key(self, runs):
        run_step({**BASE_ENV, "DEEP_MODEL": "openai:gpt-4o", "DEEP_API_KEY": "deep-key"},
                 _step_input(_message_data(_force_deep=True)))
        model = runs.calls[0].agent.model
        assert not isinstance(model, Gemini)
        assert model.id == "gpt-4o"
        assert os.environ["OPENAI_API_KEY"] == "deep-key"

    def test_deep_key_falls_back_to_fast_key(self, runs):
        run_step({**BASE_ENV, "DEEP_MODEL": "openai:gpt-4o"})
        assert os.environ["OPENAI_API_KEY"] == "fast-key"

    def test_existing_provider_env_var_is_kept(self, runs):
        os.environ["OPENAI_API_KEY"] = "set-by-user"
        run_step({**BASE_ENV, "DEEP_MODEL": "openai:gpt-4o", "DEEP_API_KEY": "deep-key"})
        assert os.environ["OPENAI_API_KEY"] == "set-by-user"

    def test_base_url_sets_ollama_host(self, runs):
        run_step({"FAST_MODEL": "ollama:llama3.2", "FAST_API_KEY": "local",
                  "FAST_BASE_URL": "http://host.docker.internal:11434"})
        assert runs.calls[0].agent.model.host == "http://host.docker.internal:11434"

    def test_base_url_sets_openai_like_endpoint_and_key(self, runs):
        run_step({"FAST_MODEL": "openai:gpt-4o", "FAST_API_KEY": "k", "FAST_BASE_URL": "http://proxy/v1"})
        model = runs.calls[0].agent.model
        assert (model.base_url, model.api_key) == ("http://proxy/v1", "k")

    def test_missing_fast_model_raises(self, runs):
        with pytest.raises(RuntimeError, match="FAST_MODEL is not set"):
            run_step({})


# ── Tools and skills ──────────────────────────────────────────────────────────

@pytest.fixture
def skills_root(tmp_path):
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill for tests.\n---\n\nAlways answer in haiku.\n",
        encoding="utf-8",
    )
    return str(tmp_path / "skills")


class TestToolsAndSkills:
    def test_no_tools_or_skills_by_default(self, runs):
        run_step(BASE_ENV)
        agent = runs.calls[0].agent
        assert not agent.tools
        assert agent.skills is None
        assert agent.add_history_to_context is False
        assert agent.markdown is False

    def test_all_tools_in_order_on_both_agents(self, runs, tmp_path, skills_root):
        env = {
            **BASE_ENV, **DEEP_GEMINI,
            "ENABLE_WORKSPACE": "on", "WORKSPACE_ROOT": str(tmp_path),
            "ENABLE_SKILLS": "on", "SKILLS_ROOT": skills_root,
            "ENABLE_DUCKDUCKGO": "on",
            "ENABLE_BRAVE_SEARCH": "on", "BRAVE_API_KEY": "bk",
            "ENABLE_WEBSITE_TOOLS": "on",
            "ENABLE_CUSTOM_APIS": "on",
            "CUSTOM_APIS_JSON": json.dumps([{"name": "Weather API", "base_url": "https://w.example", "api_key": "a"}]),
            "ENABLE_SQL_DATABASES": "on",
            "SQL_DATABASES_JSON": json.dumps([{"name": "main", "db_url": "sqlite://"}]),
        }
        run_steps(env, _step_input(), _step_input(_message_data(_force_deep=True)))
        expected =["workspace", "websearch", "brave_search", "website_tools", "call_Weather_API_api", "query_main"]
        fast, deep = runs.calls[0].agent, runs.calls[1].agent
        assert fast is not deep
        assert _tool_names(fast) == expected
        assert _tool_names(deep) == expected
        assert sorted(fast.tools[3].functions) == ["crawl_website", "read_url"]
        assert fast.skills.get_skill_names() == ["demo"]
        assert deep.skills is fast.skills

    def test_disabled_flags_ignore_their_config(self, runs):
        run_step({**BASE_ENV, "BRAVE_API_KEY": "bk",
                  "CUSTOM_APIS_JSON": json.dumps([{"name": "a", "base_url": "https://a"}])})
        assert not runs.calls[0].agent.tools

    def test_brave_without_key_is_skipped(self, runs):
        run_step({**BASE_ENV, "ENABLE_BRAVE_SEARCH": "on", "ENABLE_WEBSITE_TOOLS": "on"})
        assert _tool_names(runs.calls[0].agent) == ["website_tools"]

    def test_duplicate_custom_api_names_are_rejected(self, runs):
        apis = [{"name": "my api", "base_url": "https://a"}, {"name": "my-api", "base_url": "https://b"}]
        with pytest.raises(ValueError, match="same sanitized name 'my_api'"):
            run_step({**BASE_ENV, "CUSTOM_APIS_JSON": json.dumps(apis)})

    def test_skills_root_missing_disables_skills(self, runs, tmp_path):
        run_step({**BASE_ENV, "ENABLE_SKILLS": "on", "SKILLS_ROOT": str(tmp_path / "nope")})
        assert runs.calls[0].agent.skills is None


# ── Instructions ──────────────────────────────────────────────────────────────

class TestInstructions:
    def _instructions(self, runs) -> str:
        call = runs.calls[0]
        return call.agent.instructions(session_state=call.session_state)

    def test_plain_prompt_when_contextual_off(self, runs):
        run_step({**BASE_ENV, "ENABLE_CONTEXTUAL_SYSTEM_PROMPT": "off"})
        assert self._instructions(runs) == "You are Dango."

    def test_contextual_prompt_by_default(self, runs):
        run_step(BASE_ENV)
        text = self._instructions(runs)
        assert text.startswith("You are Dango.\n\n---\n\n")
        assert "You are talking to a human named Alice." in text
        assert "up to 12 historical messages" in text
        assert "Timezone: UTC" in text

    def test_forced_skill_is_injected(self, runs, skills_root):
        env = {**BASE_ENV, "ENABLE_CONTEXTUAL_SYSTEM_PROMPT": "off", "ENABLE_SKILLS": "on", "SKILLS_ROOT": skills_root}
        run_step(env, _step_input(_message_data(_force_skill="demo")))
        text = self._instructions(runs)
        assert text.startswith("You are Dango.\n\n---\n\n# Active skill: demo\n")
        assert text.endswith("Always answer in haiku.")

    def test_unknown_forced_skill_is_ignored(self, runs, skills_root):
        env = {**BASE_ENV, "ENABLE_CONTEXTUAL_SYSTEM_PROMPT": "off", "ENABLE_SKILLS": "on", "SKILLS_ROOT": skills_root}
        run_step(env, _step_input(_message_data(_force_skill="missing")))
        assert self._instructions(runs) == "You are Dango."


# ── Request building ──────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status, self._body = status, body

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def http(monkeypatch):
    """Fake aiohttp: `http.bodies[url] = bytes`; unknown URLs return 404."""
    state = SimpleNamespace(bodies={}, fetched=[], broken=set())

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url):
            state.fetched.append(url)
            if url in state.broken:
                raise aiohttp.ClientError("network down")
            body = state.bodies.get(url)
            return _FakeResponse(200 if body is not None else 404, body or b"")

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    return state


class TestRequest:
    def test_messages_and_session_state(self, runs):
        history = [Message(role="user", content="Bob: earlier"), Message(role="assistant", content="hi Bob")]
        out = run_step(BASE_ENV, _step_input(history=history))

        call = runs.calls[0]
        assert [(m.role, m.content) for m in call.input] == [
            ("user", "Bob: earlier"), ("assistant", "hi Bob"), ("user", "Alice: hello"),
        ]
        assert call.input[-1].images is None
        assert call.session_state == {
            "author_name": "Alice",
            "author_id": 42,
            "unique_users": ["Alice"],
            "chat_sys_prompt": "You are Dango.",
            "history_limit": 12,
            "timezone": "UTC",
            "channel_id": 7,
            "channel_name": "general",
            "guild_id": 9,
            "guild_name": "Dango HQ",
            "author_permissions": ["send_messages"],
            "mentioned_users": [{"id": 5, "name": "Bob"}],
            "mentioned_roles": [],
            "forced_skill": None,
        }
        assert out["llm_response"] == "reply"
        assert out["fallback_sysinfo"] is None
        assert out["message_data"]["author_name"] == "Alice"

    def test_mentions_are_resolved(self, runs):
        run_step(BASE_ENV, _step_input(_message_data(content="<@5> look"), mention_map={"<@5>": "@Bob"}))
        assert runs.calls[0].input[-1].content == "Alice: @Bob look"

    def test_request_context_visible_to_tools_and_reset_after(self, runs):
        from dango.extensions.context import Ctx

        run_step(BASE_ENV)
        ctx = runs.calls[0].ctx
        assert (ctx.source, ctx.author_name, ctx.author_id, ctx.channel_id, ctx.guild_name) == (
            "agent", "Alice", 42, 7, "Dango HQ",
        )
        assert ctx.mentioned_user_ids == [5]
        assert Ctx.from_agent().author_id is None

    def test_images_and_stickers_are_downloaded(self, runs, http):
        http.bodies = {"https/a.png": b"A", "https/s.png": b"S", "https/s.gif": b"G"}
        http.broken = {"https/broken.png"}
        message = _message_data(
            content="",
            attachments=[
                {"filename": "a.png", "url": "https/a.png", "content_type": "image/png"},
                {"filename": "notes.txt", "url": "https/notes.txt", "content_type": "text/plain"},
                {"filename": "dango_replaced_table_1_1.md", "url": "https/t.png", "content_type": "image/png"},
                {"filename": "gone.png", "url": "https/gone.png", "content_type": "image/png"},
                {"filename": "broken.png", "url": "https/broken.png", "content_type": "image/png"},
            ],
            stickers=[
                {"name": "wave", "url": "https/s.png", "format": "APNG"},
                {"name": "party", "url": "https/s.json", "format": "lottie"},
                {"name": "", "url": "https/s.gif", "format": "gif"},
            ],
        )
        run_step(BASE_ENV, _step_input(message))

        last = runs.calls[0].input[-1]
        assert last.content == "Alice: [sticker: wave, party]"
        assert [(i.content, i.mime_type) for i in last.images] == [
            (b"A", "image/png"), (b"S", "image/png"), (b"G", "image/gif"),
        ]
        assert http.fetched == ["https/a.png", "https/gone.png", "https/broken.png", "https/s.png", "https/s.gif"]

    def test_sticker_note_follows_text(self, runs, http):
        message = _message_data(stickers=[{"name": "wave", "url": "https/x.json", "format": "lottie"}])
        run_step(BASE_ENV, _step_input(message))
        assert runs.calls[0].input[-1].content == "Alice: hello [sticker: wave]"

    def test_previous_step_error_passes_through(self, runs):
        data = {"error": True, "error_message": "Cannot access channel", "message_data": {}}
        assert run_step(BASE_ENV, StepInput(previous_step_content=data)) == data
        assert runs.calls == []


# ── Routing and context trimming ──────────────────────────────────────────────

COMPLEX = "Why does quicksort degrade to O(n^2) on sorted input? Explain step by step and compare it with mergesort."


def _model_ids(runs) -> list[str]:
    return [c.agent.model.id for c in runs.calls]


class TestRouting:
    def test_fast_by_default(self, runs):
        run_step({**BASE_ENV, **DEEP_GEMINI})
        assert _model_ids(runs) == ["gemini-2.5-flash"]

    def test_force_deep(self, runs):
        run_step({**BASE_ENV, **DEEP_GEMINI}, _step_input(_message_data(_force_deep=True)))
        assert _model_ids(runs) == ["gemini-2.5-pro"]

    def test_force_deep_without_deep_model_uses_fast(self, runs):
        run_step(BASE_ENV, _step_input(_message_data(_force_deep=True)))
        assert _model_ids(runs) == ["gemini-2.5-flash"]

    @pytest.mark.parametrize("content, expected", [(COMPLEX, "gemini-2.5-pro"), ("thanks!", "gemini-2.5-flash")])
    def test_auto_route_by_complexity(self, runs, content, expected):
        run_step({**BASE_ENV, **DEEP_GEMINI, "AUTO_ROUTE": "on"}, _step_input(_message_data(content=content)))
        assert _model_ids(runs) == [expected]

    def test_auto_route_off_keeps_fast(self, runs):
        run_step({**BASE_ENV, **DEEP_GEMINI}, _step_input(_message_data(content=COMPLEX)))
        assert _model_ids(runs) == ["gemini-2.5-flash"]

    def test_auto_route_uses_history_topic(self, runs):
        history = [Message(role="user", content=f"Bob: {COMPLEX}")]
        run_step({**BASE_ENV, **DEEP_GEMINI, "AUTO_ROUTE": "on"},
                 _step_input(_message_data(content="and what about heapsort?"), history=history))
        assert _model_ids(runs) == ["gemini-2.5-pro"]

    def test_url_upgrades_to_deep_gemini_with_url_context(self, runs):
        run_step({**BASE_ENV, **DEEP_GEMINI, "DEEP_URL_CONTEXT": "true"},
                 _step_input(_message_data(content="summarize https://example.com/post")))
        assert _model_ids(runs) == ["gemini-2.5-pro"]

    @pytest.mark.parametrize("extra", [
        {"DEEP_URL_CONTEXT": "false"},
        {"DEEP_URL_CONTEXT": "true", "FAST_URL_CONTEXT": "true"},
    ])
    def test_url_upgrade_needs_the_gap(self, runs, extra):
        run_step({**BASE_ENV, **DEEP_GEMINI, **extra},
                 _step_input(_message_data(content="summarize https://example.com/post")))
        assert _model_ids(runs) == ["gemini-2.5-flash"]

    def test_url_upgrade_is_gemini_only(self, runs):
        run_step({**BASE_ENV, "DEEP_MODEL": "openai:gpt-4o", "GEMINI_URL_CONTEXT": "false"},
                 _step_input(_message_data(content="summarize https://example.com/post")))
        assert _model_ids(runs) == ["gemini-2.5-flash"]


@pytest.fixture
def word_tokens(monkeypatch):
    """Deterministic token counter: one token per word; records model ids."""
    import agno.utils.tokens

    seen = []

    def count(messages, model_id=None, **kwargs):
        seen.append(model_id)
        return sum(len(str(m.content).split()) for m in messages)

    monkeypatch.setattr(agno.utils.tokens, "count_tokens", count)
    return seen


def _history(n: int) -> list[Message]:
    return [Message(role="user" if i % 2 == 0 else "assistant", content=f"m{i} " + "w " * 9) for i in range(n)]


class TestTrimming:
    def test_no_budget_sends_everything(self, runs, word_tokens):
        run_step(BASE_ENV, _step_input(history=_history(6)))
        assert len(runs.calls[0].input) == 7
        assert word_tokens == []

    # 6 history messages of 10 "tokens" each + the current message (2) = 62.
    @pytest.mark.parametrize("budget, kept", [
        ("25", ["m4", "m5", "Alice:"]),  # proportional cut lands under budget
        ("11", ["Alice:"]),               # proportional cut overshoots; pop until it fits
    ])
    def test_budget_drops_oldest_and_keeps_current(self, runs, word_tokens, budget, kept):
        run_step({**BASE_ENV, "CONTEXT_TOKEN_BUDGET": budget}, _step_input(history=_history(6)))
        assert [m.content.split()[0] for m in runs.calls[0].input] == kept

    def test_under_budget_is_untouched(self, runs, word_tokens):
        run_step({**BASE_ENV, "CONTEXT_TOKEN_BUDGET": "1000"}, _step_input(history=_history(6)))
        assert len(runs.calls[0].input) == 7

    def test_per_model_budget(self, runs, word_tokens):
        env = {**BASE_ENV, **DEEP_GEMINI, "CONTEXT_TOKEN_BUDGET": "1000", "DEEP_CONTEXT_TOKEN_BUDGET": "25"}
        run_step(env, _step_input(_message_data(_force_deep=True), history=_history(6)))
        assert len(runs.calls[0].input) == 3

    @pytest.mark.parametrize("force_deep, model_id", [(False, "gemini-2.5-flash"), (True, "gpt-4o")])
    def test_tokens_counted_with_the_model_that_runs(self, runs, word_tokens, force_deep, model_id):
        env = {**BASE_ENV, "DEEP_MODEL": "openai:gpt-4o", "CONTEXT_TOKEN_BUDGET": "25"}
        run_step(env, _step_input(_message_data(_force_deep=force_deep), history=_history(6)))
        assert runs.calls[0].agent.model.id == model_id
        assert set(word_tokens) == {model_id}

    def test_counting_failure_keeps_everything(self, runs, monkeypatch):
        import agno.utils.tokens

        def broken(*args, **kwargs):
            raise RuntimeError("no tokenizer")

        monkeypatch.setattr(agno.utils.tokens, "count_tokens", broken)
        run_step({**BASE_ENV, "CONTEXT_TOKEN_BUDGET": "5"}, _step_input(history=_history(6)))
        assert len(runs.calls[0].input) == 7


# ── Retry, fallback and errors ────────────────────────────────────────────────

OPENAI_FAST = {"FAST_MODEL": "openai:gpt-4o", "FAST_API_KEY": "k"}


class TestRetryAndFallback:
    def test_non_gemini_retries_twice_with_backoff(self, runs):
        runs.queue = [_err(), _err(), _ok("third time")]
        out = run_step(OPENAI_FAST)
        assert len(runs.calls) == 3
        assert runs.sleeps == [1, 2]
        assert out["llm_response"] == "third time"

    def test_gemini_relies_on_model_level_retry(self, runs):
        runs.queue = [_err()]
        out = run_step(BASE_ENV)
        assert len(runs.calls) == 1
        assert out["error"] is True

    def test_fallback_fast_to_deep(self, runs):
        runs.queue = [_err(), _ok("from deep")]
        out = run_step({**BASE_ENV, **DEEP_GEMINI, "FALLBACK_ON_ERROR": "on"})
        assert _model_ids(runs) == ["gemini-2.5-flash", "gemini-2.5-pro"]
        assert out["llm_response"] == "from deep"
        assert out["fallback_sysinfo"] == (
            "> [dango-sysinfo]\n> ⚡ google:gemini-2.5-flash failed — response served by google:gemini-2.5-pro."
        )
        assert runs.calls[0].session_state is runs.calls[1].session_state

    def test_fallback_deep_to_fast(self, runs):
        runs.queue = [_err(), _ok("from fast")]
        out = run_step({**BASE_ENV, **DEEP_GEMINI, "FALLBACK_ON_ERROR": "on"},
                       _step_input(_message_data(_force_deep=True)))
        assert _model_ids(runs) == ["gemini-2.5-pro", "gemini-2.5-flash"]
        assert out["llm_response"] == "from fast"

    def test_fallback_retries_non_gemini_too(self, runs):
        runs.queue = [_err(), _err(), _err(), _ok("deep")]
        out = run_step({**OPENAI_FAST, **DEEP_GEMINI, "FALLBACK_ON_ERROR": "on"})
        assert len(runs.calls) == 4
        assert out["llm_response"] == "deep"

    def test_no_fallback_without_deep_model(self, runs):
        runs.queue = [_err()]
        out = run_step({**BASE_ENV, "FALLBACK_ON_ERROR": "on"})
        assert len(runs.calls) == 1
        assert out["error"] is True


# ── Failure replies ───────────────────────────────────────────────────────────

def _provider_error(message: str, status: int, cause: BaseException | None = None):
    from agno.exceptions import ModelProviderError

    error = ModelProviderError(message=message, status_code=status)
    error.__cause__ = cause
    return error


GEMINI_503 = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.'}}"


class TestFailureReplies:
    def test_overloaded_reply_names_every_model_and_shows_detail(self, runs):
        runs.queue = [_provider_error(GEMINI_503, 503), _provider_error(GEMINI_503, 503)]
        out = run_step({**BASE_ENV, **DEEP_GEMINI, "FALLBACK_ON_ERROR": "on"})
        assert out["error"] is True
        assert out["error_message"] == (
            "> [dango-sysinfo]\n> ⚠️ The model is currently overloaded "
            "(google:gemini-2.5-flash and google:gemini-2.5-pro unavailable). Please try again later.\n"
            f"> {GEMINI_503}"
        )
        assert out["message_data"]["author_name"] == "Alice"

    @pytest.mark.parametrize("error, phrase", [
        (_provider_error("400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.", 400),
         "rejected the API key or denied access"),
        (_provider_error("403 PERMISSION_DENIED. Your project has been denied access.", 403),
         "rejected the API key or denied access"),
        (_provider_error("429 RESOURCE_EXHAUSTED. You exceeded your current quota.", 429),
         "rate limit or quota has been reached"),
        (_provider_error("404 NOT_FOUND. models/gemini-9 is not found for API version v1beta.", 404),
         "configured model was not found"),
        (_provider_error("500 INTERNAL. An internal error has occurred.", 500),
         "currently overloaded"),
        (_provider_error("400 INVALID_ARGUMENT. Request contains an invalid argument.", 400),
         "provider rejected the request"),
    ])
    def test_gemini_errors(self, runs, error, phrase):
        runs.queue = [error]
        out = run_step(BASE_ENV)
        assert phrase in out["error_message"]
        assert out["error_message"].endswith(f"\n> {error.message}")

    @pytest.mark.parametrize("error, phrase, attempts", [
        (_provider_error("Incorrect API key provided: sk-abc***xyz.", 401),
         "rejected the API key or denied access", 1),
        (_provider_error("You exceeded your current quota, please check your plan.", 429),
         "rate limit or quota has been reached", 3),
        (_provider_error("The model `gpt-9` does not exist or you do not have access to it.", 404),
         "configured model was not found", 1),
        (_provider_error("Connection error.", 502, cause=httpx.ConnectError("connection refused")),
         "Could not reach the model provider", 3),
    ])
    def test_openai_errors(self, runs, error, phrase, attempts):
        runs.queue = [error, error, error]
        out = run_step(OPENAI_FAST)
        assert len(runs.calls) == attempts
        assert phrase in out["error_message"]

    def test_context_window_exceeded(self, runs):
        from agno.exceptions import ContextWindowExceededError

        runs.queue = [ContextWindowExceededError(message="This model's maximum context length is 1048576 tokens.")]
        out = run_step(BASE_ENV)
        assert "too long for the model (google:gemini-2.5-flash). Use /newchat" in out["error_message"]

    def test_last_model_decides_the_reply(self, runs):
        runs.queue = [_provider_error(GEMINI_503, 503), _provider_error("API key expired.", 400)]
        out = run_step({**BASE_ENV, **DEEP_GEMINI, "FALLBACK_ON_ERROR": "on"})
        assert "rejected the API key or denied access" in out["error_message"]
        assert "(google:gemini-2.5-flash and google:gemini-2.5-pro)" in out["error_message"]

    def test_only_the_final_attempt_counts(self, runs):
        runs.queue = [_provider_error(GEMINI_503, 503), _err("boom"), _err("boom")]
        out = run_step(OPENAI_FAST)
        assert len(runs.calls) == 3
        # The final attempt failed without a provider exception: classified by its text.
        assert out["error_message"] == (
            "> [dango-sysinfo]\n> ⚠️ The model returned an error (openai:gpt-4o). Please try again later.\n> boom"
        )

    def test_gemini_unreadable_error_is_fixed_before_classifying(self, runs):
        # Agno bug: Gemini errors can carry a bound-method repr instead of text.
        cause = RuntimeError("429 RESOURCE_EXHAUSTED. Quota exceeded for metric.")
        runs.queue = [_provider_error("<bound method ClientResponse.text>", 502, cause=cause)]
        out = run_step(BASE_ENV)
        assert "rate limit or quota has been reached" in out["error_message"]
        assert out["error_message"].endswith("\n> 429 RESOURCE_EXHAUSTED. Quota exceeded for metric.")

    @pytest.mark.parametrize("content, phrase", [
        ("quota exceeded", "rate limit or quota has been reached"),
        ("boom", "The model returned an error"),
        ("", "The model returned an error"),
    ])
    def test_failures_without_a_provider_exception_use_text(self, runs, content, phrase):
        runs.queue = [_err(content)]
        out = run_step(BASE_ENV)
        assert phrase in out["error_message"]


class TestRetryDecisions:
    """Non-Gemini models retry only failures a retry could fix."""

    @pytest.mark.parametrize("error", [
        _provider_error("Incorrect API key provided.", 401),
        _provider_error("400 INVALID_ARGUMENT. API key not valid.", 400),
        _provider_error("The model `gpt-9` does not exist.", 404),
        _provider_error("This model's maximum context length is 128000 tokens.", 400),
        _provider_error("Invalid 'messages[1].role'", 422),
    ])
    def test_unfixable_errors_are_not_retried(self, runs, error):
        runs.queue = [error, _ok("would have worked")]
        out = run_step(OPENAI_FAST)
        assert len(runs.calls) == 1
        assert runs.sleeps == []
        assert out["error"] is True

    @pytest.mark.parametrize("error", [
        _provider_error(GEMINI_503, 503),
        _provider_error("You exceeded your current quota.", 429),
        _provider_error("Connection error.", 502, cause=httpx.ConnectError("refused")),
        _provider_error("something odd", 502),
    ])
    def test_transient_errors_are_retried(self, runs, error):
        runs.queue = [error, _ok("second time")]
        out = run_step(OPENAI_FAST)
        assert len(runs.calls) == 2
        assert runs.sleeps == [1]
        assert out["llm_response"] == "second time"

    def test_text_only_failure_is_judged_by_its_text(self, runs):
        runs.queue = [_err("Incorrect API key provided."), _ok("would have worked")]
        run_step(OPENAI_FAST)
        assert len(runs.calls) == 1

    def test_retry_stops_once_an_unfixable_error_appears(self, runs):
        runs.queue = [_provider_error(GEMINI_503, 503), _provider_error("Incorrect API key provided.", 401)]
        out = run_step(OPENAI_FAST)
        assert len(runs.calls) == 2
        assert runs.sleeps == [1]
        assert "rejected the API key or denied access" in out["error_message"]

    def test_unfixable_error_goes_straight_to_fallback(self, runs):
        runs.queue = [_provider_error("Incorrect API key provided.", 401), _ok("from deep")]
        out = run_step({**OPENAI_FAST, **DEEP_GEMINI, "FALLBACK_ON_ERROR": "on"})
        assert _model_ids(runs) == ["gpt-4o", "gemini-2.5-pro"]
        assert runs.sleeps == []
        assert out["llm_response"] == "from deep"
        assert out["fallback_sysinfo"] == (
            "> [dango-sysinfo]\n> ⚡ openai:gpt-4o failed — response served by google:gemini-2.5-pro."
        )
