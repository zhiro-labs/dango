"""
Tests for the /deep and /skill slash commands in ChatCog.

Both post the user's message into the channel as the bot (with a JSON
attachment so history can restore it as a user turn), then run the
workflow with a flag that forces the deep model or a skill.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from dango.commands import chat_commands
from dango.commands.chat_commands import ChatCog

BOT_ID = 999


def _iso(value: str):
    return SimpleNamespace(isoformat=lambda: value)


def _interaction(text_guild: bool = True):
    sent = SimpleNamespace(id=5001, created_at=_iso("2026-10-24T08:00:00+00:00"))
    channel = SimpleNamespace(id=222, name="general", send=AsyncMock(return_value=sent))
    user = SimpleNamespace(
        id=111,
        display_name="Alice",
        roles=[SimpleNamespace(name="@everyone"), SimpleNamespace(name="Mods")],
        guild_permissions=[("administrator", True), ("send_messages", True), ("ban_members", False)],
    )
    members = {5: SimpleNamespace(id=5, display_name="Bob")}
    roles = {7: SimpleNamespace(id=7, name="Helpers")}
    guild = SimpleNamespace(id=333, name="Dango HQ", get_member=members.get, get_role=roles.get)
    return SimpleNamespace(
        user=user,
        channel=channel,
        guild=guild if text_guild else None,
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def _image(filename="cat.png", content_type="image/png"):
    return SimpleNamespace(filename=filename, url=f"https://cdn/{filename}", size=1234, content_type=content_type)


@pytest.fixture
def cog(monkeypatch):
    workflow = SimpleNamespace(arun=AsyncMock())
    runtime = SimpleNamespace(history_limit=12, timezone="Asia/Taipei")
    bot = SimpleNamespace(user=SimpleNamespace(id=BOT_ID))
    monkeypatch.setattr(chat_commands, "get_agents", lambda: SimpleNamespace(deep=object()))
    monkeypatch.setattr(chat_commands, "list_skill_names", lambda: ["demo", "release-notes"])
    return ChatCog(bot, workflow, "You are Dango.", runtime)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(bodies={}, fetched=[])

    class FakeResponse:
        def __init__(self, body):
            self.status, self._body = (200, body) if body is not None else (404, b"")

        async def read(self):
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url):
            state.fetched.append(url)
            return FakeResponse(state.bodies.get(url))

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    return state


def deep(cog, interaction, message="hello there", image=None):
    asyncio.run(ChatCog.deep_command.callback(cog, interaction, message=message, image=image))


def skill(cog, interaction, name="demo", message="hello there", image=None):
    asyncio.run(ChatCog.skill_command.callback(cog, interaction, name=name, message=message, image=image))


def _posted(interaction):
    """(content, [(filename, bytes)]) of the message the bot posted."""
    kwargs = interaction.channel.send.await_args.kwargs
    return kwargs["content"], [(f.filename, f.fp.read()) for f in kwargs["files"]]


def _message_data(cog) -> dict:
    return cog.discord_workflow.arun.await_args.kwargs["input"]


# ── /deep ─────────────────────────────────────────────────────────────────────

class TestDeep:
    def test_unavailable_without_deep_model(self, cog, monkeypatch):
        monkeypatch.setattr(chat_commands, "get_agents", lambda: SimpleNamespace(deep=None))
        interaction = _interaction()
        deep(cog, interaction)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ `DEEP_MODEL` is not configured — `/deep` is unavailable.", ephemeral=True
        )
        cog.discord_workflow.arun.assert_not_awaited()

    def test_posts_message_and_runs_workflow(self, cog):
        interaction = _interaction()
        deep(cog, interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        content, files = _posted(interaction)
        assert content == "> **[deep]** **Alice:** hello there"
        assert files == [(
            "dango_deep_111.json",
            json.dumps({"author_name": "Alice", "author_id": 111, "content": "hello there"}).encode(),
        )]

        data = _message_data(cog)
        assert data["_force_deep"] is True
        assert "_force_skill" not in data
        assert {k: data[k] for k in (
            "content", "author_id", "author_name", "channel_id", "channel_name", "message_id",
            "bot_user_id", "guild_id", "guild_name", "created_at", "is_dm", "has_embeds",
            "message_type", "attachments", "embeds",
            "_chat_sys_prompt", "_history_limit", "_timezone",
        )} == {
            "content": "hello there",
            "author_id": 111,
            "author_name": "Alice",
            "channel_id": 222,
            "channel_name": "general",
            "message_id": 5001,  # the bot's post: history is read from before it
            "bot_user_id": BOT_ID,
            "guild_id": 333,
            "guild_name": "Dango HQ",
            "created_at": "2026-10-24T08:00:00+00:00",
            "is_dm": False,
            "has_embeds": False,
            "message_type": "default",
            "attachments": [],
            "embeds": [],
            "_chat_sys_prompt": "You are Dango.",
            "_history_limit": 12,
            "_timezone": "Asia/Taipei",
        }
        assert data["_bot"] is cog.bot
        interaction.followup.send.assert_awaited_once_with("✅", ephemeral=True)

    def test_image_is_reuploaded_and_passed_on(self, cog, http):
        http.bodies = {"https://cdn/cat.png": b"PNG"}
        interaction = _interaction()
        deep(cog, interaction, image=_image())

        _, files = _posted(interaction)
        assert files[1] == ("cat.png", b"PNG")
        assert _message_data(cog)["attachments"] == [
            {"filename": "cat.png", "url": "https://cdn/cat.png", "size": 1234, "content_type": "image/png"}
        ]

    def test_non_image_attachment_is_ignored(self, cog, http):
        interaction = _interaction()
        deep(cog, interaction, image=_image("notes.txt", "text/plain"))

        _, files = _posted(interaction)
        assert [name for name, _ in files] == ["dango_deep_111.json"]
        assert http.fetched == []
        assert _message_data(cog)["attachments"] == []

    def test_failed_download_still_posts(self, cog, http):
        interaction = _interaction()
        deep(cog, interaction, image=_image())  # 404 from the fake CDN

        _, files = _posted(interaction)
        assert [name for name, _ in files] == ["dango_deep_111.json"]
        assert _message_data(cog)["attachments"][0]["filename"] == "cat.png"

    def test_workflow_error_is_reported(self, cog):
        cog.discord_workflow.arun.side_effect = RuntimeError("boom")
        interaction = _interaction()
        deep(cog, interaction)
        interaction.followup.send.assert_awaited_once_with("Failed to process deep model request.", ephemeral=True)


# ── /skill ────────────────────────────────────────────────────────────────────

class TestSkill:
    def test_no_skills(self, cog, monkeypatch):
        monkeypatch.setattr(chat_commands, "list_skill_names", lambda: [])
        interaction = _interaction()
        skill(cog, interaction)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ No skills are available — enable skills and add at least one to use `/skill`.",
            ephemeral=True,
        )
        cog.discord_workflow.arun.assert_not_awaited()

    def test_unknown_skill(self, cog):
        interaction = _interaction()
        skill(cog, interaction, name="nope")
        interaction.response.send_message.assert_awaited_once_with(
            "❌ Unknown skill `nope`. Available: `demo`, `release-notes`", ephemeral=True
        )
        cog.discord_workflow.arun.assert_not_awaited()

    def test_posts_message_and_runs_workflow(self, cog):
        interaction = _interaction()
        skill(cog, interaction, name="release-notes", message="v2 is out")

        content, files = _posted(interaction)
        assert content == "> **[skill: release-notes]** **Alice:** v2 is out"
        assert files == [(
            "dango_skill_111.json",
            json.dumps({"author_name": "Alice", "author_id": 111, "content": "v2 is out"}).encode(),
        )]
        data = _message_data(cog)
        assert data["_force_skill"] == "release-notes"
        assert "_force_deep" not in data
        assert (data["content"], data["message_id"]) == ("v2 is out", 5001)
        interaction.followup.send.assert_awaited_once_with("✅", ephemeral=True)

    def test_workflow_error_is_reported(self, cog):
        cog.discord_workflow.arun.side_effect = RuntimeError("boom")
        interaction = _interaction()
        skill(cog, interaction)
        interaction.followup.send.assert_awaited_once_with("Failed to process skill request.", ephemeral=True)

    def test_autocomplete_is_registered(self):
        assert ChatCog.skill_command.get_parameter("name").autocomplete

    def test_autocomplete(self, cog, monkeypatch):
        names = [f"skill-{i}" for i in range(30)] + ["Demo-Skill"]
        monkeypatch.setattr(chat_commands, "list_skill_names", lambda: names)
        choices = asyncio.run(cog._skill_name_autocomplete(_interaction(), "DEMO"))
        assert [(c.name, c.value) for c in choices] == [("Demo-Skill", "Demo-Skill")]
        assert len(asyncio.run(cog._skill_name_autocomplete(_interaction(), "skill"))) == 25


# ── Same context as plain messages ────────────────────────────────────────────

def _guild_message(author, guild):
    """A plain guild message from `author`, as on_message would receive it."""
    return SimpleNamespace(
        author=author,
        channel=SimpleNamespace(id=222, name="general"),
        guild=guild,
        id=4001,
        clean_content="hello there",
        embeds=[],
        attachments=[],
        stickers=[],
        mentions=[],
        role_mentions=[],
        created_at=_iso("2026-10-24T08:00:00+00:00"),
        type="default",
    )


class TestSameContextAsMessages:
    """Slash turns must give the workflow and custom tools the same context."""

    def test_same_fields_as_a_plain_message(self, cog):
        from dango.commands.chat_commands import _build_message_data

        interaction = _interaction()
        deep(cog, interaction)
        slash = {k for k in _message_data(cog) if not k.startswith("_")}
        plain = set(_build_message_data(_guild_message(interaction.user, interaction.guild), BOT_ID))
        assert slash == plain

    @pytest.mark.parametrize("run", [deep, skill])
    def test_roles_and_permissions_reach_tools(self, cog, run):
        run(cog, _interaction())
        data = _message_data(cog)
        assert data["author_roles"] == ["Mods"]
        assert data["author_permissions"] == ["administrator", "send_messages"]
        assert data["stickers"] == []

    def test_typed_mentions_are_resolved(self, cog):
        interaction = _interaction()
        deep(cog, interaction, message="<@5> meet <@&7> and <@!5>, not <@42>")

        data = _message_data(cog)
        assert data["content"] == "@Bob meet @Helpers and @Bob, not <@42>"
        assert data["mentioned_users"] == [{"id": 5, "name": "Bob"}]
        assert data["mentioned_roles"] == [{"id": 7, "name": "Helpers"}]
        # The bot's post and its JSON keep the text as typed, so Discord renders the mentions.
        content, files = _posted(interaction)
        assert content.endswith("<@5> meet <@&7> and <@!5>, not <@42>")
        assert json.loads(files[0][1])["content"] == "<@5> meet <@&7> and <@!5>, not <@42>"

    def test_dm(self, cog):
        interaction = _interaction(text_guild=False)
        interaction.channel = SimpleNamespace(id=222, send=interaction.channel.send)  # DM channels have no name
        deep(cog, interaction, message="<@5> hi")

        data = _message_data(cog)
        assert (data["channel_name"], data["guild_id"], data["guild_name"]) == ("DM", None, "")
        assert (data["author_roles"], data["author_permissions"]) == ([], [])
        assert (data["content"], data["mentioned_users"]) == ("<@5> hi", [])


def test_webhook_author_in_guild_has_no_roles():
    """Webhook messages have a plain User author (no roles) even in a guild."""
    from dango.commands.chat_commands import _build_message_data

    webhook = SimpleNamespace(id=1, display_name="GitHub")
    data = _build_message_data(_guild_message(webhook, SimpleNamespace(id=333, name="Dango HQ")), BOT_ID)
    assert (data["author_roles"], data["author_permissions"]) == ([], [])
    assert (data["guild_id"], data["channel_name"]) == (333, "general")
