"""
End-to-end flows with everything real except Discord, the CDN and the model.

A message goes through ChatCog.on_message → the real Agno workflow
(FetchHistory → LLMChat → ExtractRenderTables → SendResponse) → a reply in
the fake channel. Agent.arun is replaced by a scripted model that records
what it was sent. Setup flows drive the real web dashboard and app_config
before the bot is built from the resulting config.
"""

import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from agno.agent import Agent
from agno.run.base import RunStatus
from starlette.testclient import TestClient

from dango.utils.runtime_config import RuntimeConfig

from .fake_discord import (
    FakeBot, FakeCDN, FakeChannel, FakeDMChannel, FakeGuild, FakeInteraction, FakeMember, FakeUser,
)

REPO = Path(__file__).resolve().parent.parent
BOT_ID = 900
BASE_ENV = {"FAST_MODEL": "google:gemini-2.5-flash", "FAST_API_KEY": "fast-key"}
LOCAL = "http://localhost:17860"
ORIGIN = {"origin": LOCAL}

_CONFIG_PREFIXES = (
    "FAST_", "DEEP_", "GEMINI_", "ENABLE_", "WORKSPACE_", "SKILLS_", "BRAVE_", "MESSAGE_BATCH_",
    "CUSTOM_APIS", "SQL_DATABASES", "CONTEXT_TOKEN_BUDGET", "AUTO_ROUTE", "FALLBACK_ON_ERROR",
    "DISCORD_",
)


# ── Harness ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp working dir (config/, data/, temp/ are relative), clean env, no custom tools."""
    (tmp_path / "web").mkdir()
    os.symlink(REPO / "web" / "templates", tmp_path / "web" / "templates")
    monkeypatch.chdir(tmp_path)

    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(_CONFIG_PREFIXES) or key.endswith(("_API_KEY", "_TOKEN")):
            del os.environ[key]
    os.environ["AGNO_TELEMETRY"] = "false"

    from dango.extensions import loader, registry
    monkeypatch.setattr(loader, "_loaded", True)
    monkeypatch.setattr(registry, "_REGISTRY", [])
    monkeypatch.setattr(registry, "_RAW_TOOLS", [])
    yield tmp_path
    os.environ.clear()
    os.environ.update(saved)


class ScriptedModel:
    """Stands in for every model call: replays queued outcomes, records inputs."""

    def __init__(self):
        self.calls = []
        self.queue = []

    def reply(self, *texts):
        self.queue += [SimpleNamespace(status=RunStatus.completed, content=t) for t in texts]

    def fail(self, detail):
        self.queue.append(SimpleNamespace(status=RunStatus.error, content=detail))

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def model(monkeypatch):
    scripted = ScriptedModel()

    async def arun(agent, input=None, session_state=None, **kwargs):
        scripted.calls.append(SimpleNamespace(agent=agent, input=input, session_state=session_state))
        if not scripted.queue:
            raise AssertionError("the model was called but no reply was scripted")
        return scripted.queue.pop(0)

    monkeypatch.setattr(Agent, "arun", arun)
    return scripted


@pytest.fixture
def cdn(monkeypatch):
    store = FakeCDN()

    class Response:
        def __init__(self, body):
            self.status = 200 if body is not None else 404
            self._body = body or b""

        async def read(self):
            return self._body

        async def text(self):
            return self._body.decode()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url):
            return Response(store.files.get(str(url)))

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    return store


def _fresh_bot_modules():
    """Re-import the bot so it reads the current env (settings, batching flag)."""
    for name in list(sys.modules):
        if name.startswith(("dango.agent", "dango.steps", "dango.commands")) or name == "dango.workflow":
            del sys.modules[name]
    workflow = importlib.import_module("dango.workflow")
    chat = importlib.import_module("dango.commands.chat_commands")
    return workflow, chat


class World:
    """One guild (#general, #random), a DM channel, and a running ChatCog."""

    def __init__(self, cdn: FakeCDN, model: ScriptedModel, chat_prompt: str):
        self.model = model
        self.bot_user = FakeUser(BOT_ID, "Dango", bot=True)
        self.bot = FakeBot(self.bot_user)
        self.guild = FakeGuild(500, "Dango HQ")
        self.guild.add_member(FakeMember(BOT_ID, "Dango", bot=True))
        self.alice = self.guild.add_member(
            FakeMember(1, "Alice", roles=["Mods"], permissions=["administrator", "send_messages"])
        )
        self.bob = self.guild.add_member(FakeMember(2, "Bob", permissions=["send_messages"]))
        self.general = self.bot.add_channel(
            FakeChannel(222, name="general", guild=self.guild, bot_user=self.bot_user, cdn=cdn)
        )
        self.random = self.bot.add_channel(
            FakeChannel(333, name="random", guild=self.guild, bot_user=self.bot_user, cdn=cdn)
        )
        self.dm = self.bot.add_channel(FakeDMChannel(444, bot_user=self.bot_user, cdn=cdn))
        self.cdn = cdn

        workflow, chat = _fresh_bot_modules()
        self.chat_module = chat
        self.runtime = RuntimeConfig("config/runtime.yml")
        self.cog = chat.ChatCog(self.bot, workflow.create_discord_workflow(), chat_prompt, self.runtime)

    def say(self, author, text, *, channel=None, mention_bot=False, mentions=(), reply_to=None):
        """Post a message as `author`, let the bot handle it, return what the bot sent."""
        channel = channel or self.general
        mentions = [*mentions, *([self.bot_user] if mention_bot else [])]
        content = f"{self.bot_user.mention} {text}" if mention_bot else text
        message = channel.post(author, content, mentions=mentions, reference=reply_to)
        before = len(channel.messages)
        asyncio.run(self.cog.on_message(message))
        return channel.messages[before:]

    def slash(self, command, user, *, channel=None, **options):
        """Run a slash command; return (bot posts, ephemeral replies)."""
        channel = channel or self.general
        interaction = FakeInteraction(user, channel)
        before = len(channel.messages)
        callback = getattr(self.chat_module.ChatCog, command).callback
        asyncio.run(callback(self.cog, interaction, **options))
        return channel.messages[before:], interaction.ephemeral


@pytest.fixture
def make_world(cdn, model):
    def make(env=None, chat_prompt="You are Dango.", *, use_current_env=False):
        if not use_current_env:
            os.environ.update({**BASE_ENV, **(env or {})})
        return World(cdn, model, chat_prompt)
    return make


def _turns(call):
    return [(m.role, m.content) for m in call.input]


def _bump_mtime(path="config/runtime.yml"):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


# ── Who gets an answer ────────────────────────────────────────────────────────

class TestWhoGetsAnAnswer:
    def test_mention_gets_a_threaded_reply(self, make_world):
        w = make_world()
        w.model.reply("Hi Alice! 🍡")
        sent = w.say(w.alice, "what's up?", mention_bot=True)

        assert [m.content for m in sent] == ["Hi Alice! 🍡"]
        assert sent[0].author is w.bot_user
        assert sent[0].replied_to.content == "<@900> what's up?"
        call = w.model.last
        assert _turns(call) == [("user", "Alice: @Dango what's up?")]
        assert call.agent.model.id == "gemini-2.5-flash"
        assert call.session_state["author_permissions"] == ["administrator", "send_messages"]
        assert call.agent.instructions(session_state=call.session_state).startswith("You are Dango.")

    def test_channel_rules(self, make_world):
        w = make_world()
        assert w.say(w.alice, "anyone here?") == []
        assert w.model.calls == []

        # Allowed from elsewhere (e.g. the dashboard): picked up on the next message.
        RuntimeConfig("config/runtime.yml").add_channel(222)
        _bump_mtime()
        w.model.reply("Hello!")
        assert [m.content for m in w.say(w.alice, "anyone here?")] == ["Hello!"]
        assert w.say(w.alice, "and here?", channel=w.random) == []

    def test_dm_rules(self, make_world):
        w = make_world()
        alice_dm = FakeUser(1, "Alice")
        assert w.say(alice_dm, "psst", channel=w.dm) == []

        w.runtime.add_user(1, "alice")
        w.model.reply("Hi in DM")
        sent = w.say(alice_dm, "psst", channel=w.dm)
        assert [m.content for m in sent] == ["Hi in DM"]
        state = w.model.last.session_state
        assert (state["channel_name"], state["guild_id"], state["author_permissions"]) == ("DM", None, [])

    def test_bot_ignores_its_own_messages(self, make_world):
        w = make_world()
        w.runtime.add_channel(222)
        assert w.say(w.bot_user, "I said this") == []
        assert w.model.calls == []


# ── What the model sees ───────────────────────────────────────────────────────

class TestConversation:
    def test_history_becomes_the_conversation(self, make_world):
        w = make_world()
        w.general.post(w.bob, "old topic, should be forgotten")
        w.general.post(w.bot_user, "[new chat] ---")
        w.general.post(w.bob, "I like cats")
        w.general.post(w.bot_user, "Cats are great")
        w.general.post(w.bob, "and dogs")
        w.general.post(w.bob, "especially corgis")
        w.model.reply("Both are lovely.")

        w.say(w.alice, "what do you think?", mention_bot=True)

        call = w.model.last
        assert _turns(call) == [
            ("user", "Bob: I like cats"),
            ("assistant", "Cats are great"),
            ("user", "Bob: and dogs\nespecially corgis"),
            ("user", "Alice: @Dango what do you think?"),
        ]
        prompt = call.agent.instructions(session_state=call.session_state)
        assert "Current participants:" in prompt and "Alice" in prompt and "Bob" in prompt

    def test_reply_context_is_included(self, make_world):
        w = make_world()
        meeting = w.general.post(w.bob, "the meeting is at 3pm")
        w.model.reply("At 3pm.")
        w.say(w.alice, "when again?", mention_bot=True, reply_to=meeting)
        assert _turns(w.model.last)[-1] == ("user", 'Alice: Bob said "the meeting is at 3pm" @Dango when again?')

    def test_mentions_in_history_are_names(self, make_world):
        w = make_world()
        w.general.post(w.bob, f"{w.alice.mention} you around?", mentions=[w.alice])
        w.model.reply("ok")
        w.say(w.alice, "yes", mention_bot=True)
        assert _turns(w.model.last)[0] == ("user", "Bob: @Alice you around?")


# ── What the bot sends back ───────────────────────────────────────────────────

TABLE = "| Name | Qty |\n|---|---|\n| Mochi | 3 |\n| Dango | 5 |"


class TestReplies:
    def test_long_reply_is_split_into_discord_sized_messages(self, make_world):
        w = make_world()
        paragraphs = [f"Paragraph {i}: " + "word " * 150 for i in range(8)]
        w.model.reply("\n\n".join(paragraphs))
        sent = w.say(w.alice, "tell me a lot", mention_bot=True)

        assert len(sent) >= 3
        assert all(len(m.content) <= 2000 for m in sent)
        assert all(m.replied_to is not None for m in sent)
        joined = " ".join(m.content for m in sent)
        assert all(f"Paragraph {i}:" in joined for i in range(8))

    def test_table_is_rendered_as_an_image_and_restored_in_history(self, make_world):
        w = make_world()
        w.model.reply(f"Here you go:\n\n{TABLE}\n\nEnjoy!")
        sent = w.say(w.alice, "inventory?", mention_bot=True)

        (reply,) = sent
        question_id = reply.replied_to.id
        assert reply.content == (
            f"Here you go:\n\n> `[dango_replaced_table_{question_id}_1_as_image]`\n\nEnjoy!"
        )
        files = {a.filename: w.cdn.files[a.url] for a in reply.attachments}
        assert set(files) == {"table_1.png", f"dango_replaced_table_{question_id}_1.md"}
        assert files["table_1.png"].startswith(b"\x89PNG")
        assert files[f"dango_replaced_table_{question_id}_1.md"].decode() == TABLE
        assert list(Path("temp").iterdir()) == []  # temp table files cleaned up

        # Next turn: the model sees the table itself, not the placeholder.
        w.model.reply("You have 8 items.")
        w.say(w.alice, "how many in total?", mention_bot=True)
        assert ("assistant", f"Here you go:\n\n{TABLE}\n\nEnjoy!") in _turns(w.model.last)

    def test_model_failure_is_reported_and_kept_out_of_history(self, make_world):
        w = make_world()
        w.model.fail("503 UNAVAILABLE. The model is overloaded.")
        (sent,) = w.say(w.alice, "hello?", mention_bot=True)
        assert sent.content.startswith(
            "> [dango-sysinfo]\n> ⚠️ The model is currently overloaded (google:gemini-2.5-flash unavailable)."
        )
        assert sent.replied_to is not None

        # The error note is not part of the conversation the model sees next.
        w.model.reply("I'm back.")
        w.say(w.alice, "hello again?", mention_bot=True)
        assert _turns(w.model.last) == [
            ("user", "Alice: @Dango hello?"),
            ("user", "Alice: @Dango hello again?"),
        ]


# ── Slash commands through the whole pipeline ─────────────────────────────────

class TestDeepCommand:
    def test_deep_round_trip(self, make_world):
        w = make_world({"DEEP_MODEL": "google:gemini-2.5-pro"})
        w.model.reply("A monad is a monoid in the category of endofunctors.")
        posted, ephemeral = w.slash("deep_command", w.alice, message="explain monads", image=None)

        echo, answer = posted
        assert echo.content == "> **[deep]** **Alice:** explain monads"
        assert [a.filename for a in echo.attachments] == ["dango_deep_1.json"]
        assert answer.replied_to is echo
        assert answer.content == "A monad is a monoid in the category of endofunctors."
        assert ephemeral == ["✅"]
        assert w.model.last.agent.model.id == "gemini-2.5-pro"

        # The bot's echo post comes back as Alice's own turn in later history.
        w.model.reply("You're welcome!")
        w.say(w.alice, "thanks!", mention_bot=True)
        assert _turns(w.model.last) == [
            ("user", "Alice: explain monads"),
            ("assistant", "A monad is a monoid in the category of endofunctors."),
            ("user", "Alice: @Dango thanks!"),
        ]
        assert w.model.last.agent.model.id == "gemini-2.5-flash"

    def test_deep_without_deep_model(self, make_world):
        w = make_world()
        posted, ephemeral = w.slash("deep_command", w.alice, message="hi", image=None)
        assert posted == []
        assert ephemeral == ["❌ `DEEP_MODEL` is not configured — `/deep` is unavailable."]
        assert w.model.calls == []


# ── Setup: dashboard → config.yaml → env → running bot ────────────────────────

COMPLEX = "Why does quicksort degrade to O(n^2) on sorted input? Explain step by step and compare it with mergesort."


@pytest.fixture
def dashboard():
    from web import main as web_main

    return TestClient(web_main.app, base_url=LOCAL)


class TestSetupFlow:
    def test_setup_wizard_to_first_replies(self, dashboard, make_world):
        import app_config

        # First visit goes to the wizard; finishing it saves data/config.yaml.
        assert dashboard.get("/", follow_redirects=False).headers["location"] == "/setup"
        r = dashboard.post("/setup/complete", headers=ORIGIN, follow_redirects=False, data={
            "discord_token": "discord-token",
            "fast_api_key": "gemini-key",
            "fast_model": "google:gemini-2.5-flash",
            "chat_sys_prompt": "You are Mochi, a cheerful helper.",
        })
        assert r.headers["location"] == "/overview"
        assert dashboard.get("/", follow_redirects=False).headers["location"] == "/overview"

        # Further settings from the dashboard tabs.
        dashboard.post("/api/config/models/deep", headers=ORIGIN, data={
            "deep_model": "openai:gpt-4o", "deep_api_key": "openai-key",
        })
        dashboard.post("/api/config/features", headers=ORIGIN, data={
            "auto_route": "on", "fallback_on_error": "on",
            "enable_contextual_system_prompt": "on", "enable_duckduckgo": "on",
        })
        dashboard.post("/api/runtime/channels/add", headers=ORIGIN, data={"channel_id": "222"})

        # Bot startup (main.py): config.yaml → env, then the bot is built from env.
        prompt = app_config.inject_config_to_env()
        assert prompt == "You are Mochi, a cheerful helper."
        assert os.environ["DISCORD_BOT_TOKEN"] == "discord-token"
        w = make_world(chat_prompt=prompt, use_current_env=True)

        # A plain message in the allowed channel goes to the fast model.
        w.model.reply("Mochi here!")
        assert [m.content for m in w.say(w.alice, "hello")] == ["Mochi here!"]
        fast = w.model.last.agent
        assert (fast.model.id, fast.model.api_key) == ("gemini-2.5-flash", "gemini-key")
        assert [t.name for t in fast.tools] == ["websearch"]
        assert fast.instructions(session_state=w.model.last.session_state).startswith(prompt)
        assert os.environ["OPENAI_API_KEY"] == "openai-key"

        # A complex question is auto-routed to the deep model.
        w.model.reply("Here is why...")
        w.say(w.alice, COMPLEX)
        assert w.model.last.agent.model.id == "gpt-4o"

        # A failing fast model falls back to the deep one, with a note. ("thanks!"
        # is a closer, so routing keeps it on the fast model despite the history.)
        w.model.fail("503 UNAVAILABLE")
        w.model.reply("You're welcome!")
        sent = w.say(w.alice, "thanks!")
        assert [c.agent.model.id for c in w.model.calls[-2:]] == ["gemini-2.5-flash", "gpt-4o"]
        assert [m.content for m in sent] == [
            "You're welcome!",
            "> [dango-sysinfo]\n> ⚡ google:gemini-2.5-flash failed — response served by openai:gpt-4o.",
        ]

    def test_dashboard_changes_reach_the_running_bot(self, dashboard, make_world):
        w = make_world()
        for author, text in [(w.bob, "one"), (w.bot_user, "two"), (w.bob, "three"), (w.bot_user, "four")]:
            w.general.post(author, text)
        assert w.say(w.alice, "hi") == []  # #general not allowed yet

        dashboard.post("/api/runtime/channels/add", headers=ORIGIN, data={"channel_id": "222"})
        r = dashboard.post("/api/runtime/settings", headers=ORIGIN, data={
            "timezone": "Asia/Tokyo", "discord_activity": "Reading", "history_limit": "3",
        })
        assert "Saved" in r.text
        _bump_mtime()

        w.model.reply("Hello from Tokyo time!")
        assert [m.content for m in w.say(w.alice, "hi")] == ["Hello from Tokyo time!"]
        call = w.model.last
        assert (call.session_state["timezone"], call.session_state["history_limit"]) == ("Asia/Tokyo", 3)
        # 3 messages of history before this one: "three", "four", and Alice's unanswered "hi".
        assert _turns(call) == [
            ("user", "Bob: three"),
            ("assistant", "four"),
            ("user", "Alice: hi"),
            ("user", "Alice: hi"),
        ]
        assert "Timezone: Asia/Tokyo" in call.agent.instructions(session_state=call.session_state)

    def test_invalid_dashboard_settings_never_reach_the_bot(self, dashboard, make_world):
        w = make_world()
        w.runtime.add_channel(222)
        r = dashboard.post("/api/runtime/settings", headers=ORIGIN, data={
            "timezone": "Taipei", "discord_activity": "x", "history_limit": "5",
        })
        assert "Unknown timezone" in r.text

        w.model.reply("still fine")
        assert [m.content for m in w.say(w.alice, "hi")] == ["still fine"]
        assert w.model.last.session_state["timezone"] == "UTC"
