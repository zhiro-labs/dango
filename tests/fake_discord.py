"""
In-memory stand-ins for the parts of discord.py that Dango touches.

Messages live in FakeChannel.messages; anything the bot sends lands there
too, with its files uploaded to a FakeCDN so later history reads can
download them again (table markdown, /deep JSON), exactly like the real
round trip through Discord's CDN.
"""

import itertools
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord

_ids = itertools.count(1_400_000_000_000_000_000)
_EPOCH = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)


def next_id() -> int:
    return next(_ids)


def not_found(what: str = "Unknown Message") -> discord.NotFound:
    return discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), what)


class FakeCDN:
    """Bytes behind attachment URLs; served by the fake aiohttp session."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    def upload(self, filename: str, data: bytes) -> "FakeAttachment":
        url = f"https://cdn.test/{next_id()}/{filename}"
        self.files[url] = data
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FakeAttachment(filename, url, len(data), content_type)


class FakeAttachment:
    def __init__(self, filename: str, url: str, size: int, content_type: str | None):
        self.filename, self.url, self.size, self.content_type = filename, url, size, content_type


class FakeUser:
    """A Discord user outside any guild (DM author, webhook, the bot itself)."""

    def __init__(self, user_id: int, name: str, *, bot: bool = False):
        self.id = user_id
        self.name = self.display_name = name
        self.bot = bot

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def mentioned_in(self, message: "FakeMessage") -> bool:
        return any(m.id == self.id for m in message.mentions)


class FakeMember(FakeUser):
    """A guild member: has roles and guild permissions."""

    def __init__(self, user_id: int, name: str, *, roles=(), permissions=(), bot: bool = False):
        super().__init__(user_id, name, bot=bot)
        self.roles = [SimpleNamespace(name="@everyone"), *(SimpleNamespace(name=r) for r in roles)]
        self.guild_permissions = [(p, True) for p in permissions] + [("ban_members", False)]


class FakeGuild:
    def __init__(self, guild_id: int, name: str):
        self.id, self.name = guild_id, name
        self.members: dict[int, FakeMember] = {}
        self.role_objects: dict[int, SimpleNamespace] = {}

    def add_member(self, member: FakeMember) -> FakeMember:
        self.members[member.id] = member
        return member

    def add_role(self, role_id: int, name: str) -> SimpleNamespace:
        self.role_objects[role_id] = SimpleNamespace(id=role_id, name=name, mention=f"<@&{role_id}>")
        return self.role_objects[role_id]

    def get_member(self, user_id: int):
        return self.members.get(user_id)

    async def fetch_member(self, user_id: int):
        if user_id not in self.members:
            raise not_found("Unknown Member")
        return self.members[user_id]

    def get_role(self, role_id: int):
        return self.role_objects.get(role_id)


class FakeMessage:
    def __init__(self, channel, author, content="", *, attachments=(), mentions=(),
                 role_mentions=(), reference=None):
        self.id = next_id()
        self.channel = channel
        self.guild = channel.guild
        self.author = author
        self.content = content
        self.attachments = list(attachments)
        self.stickers = []
        self.embeds = []
        self.mentions = list(mentions)
        self.role_mentions = list(role_mentions)
        self.reference = SimpleNamespace(message_id=reference.id) if reference else None
        self.created_at = _EPOCH + timedelta(seconds=len(channel.messages))
        self.type = discord.MessageType.default

    @property
    def clean_content(self) -> str:
        """Mention tokens shown as names, like discord.py's clean_content."""
        def user(m):
            uid = int(m.group(1))
            found = next((u for u in self.mentions if u.id == uid), None)
            return f"@{found.display_name}" if found else m.group(0)

        def role(m):
            found = next((r for r in self.role_mentions if r.id == int(m.group(1))), None)
            return f"@{found.name}" if found else m.group(0)

        return re.sub(r"<@&(\d+)>", role, re.sub(r"<@!?(\d+)>", user, self.content))

    async def reply(self, content=None, files=None):
        return await self.channel.send(content=content, files=files, reference=self)


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeChannel:
    """A text channel (guild set) or the base of a DM channel (guild None)."""

    def __init__(self, channel_id: int, *, name: str | None, guild: FakeGuild | None, bot_user: FakeUser, cdn: FakeCDN):
        self.id = channel_id
        if name is not None:
            self.name = name
        if not isinstance(self, discord.DMChannel):  # DMChannel.guild is a read-only None
            self.guild = guild
        self.bot_user = bot_user
        self.cdn = cdn
        self.messages: list[FakeMessage] = []

    # ── Test helpers ──────────────────────────────────────────────────────────

    def post(self, author, content="", **kwargs) -> FakeMessage:
        """Put a message in the channel (what a user typing would do)."""
        message = FakeMessage(self, author, content, **kwargs)
        self.messages.append(message)
        return message

    # ── discord.py API used by Dango ──────────────────────────────────────────

    async def send(self, content=None, files=None, reference=None) -> FakeMessage:
        attachments = [self.cdn.upload(f.filename, f.fp.read()) for f in files or []]
        message = FakeMessage(self, self.bot_user, content or "", attachments=attachments, reference=reference)
        message.replied_to = reference
        self.messages.append(message)
        return message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        for message in self.messages:
            if message.id == message_id:
                return message
        raise not_found()

    async def history(self, limit=None, before=None, oldest_first=False):
        older = [m for m in self.messages if before is None or m.id < before.id]
        older = older if oldest_first else list(reversed(older))
        for message in older[:limit]:
            yield message

    def typing(self) -> _Typing:
        return _Typing()


class FakeDMChannel(FakeChannel, discord.DMChannel):
    """A DM: no name, no guild, and isinstance(..., discord.DMChannel) holds."""

    def __init__(self, channel_id: int, *, bot_user: FakeUser, cdn: FakeCDN):
        super().__init__(channel_id, name=None, guild=None, bot_user=bot_user, cdn=cdn)


class FakeBot:
    def __init__(self, user: FakeUser):
        self.user = user
        self.channels: dict[int, FakeChannel] = {}

    def add_channel(self, channel: FakeChannel) -> FakeChannel:
        self.channels[channel.id] = channel
        return channel

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        raise not_found("Unknown Channel")


class FakeInteraction:
    """A slash-command invocation by `user` in `channel`."""

    def __init__(self, user, channel: FakeChannel):
        self.user = user
        self.channel = channel
        self.guild = channel.guild
        self.ephemeral: list[str] = []

        async def respond(content=None, ephemeral=False, **kwargs):
            self.ephemeral.append(content)

        async def defer(ephemeral=False):
            pass

        self.response = SimpleNamespace(send_message=respond, defer=defer)
        self.followup = SimpleNamespace(send=respond)
