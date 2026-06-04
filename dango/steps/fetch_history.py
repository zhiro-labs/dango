"""
Fetch Discord channel history and format it as Agno Messages.
Combines the original FetchDiscordHistory + ProcessMessageHistory nodes.
"""

import json
import re

import aiohttp
import discord
from agno.media import Image
from agno.models.message import Message
from agno.workflow import StepInput, StepOutput

from ..utils.discord_helpers import ROLE_MENTION_RE, SYSINFO_MARKER, USER_MENTION_RE, resolve_mentions


async def fetch_and_process_history(step_input: StepInput) -> StepOutput:
    """Fetch channel history and convert to Agno Message list."""
    message_data = step_input.input
    bot = message_data["_bot"]
    history_limit = message_data["_history_limit"]

    channel_id = message_data["channel_id"]
    message_id = message_data["message_id"]
    bot_user_id = message_data["bot_user_id"]

    print(
        f"🔍 [fetch_and_process_history] Fetching channel {channel_id}, message {message_id}"
    )

    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"❌ [fetch_and_process_history] Cannot access channel: {e}")
            return StepOutput(
                content={
                    "error": True,
                    "error_message": f"Cannot access channel: {e}",
                    "message_data": message_data,
                }
            )

    try:
        if message_id:
            target = await channel.fetch_message(message_id)
            msgs = [
                m
                async for m in channel.history(
                    limit=history_limit, before=target, oldest_first=False
                )
            ]
        else:
            msgs = [
                m
                async for m in channel.history(
                    limit=history_limit, oldest_first=False
                )
            ]

        # Cut history at [new chat] marker
        for i, msg in enumerate(msgs):
            if "[new chat] ---" in msg.content:
                msgs = msgs[:i]
                print(
                    f"✂️ [fetch_and_process_history] Cut history at [new chat] marker, {len(msgs)} messages remain"
                )
                break

        msgs.reverse()
        print(
            f"📜 [fetch_and_process_history] Fetched {len(msgs)} history messages"
        )

        table_content_map = await _extract_table_attachments(msgs)
        deep_map = await _extract_deep_attachments(msgs)
        image_map = await _download_image_attachments(msgs, bot_user_id)
        mention_map = await _build_mention_map(msgs)
        formatted_history, unique_users = _process_messages(
            msgs, bot_user_id, table_content_map, image_map, deep_map, mention_map
        )

        return StepOutput(
            content={
                "formatted_history": formatted_history,
                "unique_users": list(unique_users),
                "mention_map": mention_map,
                "message_data": message_data,
            }
        )

    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        print(f"❌ [fetch_and_process_history] Discord error: {e}")
        return StepOutput(
            content={
                "error": True,
                "error_message": f"Discord error: {e}",
                "message_data": message_data,
            }
        )


async def _extract_table_attachments(msgs: list) -> dict:
    """Download table attachment content from previous bot messages."""
    table_content_map = {}
    for msg in msgs:
        if not msg.attachments:
            continue
        for attachment in msg.attachments:
            if attachment.filename.startswith(
                "dango_replaced_table_"
            ) and attachment.filename.endswith(".md"):
                parts = attachment.filename.replace(".md", "").split("_")
                if len(parts) >= 5 and parts[3].isdigit() and parts[4].isdigit():
                    key = f"{parts[3]}_{parts[4]}"
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    table_content_map[key] = await resp.text()
                    except Exception as e:
                        print(
                            f"❌ [fetch_and_process_history] Failed to download table attachment: {e}"
                        )
    return table_content_map


async def _extract_deep_attachments(msgs: list) -> dict:
    """Download dango_deep_*.json attachments → {message_id: deep_info}.

    deep_info contains: author_name, author_id, content, and optionally
    _images (list[Image]) when an image was re-uploaded alongside the JSON.
    Used by _process_messages to restore /deep slash command messages
    as proper user turns in conversation history.
    """
    deep_map: dict[int, dict] = {}
    async with aiohttp.ClientSession() as session:
        for msg in msgs:
            if not msg.attachments:
                continue

            deep_info = None
            image_attachments = []

            for attachment in msg.attachments:
                if attachment.filename.startswith("dango_deep_") and attachment.filename.endswith(".json"):
                    try:
                        async with session.get(attachment.url) as resp:
                            if resp.status == 200:
                                deep_info = json.loads(await resp.text())
                    except Exception as e:
                        print(
                            f"❌ [fetch_and_process_history] Failed to download deep attachment: {e}"
                        )
                elif attachment.content_type and attachment.content_type.startswith("image/"):
                    image_attachments.append(attachment)

            if deep_info is not None:
                images: list[Image] = []
                for img_att in image_attachments:
                    try:
                        async with session.get(img_att.url) as resp:
                            if resp.status == 200:
                                images.append(Image(content=await resp.read(), mime_type=img_att.content_type))
                    except Exception as e:
                        print(
                            f"❌ [fetch_and_process_history] Failed to download deep image: {e}"
                        )
                deep_info["_images"] = images
                deep_map[msg.id] = deep_info

    return deep_map


async def _download_image_attachments(msgs: list, bot_user_id: int) -> dict:
    """Download image attachments from user messages; returns dict[message_id -> list[Image]]."""
    image_map: dict[int, list[Image]] = {}
    async with aiohttp.ClientSession() as session:
        for msg in msgs:
            if msg.author.id == bot_user_id or not msg.attachments:
                continue
            images: list[Image] = []
            for attachment in msg.attachments:
                if "dango_replaced" in attachment.filename:
                    continue
                content_type = attachment.content_type or ""
                if not content_type.startswith("image/"):
                    continue
                try:
                    async with session.get(attachment.url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            images.append(Image(content=data, mime_type=content_type))
                except Exception as e:
                    print(f"❌ [fetch_and_process_history] Failed to download image: {e}")
            if images:
                image_map[msg.id] = images
    return image_map


async def _build_mention_map(msgs: list) -> dict[str, str]:
    """Collect all @user / @role mention tokens in msgs and resolve them to display names.

    Uses guild member/role cache first; falls back to fetch_member for cache misses.
    Returns a flat token→display-string dict, e.g. {"<@123>": "@Alice", "<@&456>": "@Mods"}.
    """
    guild = next((m.guild for m in msgs if m.guild), None)
    if guild is None:
        return {}

    user_ids: set[int] = set()
    role_ids: set[int] = set()
    for msg in msgs:
        for m in USER_MENTION_RE.finditer(msg.content):
            user_ids.add(int(m.group(1)))
        for m in ROLE_MENTION_RE.finditer(msg.content):
            role_ids.add(int(m.group(1)))

    mention_map: dict[str, str] = {}

    for uid in user_ids:
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        name = member.display_name if member else str(uid)
        mention_map[f"<@{uid}>"] = f"@{name}"
        mention_map[f"<@!{uid}>"] = f"@{name}"

    for rid in role_ids:
        role = guild.get_role(rid)
        name = role.name if role else str(rid)
        mention_map[f"<@&{rid}>"] = f"@{name}"

    if mention_map:
        print(f"🏷️  [fetch_and_process_history] Resolved {len(user_ids)} user(s), {len(role_ids)} role mention(s)")
    return mention_map


def _replace_table_placeholders(content: str, table_map: dict) -> str:
    """Replace table image placeholders with actual table markdown."""
    placeholder_pattern = r"> `\[dango_replaced_table_(\d+)_(\d+)_as_image\]`"

    def replacer(match):
        key = f"{match.group(1)}_{match.group(2)}"
        return table_map.get(key, match.group(0))

    return re.sub(placeholder_pattern, replacer, content)


def _process_messages(
    msgs: list,
    bot_user_id: int,
    table_content_map: dict,
    image_map: dict,
    deep_map: dict | None = None,
    mention_map: dict | None = None,
) -> tuple[list[Message], set[str]]:
    """Normalize Discord messages and convert to Agno Message list."""
    deep_map = deep_map or {}
    mention_map = mention_map or {}
    raw_messages = []
    unique_users: set[str] = set()

    for msg in msgs:
        if msg.id in deep_map:
            # Restore /deep slash command message as the original user turn
            info = deep_map[msg.id]
            author_name = info.get("author_name", "User")
            unique_users.add(author_name)
            raw_messages.append({
                "role": "user",
                "content": resolve_mentions(info.get("content", ""), mention_map),
                "author_id": info.get("author_id"),
                "author_name": author_name,
                "images": info.get("_images", []),
            })
        elif msg.author.id == bot_user_id:
            content = resolve_mentions(msg.content.strip(), mention_map)
            if content.startswith(SYSINFO_MARKER):
                continue
            raw_messages.append(
                {"role": "assistant", "content": content, "author_id": None, "author_name": "Bot"}
            )
        else:
            author_name = msg.author.display_name
            unique_users.add(author_name)
            raw_messages.append(
                {
                    "role": "user",
                    "content": resolve_mentions(msg.content.strip(), mention_map),
                    "author_id": msg.author.id,
                    "author_name": author_name,
                    "images": image_map.get(msg.id, []),
                }
            )

    # Normalize consecutive messages (combine same-role turns, add separators for different users)
    normalized: list[dict] = []
    i = 0
    while i < len(raw_messages):
        current = raw_messages[i]
        if current["role"] == "assistant":
            combined = [current["content"]]
            j = i + 1
            while j < len(raw_messages) and raw_messages[j]["role"] == "assistant":
                combined.append(raw_messages[j]["content"])
                j += 1
            normalized.append({"role": "assistant", "content": "\n".join(combined)})
            i = j
        else:
            combined = [f"{current['author_name']}: {current['content']}"]
            combined_images = list(current.get("images", []))
            j = i + 1
            while j < len(raw_messages) and raw_messages[j]["role"] == "user":
                if raw_messages[j]["author_id"] == current["author_id"]:
                    combined.append(raw_messages[j]["content"])
                    combined_images.extend(raw_messages[j].get("images", []))
                else:
                    break
                j += 1
            entry = {"role": "user", "content": "\n".join(combined), "images": combined_images}
            if (
                j < len(raw_messages)
                and raw_messages[j]["role"] == "user"
                and raw_messages[j]["author_id"] != current["author_id"]
            ):
                normalized.append(entry)
                normalized.append({"role": "assistant", "content": "...", "images": []})
                i = j
            else:
                normalized.append(entry)
                i = j

    # Replace table placeholders
    if table_content_map:
        for msg in normalized:
            msg["content"] = _replace_table_placeholders(
                msg["content"], table_content_map
            )

    # Remove leading assistant messages (model must not start conversation)
    while normalized and normalized[0]["role"] == "assistant":
        normalized.pop(0)

    formatted_history = [
        Message(role=m["role"], content=m["content"], images=m.get("images") or None)
        for m in normalized
    ]
    print(
        f"✅ [fetch_and_process_history] {len(formatted_history)} formatted messages, {len(unique_users)} unique users"
    )
    return formatted_history, unique_users
