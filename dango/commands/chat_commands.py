"""Chat-related Discord Cog"""

import asyncio
import io
import json
import os
import re
import time
from datetime import datetime
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..agent import get_agents, list_skill_names
from ..utils.config_utils import env_onoff_to_bool
from ..utils.discord_helpers import ROLE_MENTION_RE, USER_MENTION_RE, format_reply_context


# ── Message batching ──────────────────────────────────────────────────────────
# When on, rapid consecutive messages from the same author in the same channel
# are coalesced into a single workflow run (Discord-style message grouping).
# A burst opens on a qualifying message and, while open, folds in every later
# message from that author. Each new message resets the window (sliding
# debounce); MAX_WAIT caps how long a single burst can be held.
ENABLE_MESSAGE_BATCHING = env_onoff_to_bool(os.getenv("ENABLE_MESSAGE_BATCHING"))


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"⚠️ [config] {name}={raw!r} is not a number — using default {default}")
        return default


MESSAGE_BATCH_WINDOW = _env_float("MESSAGE_BATCH_WINDOW", 5.0)
MESSAGE_BATCH_MAX_WAIT = _env_float("MESSAGE_BATCH_MAX_WAIT", 15.0)


def _embed_dicts(message: discord.Message) -> list[dict]:
    embeds = []
    if message.embeds:
        for embed in message.embeds:
            try:
                embeds.append(embed.to_dict())
            except Exception as e:
                print(f"⚠️ [_build_message_data] Error processing embed: {e}")
    return embeds


def _attachment_dict(a: discord.Attachment) -> dict:
    return {
        "filename": str(a.filename),
        "url": str(a.url),
        "size": int(a.size),
        "content_type": str(a.content_type) if a.content_type else "",
    }


def _attachment_dicts(message: discord.Message) -> list[dict]:
    return [_attachment_dict(a) for a in message.attachments] if message.attachments else []


def _sticker_dicts(message: discord.Message) -> list[dict]:
    # Stickers are separate from attachments in Discord. Community stickers
    # are PNG/APNG/GIF (viewable); Discord's default packs are Lottie (vector
    # JSON, name only). call_agent downloads the image formats for the model.
    return [
        {
            "name": str(s.name),
            "url": str(s.url),
            "format": s.format.name if s.format else "",
        }
        for s in message.stickers
    ] if message.stickers else []


# ── message_data ──────────────────────────────────────────────────────────────
# Every entry point (plain messages, /deep, /skill) builds the same shape, so
# the workflow and custom tools (via Ctx) see the same context either way.

def _author_fields(author, guild) -> dict[str, Any]:
    """Who sent it. Roles and permissions exist only for guild members
    (webhook authors and DM users have neither)."""
    roles: list[str] = []
    permissions: list[str] = []
    if guild is not None and hasattr(author, "guild_permissions"):
        roles = [r.name for r in author.roles if r.name != "@everyone"]
        # guild_permissions is a Permissions object; iterating yields (name, value).
        permissions = [name for name, value in author.guild_permissions if value]
    return {
        "author_id": int(author.id),
        "author_name": str(author.display_name),
        "author_roles": roles,
        "author_permissions": permissions,
    }


def _channel_fields(channel, guild) -> dict[str, Any]:
    name = getattr(channel, "name", None)
    return {
        "channel_id": int(channel.id),
        "channel_name": str(name) if name else ("DM" if guild is None else ""),
        "guild_id": int(guild.id) if guild else None,
        "guild_name": str(guild.name) if guild else "",
        "is_dm": isinstance(channel, discord.DMChannel),
    }


def _build_message_data(message: discord.Message, bot_user_id: int) -> dict[str, Any]:
    embeds = _embed_dicts(message)
    return {
        "content": str(message.clean_content) if message.clean_content else "",
        "embeds": embeds,
        **_author_fields(message.author, message.guild),
        # Precise IDs for members/roles the message tagged, so tools don't have
        # to fuzzy-match names. role_mentions is empty outside guilds.
        "mentioned_users": [
            {"id": int(m.id), "name": str(m.display_name)} for m in message.mentions
        ],
        "mentioned_roles": [
            {"id": int(r.id), "name": str(r.name)} for r in message.role_mentions
        ],
        **_channel_fields(message.channel, message.guild),
        "message_id": int(message.id),
        "bot_user_id": int(bot_user_id),
        "timestamp": datetime.now().isoformat(),
        "created_at": message.created_at.isoformat(),
        "has_embeds": len(embeds) > 0,
        "message_type": str(message.type),
        "attachments": _attachment_dicts(message),
        "stickers": _sticker_dicts(message),
    }


def _typed_mentions(text: str, guild) -> tuple[str, list[dict], list[dict]]:
    """Resolve <@id> / <@&id> tokens typed into a slash-command option.

    Slash commands get raw text, not a Message, so this stands in for
    clean_content / mentions / role_mentions. Tokens the guild cache cannot
    resolve are left as typed.
    """
    users: list[dict] = []
    roles: list[dict] = []
    if guild is None:
        return text, users, roles

    def user(match: re.Match) -> str:
        member = guild.get_member(int(match.group(1)))
        if member is None:
            return match.group(0)
        entry = {"id": int(member.id), "name": str(member.display_name)}
        if entry not in users:
            users.append(entry)
        return f"@{member.display_name}"

    def role(match: re.Match) -> str:
        found = guild.get_role(int(match.group(1)))
        if found is None:
            return match.group(0)
        entry = {"id": int(found.id), "name": str(found.name)}
        if entry not in roles:
            roles.append(entry)
        return f"@{found.name}"

    text = USER_MENTION_RE.sub(user, text)
    text = ROLE_MENTION_RE.sub(role, text)
    return text, users, roles


def _is_image(attachment: discord.Attachment | None) -> bool:
    return bool(attachment and attachment.content_type and attachment.content_type.startswith("image/"))


def _build_slash_message_data(
    interaction: discord.Interaction,
    sent: discord.Message,
    text: str,
    image: discord.Attachment | None,
    bot_user_id: int,
) -> dict[str, Any]:
    """message_data for a slash command whose text the bot posted as `sent`.

    message_id is the bot's post, so history is read from before it.
    """
    content, mentioned_users, mentioned_roles = _typed_mentions(text, interaction.guild)
    return {
        "content": content,
        "embeds": [],
        **_author_fields(interaction.user, interaction.guild),
        "mentioned_users": mentioned_users,
        "mentioned_roles": mentioned_roles,
        **_channel_fields(interaction.channel, interaction.guild),
        "message_id": int(sent.id),
        "bot_user_id": int(bot_user_id),
        "timestamp": datetime.now().isoformat(),
        "created_at": sent.created_at.isoformat(),
        "has_embeds": False,
        "message_type": "default",
        "attachments": [_attachment_dict(image)] if _is_image(image) else [],
        "stickers": [],
    }


async def _reupload(image: discord.Attachment, log_tag: str) -> discord.File | None:
    """Download an attachment so the bot can post it again; None on failure."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image.url) as resp:
                if resp.status == 200:
                    return discord.File(io.BytesIO(await resp.read()), filename=image.filename)
    except Exception as e:
        print(f"⚠️ [{log_tag}] Failed to re-upload image: {e}")
    return None


def _merge_burst_messages(
    messages: list[discord.Message], bot_user_id: int
) -> dict[str, Any]:
    """Combine a burst of consecutive messages from one author into one
    message_data.

    The first message is the carrier — its id/timestamp/reply anchor are used so
    fetch_history reads the channel *before* the whole burst (no duplication).
    Later messages contribute their text, attachments and stickers.
    """
    data = _build_message_data(messages[0], bot_user_id)
    if len(messages) == 1:
        return data

    contents = [data["content"]] if data["content"] else []
    for m in messages[1:]:
        extra = str(m.clean_content) if m.clean_content else ""
        if extra:
            contents.append(extra)
        data["attachments"].extend(_attachment_dicts(m))
        data["stickers"].extend(_sticker_dicts(m))
        data["embeds"].extend(_embed_dicts(m))
    data["content"] = "\n".join(contents)
    data["has_embeds"] = len(data["embeds"]) > 0
    return data


class ChatCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        discord_workflow,
        chat_system_prompt: str,
        runtime_config,
    ):
        self.bot = bot
        self.discord_workflow = discord_workflow
        self.chat_system_prompt = chat_system_prompt
        self.runtime_config = runtime_config
        # Open message bursts, keyed by channel_id. Each channel holds at most one
        # active burst, owned by whoever opened it; a different speaker flushes it.
        # Only used when ENABLE_MESSAGE_BATCHING is on.
        self._bursts: dict[int, dict] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        print(
            f"📨 [on_message] Received message from {message.author.display_name} in "
            f"#{message.channel.name if hasattr(message.channel, 'name') else 'DM'}"
        )

        if message.author == self.bot.user:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_allowed_dm_user = message.author.id in self.runtime_config.allowed_users
        is_in_allowed_channel = message.channel.id in self.runtime_config.allowed_channels
        is_mentioned = self.bot.user.mentioned_in(message)

        should_respond = (is_dm and is_allowed_dm_user) or (
            not is_dm and (is_mentioned or is_in_allowed_channel)
        )

        if not ENABLE_MESSAGE_BATCHING:
            if not should_respond:
                return
            print("✅ [on_message] Processing message...")
            await self._run_workflow_for([message])
            return

        # Batching on. Each channel holds at most one active burst, owned by the
        # author who opened it.
        key = message.channel.id
        burst = self._bursts.get(key)

        if burst is not None:
            if message.author.id == burst["owner_id"]:
                # The owner keeps the floor: fold this in and slide the window.
                # Later messages are folded even without a mention.
                print(f"➕ [on_message] Folding message into {message.author.display_name}'s burst")
                burst["messages"].append(message)
                burst["dirty"] = True
                return
            if should_respond:
                # Another user the bot would answer jumped in: send the owner's
                # pending reply now, then let the newcomer take the floor below.
                self._flush_burst(key)
            else:
                # Idle chatter from someone else — don't disturb the open burst.
                return

        if not should_respond:
            return
        self._open_burst(key, message)

    def _open_burst(self, key: int, message: discord.Message) -> None:
        print(
            f"⏳ [on_message] Opening burst for {message.author.display_name} "
            f"(window {MESSAGE_BATCH_WINDOW}s, max {MESSAGE_BATCH_MAX_WAIT}s)"
        )
        burst = {
            "owner_id": message.author.id,
            "messages": [message],
            "first_ts": time.monotonic(),
            "dirty": False,
        }
        self._bursts[key] = burst
        burst["task"] = asyncio.create_task(self._debounce_burst(key))

    def _flush_burst(self, key: int) -> None:
        """Fire an open burst immediately, e.g. when another user takes the floor.

        Cancelling the debounce task and popping the burst here is race-free: the
        pop is the atomic commit point and _debounce_burst also pops before firing,
        so whichever runs first owns the burst and the other no-ops.
        """
        burst = self._bursts.pop(key, None)
        if burst is None:
            return
        task = burst.get("task")
        if task is not None:
            task.cancel()
        if burst["messages"]:
            print(f"⚡ [on_message] Flushing burst early ({len(burst['messages'])} msg) — another user spoke")
            asyncio.create_task(self._run_workflow_for(burst["messages"]))

    async def _debounce_burst(self, key: int) -> None:
        """Wait for the author to stop sending, then fire the burst once.

        Sliding window: each new message sets ``dirty`` so we sleep again, capped
        by MESSAGE_BATCH_MAX_WAIT measured from the first message.
        """
        burst = self._bursts.get(key)
        if burst is None:
            return
        while True:
            burst["dirty"] = False
            elapsed = time.monotonic() - burst["first_ts"]
            remaining = min(MESSAGE_BATCH_WINDOW, MESSAGE_BATCH_MAX_WAIT - elapsed)
            if remaining <= 0:
                break
            await asyncio.sleep(remaining)
            if not burst["dirty"]:
                break

        burst = self._bursts.pop(key, None)
        if not burst or not burst["messages"]:
            return
        count = len(burst["messages"])
        if count > 1:
            print(f"📦 [on_message] Firing burst: {count} messages merged into one")
        await self._run_workflow_for(burst["messages"])

    async def _run_workflow_for(self, messages: list[discord.Message]) -> None:
        """Build merged message_data from a burst and run the workflow once."""
        carrier = messages[0]
        async with carrier.channel.typing():
            try:
                message_data = _merge_burst_messages(messages, self.bot.user.id)

                if carrier.reference and carrier.reference.message_id:
                    try:
                        ref_msg = await carrier.channel.fetch_message(carrier.reference.message_id)
                        if ref_msg.content:
                            message_data["content"] = format_reply_context(
                                current_author=message_data["author_name"],
                                ref_author=ref_msg.author.display_name,
                                ref_content=ref_msg.content,
                                current_content=message_data["content"],
                            )
                            print(f"↩️ [on_message] Reply context injected from {ref_msg.author.display_name}")
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                        print(f"⚠️ [on_message] Could not fetch reference message: {e}")

                await self.discord_workflow.arun(input=self._with_runtime_context(message_data))
                print("✅ [on_message] Workflow completed successfully")

            except Exception as e:
                print(f"❌ [on_message] Error processing message: {e}")
                import traceback
                traceback.print_exc()
                try:
                    await carrier.channel.send(
                        f"Sorry, an error occurred while processing your message. Error: {e}"
                    )
                except Exception as send_error:
                    print(f"❌ [on_message] Failed to send error message: {send_error}")

    def _with_runtime_context(self, message_data: dict[str, Any]) -> dict[str, Any]:
        """Add the bot and current runtime settings the workflow steps need."""
        message_data["_bot"] = self.bot
        message_data["_chat_sys_prompt"] = self.chat_system_prompt
        message_data["_history_limit"] = self.runtime_config.history_limit
        message_data["_timezone"] = self.runtime_config.timezone
        return message_data

    async def _run_slash_turn(
        self,
        interaction: discord.Interaction,
        text: str,
        image: discord.Attachment | None,
        *,
        kind: str,
        label: str,
        flags: dict[str, Any],
        failure: str,
    ) -> None:
        """Post a slash command's text as the bot, then answer it like a message.

        Slash-command input is invisible to the channel, so the bot posts it
        ("> **[label]** **Author:** text") with a dango_<kind>_<author id>.json
        attachment; fetch_history uses that file to restore the post as the
        author's own turn in later history.
        """
        try:
            await interaction.response.defer(ephemeral=True)
            author = interaction.user

            info = {"author_name": author.display_name, "author_id": author.id, "content": text}
            files = [
                discord.File(
                    io.BytesIO(json.dumps(info, ensure_ascii=False).encode()),
                    filename=f"dango_{kind}_{author.id}.json",
                )
            ]
            if _is_image(image):
                reupload = await _reupload(image, log_tag=kind)
                if reupload:
                    files.append(reupload)

            sent = await interaction.channel.send(
                content=f"> **[{label}]** **{author.display_name}:** {text}",
                files=files,
            )

            message_data = _build_slash_message_data(interaction, sent, text, image, self.bot.user.id)
            message_data.update(flags)
            await self.discord_workflow.arun(input=self._with_runtime_context(message_data))
            await interaction.followup.send("✅", ephemeral=True)
            print(f"✅ [{kind}] Processed {label} request from {author.display_name}")

        except Exception as e:
            print(f"❌ [{kind}] Error: {e}")
            try:
                await interaction.followup.send(failure, ephemeral=True)
            except Exception:
                pass

    @app_commands.command(
        name="newchat", description="Start a new chat session by sending a marker"
    )
    async def newchat(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message("[new chat] ---", ephemeral=False)
            print(
                f"✅ [newchat] New chat marker sent in {interaction.channel.name if hasattr(interaction.channel, 'name') else 'DM'}"
            )
        except Exception as e:
            print(f"❌ [newchat] Error sending new chat marker: {e}")
            await interaction.response.send_message(
                "Failed to send new chat marker.", ephemeral=True
            )

    @app_commands.command(
        name="deep",
        description="Send a message and force the deep model to respond",
    )
    @app_commands.describe(
        message="Your message for the deep model",
        image="Optional image attachment",
    )
    async def deep_command(
        self,
        interaction: discord.Interaction,
        message: str,
        image: discord.Attachment = None,
    ):
        if get_agents().deep is None:
            await interaction.response.send_message(
                "❌ `DEEP_MODEL` is not configured — `/deep` is unavailable.",
                ephemeral=True,
            )
            return
        await self._run_slash_turn(
            interaction, message, image,
            kind="deep", label="deep", flags={"_force_deep": True},
            failure="Failed to process deep model request.",
        )

    @app_commands.command(
        name="skill",
        description="Send a message and force a specific skill to be applied",
    )
    @app_commands.describe(
        name="The skill to apply",
        message="Your message",
        image="Optional image attachment",
    )
    async def skill_command(
        self,
        interaction: discord.Interaction,
        name: str,
        message: str,
        image: discord.Attachment = None,
    ):
        available = list_skill_names()
        if not available:
            await interaction.response.send_message(
                "❌ No skills are available — enable skills and add at least one "
                "to use `/skill`.",
                ephemeral=True,
            )
            return
        if name not in available:
            await interaction.response.send_message(
                f"❌ Unknown skill `{name}`. Available: "
                + ", ".join(f"`{n}`" for n in available),
                ephemeral=True,
            )
            return
        await self._run_slash_turn(
            interaction, message, image,
            kind="skill", label=f"skill: {name}", flags={"_force_skill": name},
            failure="Failed to process skill request.",
        )

    @skill_command.autocomplete("name")
    async def _skill_name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cur = current.lower()
        return [
            app_commands.Choice(name=n, value=n)
            for n in list_skill_names()
            if cur in n.lower()
        ][:25]
