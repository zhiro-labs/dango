"""
Tests for keeping large tool results out of the model's context.

Agno's result offloading replaces a long tool result with a preview and a
result id; the model reads the rest with read_result / search_result. Dango
backs it with a SQLite file in a temporary directory (dango/agent/result_store.py)
while the agents themselves keep no database.
"""

import asyncio
import importlib
import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dango.agent.settings import load_settings

_CONFIG_PREFIXES = (
    "FAST_", "DEEP_", "GEMINI_", "ENABLE_", "WORKSPACE_", "SKILLS_", "BRAVE_", "TOOL_RESULT_",
    "CUSTOM_APIS", "SQL_DATABASES", "CONTEXT_TOKEN_BUDGET", "AUTO_ROUTE", "FALLBACK_ON_ERROR",
    "DISCORD_", "MESSAGE_BATCH_",
)


@pytest.fixture(autouse=True)
def isolated_env():
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(_CONFIG_PREFIXES) or key.endswith(("_API_KEY", "_TOKEN")) or "PROXY" in key.upper():
            del os.environ[key]
    os.environ["AGNO_TELEMETRY"] = "false"
    yield
    os.environ.clear()
    os.environ.update(saved)


# ── Settings ──────────────────────────────────────────────────────────────────

class TestSettings:
    def test_defaults(self):
        s = load_settings()
        assert (s.tool_result_offload_chars, s.tool_result_ttl_seconds) == (16_000, 3_600)

    @pytest.mark.parametrize("raw, expected", [("0", 0), (" 50000 ", 50_000), ("", 16_000)])
    def test_threshold_values(self, raw, expected):
        os.environ["TOOL_RESULT_OFFLOAD_CHARS"] = raw
        assert load_settings().tool_result_offload_chars == expected

    @pytest.mark.parametrize("name, raw, message", [
        ("TOOL_RESULT_OFFLOAD_CHARS", "lots", "must be a whole number"),
        ("TOOL_RESULT_OFFLOAD_CHARS", "-1", "must be 0 or more"),
        ("TOOL_RESULT_TTL_SECONDS", "1.5", "must be a whole number"),
    ])
    def test_bad_values_fail_at_startup(self, name, raw, message):
        os.environ[name] = raw
        with pytest.raises(ValueError, match=f"{name} {message}"):
            load_settings()


# ── The temporary store ───────────────────────────────────────────────────────

@pytest.fixture
def result_store(monkeypatch):
    from dango.agent import result_store as module

    monkeypatch.setattr(module, "_temp_dir", None)
    yield module
    module.remove_temp_directory()


class TestTemporaryStore:
    def test_off_when_threshold_is_zero(self, result_store):
        os.environ["TOOL_RESULT_OFFLOAD_CHARS"] = "0"
        assert result_store.make_result_store(load_settings()) is None
        assert result_store._temp_dir is None  # nothing created

    def test_sqlite_file_in_a_fresh_temp_dir(self, result_store):
        os.environ["TOOL_RESULT_OFFLOAD_CHARS"] = "5000"
        os.environ["TOOL_RESULT_TTL_SECONDS"] = "600"
        store = result_store.make_result_store(load_settings())

        assert (store.threshold_chars, store.ttl_seconds) == (5000, 600)
        db_file = Path(store.db.db_file)
        assert db_file.name == "tool_results.db"
        assert db_file.parent.name.startswith("dango-tool-results-")
        assert db_file.parent.parent.resolve() == Path(tempfile.gettempdir()).resolve()

    def test_ttl_zero_keeps_results_until_exit(self, result_store):
        os.environ["TOOL_RESULT_TTL_SECONDS"] = "0"
        assert result_store.make_result_store(load_settings()).ttl_seconds is None

    def test_one_directory_per_process_removed_at_exit(self, result_store):
        first = result_store.make_result_store(load_settings())
        second = result_store.make_result_store(load_settings())
        directory = Path(first.db.db_file).parent
        assert Path(second.db.db_file).parent == directory
        assert directory.is_dir()

        result_store.remove_temp_directory()
        assert not directory.exists()
        result_store.remove_temp_directory()  # safe to repeat


# ── Through Dango's LLM step with the real Agno run loop ──────────────────────

class FakeWorld:
    """One local server playing an OpenAI-compatible model and a REST API."""

    LINES = 1500

    def __init__(self):
        self.model_requests: list[dict] = []
        world = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = "\n".join(f"item-{i}: widget batch {i} " + "x" * 30 for i in range(world.LINES))
                self._send(200, body.encode(), "text/plain")

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["content-length"])))
                world.model_requests.append(request)
                self._send(200, json.dumps(world.reply(request)).encode(), "application/json")

            def _send(self, status, data, content_type):
                self.send_response(status)
                self.send_header("content-type", content_type)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def _completion(message, finish="stop"):
        return {"id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o",
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    def _call(self, name, args):
        return self._completion({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}},
        ]}, "tool_calls")

    def reply(self, request):
        """Script: call the API, then read line 1200 back if the result was stored."""
        tools = [m for m in request["messages"] if m["role"] == "tool"]
        if not tools:
            return self._call("call_inventory_api", {"endpoint": "items"})
        stored = re.search(r"res_[0-9a-f]+", tools[0]["content"])
        if len(tools) == 1 and stored:
            return self._call("read_result", {"result_id": stored.group(0), "start_line": 1200, "end_line": 1200})
        return self._completion({"role": "assistant", "content": "Item 1199 is a widget."})


@pytest.fixture
def world():
    w = FakeWorld()
    yield w
    w.server.shutdown()


def _run_step(world, threshold: str):
    os.environ.update({
        "FAST_MODEL": "openai-chat:gpt-4o",
        "FAST_API_KEY": "sk-test",
        "FAST_BASE_URL": f"{world.url}/v1",
        "ENABLE_CONTEXTUAL_SYSTEM_PROMPT": "off",
        "ENABLE_CUSTOM_APIS": "on",
        "CUSTOM_APIS_JSON": json.dumps([{"name": "inventory", "base_url": f"{world.url}/api"}]),
        "TOOL_RESULT_OFFLOAD_CHARS": threshold,
    })
    for name in list(sys.modules):
        if name == "dango.steps.call_agent" or name.startswith("dango.agent"):
            del sys.modules[name]
    step = importlib.import_module("dango.steps.call_agent")

    from agno.workflow import StepInput
    message = {"content": "what is item 1199?", "author_name": "Alice", "author_id": 1,
               "attachments": [], "stickers": [], "_chat_sys_prompt": "You are Dango.",
               "_history_limit": 5, "_timezone": "UTC"}
    out = asyncio.run(step.call_discord_agent(StepInput(previous_step_content={
        "formatted_history": [], "unique_users": ["Alice"], "mention_map": {}, "message_data": message,
    }))).content
    agents = importlib.import_module("dango.agent.registry").get_agents()
    importlib.import_module("dango.agent.result_store").remove_temp_directory()
    return out, agents


@pytest.fixture
def no_custom_extensions(monkeypatch):
    from dango.extensions import loader, registry

    monkeypatch.setattr(loader, "_loaded", True)
    monkeypatch.setattr(registry, "_REGISTRY", [])
    monkeypatch.setattr(registry, "_RAW_TOOLS", [])


def test_large_result_reaches_the_model_as_a_preview(world, no_custom_extensions):
    out, agents = _run_step(world, threshold="4000")

    assert out["llm_response"] == "Item 1199 is a widget."
    assert agents.fast.db is None  # conversations are not stored

    second = world.model_requests[1]
    preview = next(m["content"] for m in second["messages"] if m["role"] == "tool")
    assert len(preview) < 4000
    assert re.search(r'<result id="res_[0-9a-f]+" tool="call_inventory_api"', preview)
    assert "item-1199:" not in preview
    assert {"read_result", "search_result"} <= {t["function"]["name"] for t in second["tools"]}

    read_back = [m["content"] for m in world.model_requests[2]["messages"] if m["role"] == "tool"][1]
    assert "item-1199: widget batch 1199" in read_back


def test_threshold_zero_sends_results_in_full(world, no_custom_extensions):
    out, agents = _run_step(world, threshold="0")

    assert out["llm_response"] == "Item 1199 is a widget."
    second = world.model_requests[1]
    full = next(m["content"] for m in second["messages"] if m["role"] == "tool")
    assert "item-1199: widget batch 1199" in full
    assert "read_result" not in {t["function"]["name"] for t in second["tools"]}
    assert agents.fast.offload_tool_results is None


# ── Dashboard → config.yaml → env ─────────────────────────────────────────────

ORIGIN = {"origin": "http://localhost:17860"}


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # data/config.yaml is relative
    from web import main as web_main

    return TestClient(web_main.app, base_url="http://localhost:17860")


class TestDashboard:
    def test_saved_values_reach_the_bot(self, dashboard):
        import app_config

        r = dashboard.post("/api/config/advanced", headers=ORIGIN, data={
            "context_token_budget": "", "tool_result_offload_chars": " 50000 ", "tool_result_ttl_seconds": "0",
        })
        assert "Saved" in r.text

        app_config.inject_config_to_env()
        assert (os.environ["TOOL_RESULT_OFFLOAD_CHARS"], os.environ["TOOL_RESULT_TTL_SECONDS"]) == ("50000", "0")
        s = load_settings()
        assert (s.tool_result_offload_chars, s.tool_result_ttl_seconds) == (50_000, 0)

    @pytest.mark.parametrize("value", ["lots", "-5", "1.5", "²"])
    def test_rejects_non_numbers(self, dashboard, value):
        from web.config_store import load_config

        r = dashboard.post("/api/config/advanced", headers=ORIGIN, data={"tool_result_offload_chars": value})
        assert "must be a whole number" in r.text
        assert load_config().tool_result_offload_chars == ""

    def test_forms_without_the_fields_keep_them(self, dashboard):
        from web.config_store import load_config

        dashboard.post("/api/config/advanced", headers=ORIGIN, data={"tool_result_offload_chars": "9000"})
        dashboard.post("/api/config/advanced", headers=ORIGIN, data={"context_token_budget": "4096"})
        config = load_config()
        assert (config.tool_result_offload_chars, config.context_token_budget) == ("9000", "4096")

    def test_empty_means_default(self, dashboard):
        import app_config

        dashboard.post("/api/config/advanced", headers=ORIGIN, data={
            "tool_result_offload_chars": "", "tool_result_ttl_seconds": "",
        })
        app_config.inject_config_to_env()
        assert "TOOL_RESULT_OFFLOAD_CHARS" not in os.environ
        assert load_settings().tool_result_offload_chars == 16_000
