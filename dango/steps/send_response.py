"""
Send the LLM response (text + table images + table files) to Discord.
"""

import os

import discord
from agno.workflow import StepInput, StepOutput

from ..utils.discord_helpers import split_message


async def send_discord_response(step_input: StepInput, _bot=None) -> StepOutput:
    """Send text and image attachments to the Discord channel."""
    data = step_input.previous_step_content
    message_data = data["message_data"]
    bot = message_data["_bot"]

    channel_id = message_data["channel_id"]
    message_id = message_data.get("message_id")
    interaction = message_data.get("_interaction")
    is_ephemeral = data.get("ephemeral", False)

    discord_response = data.get("discord_response") or {}
    extra_embeds: list[discord.Embed] = discord_response.get("embeds", [])
    suppress_text: bool = discord_response.get("suppress_text", False)

    if data.get("error"):
        response_text = data.get("error_message", "An error occurred while processing your message.")
        table_images = []
        extracted_tables_files = []
        suppress_text = False  # always show error text
    else:
        response_text = data.get("response_text") or data.get("llm_response", "No response generated")
        table_images = data.get("table_images", [])
        extracted_tables_files = data.get("extracted_tables_files", [])

    print(
        f"📤 [send_discord_response] Sending to channel {channel_id}"
        f", {len(table_images)} images, {len(extra_embeds)} embed(s)"
        + (" (ephemeral)" if is_ephemeral else "")
        + (" (suppress_text)" if suppress_text else "")
    )

    try:
        files = []
        for img_data in table_images:
            files.append(discord.File(img_data["buffer"], filename=img_data["filename"]))
        for table_file in extracted_tables_files:
            if os.path.exists(table_file):
                files.append(discord.File(table_file, filename=os.path.basename(table_file)))

        message_chunks = [] if suppress_text else split_message(response_text)
        fallback_sysinfo = data.get("fallback_sysinfo")

        if interaction:
            # Respond via interaction followup (modal submit / component click / context menu).
            if message_chunks:
                # Send text chunks; embeds and files go on the last chunk.
                for chunk in message_chunks[:-1]:
                    await interaction.followup.send(content=chunk, ephemeral=is_ephemeral)
                await interaction.followup.send(
                    content=message_chunks[-1],
                    embeds=extra_embeds[:10],
                    files=files,
                    ephemeral=is_ephemeral,
                )
            elif extra_embeds or files:
                await interaction.followup.send(
                    embeds=extra_embeds[:10],
                    files=files,
                    ephemeral=is_ephemeral,
                )
            if fallback_sysinfo:
                await interaction.followup.send(fallback_sysinfo, ephemeral=is_ephemeral)
        else:
            channel = bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden) as e:
                    print(f"❌ [send_discord_response] Cannot access channel: {e}")
                    return StepOutput(content="failed")

            original_message = None
            if message_id:
                try:
                    original_message = await channel.fetch_message(message_id)
                except (discord.NotFound, discord.Forbidden):
                    pass

            send = original_message.reply if original_message else channel.send

            if message_chunks:
                for chunk in message_chunks[:-1]:
                    await send(content=chunk)
                await send(content=message_chunks[-1], embeds=extra_embeds[:10], files=files)
            elif extra_embeds or files:
                await send(embeds=extra_embeds[:10], files=files)

            if fallback_sysinfo:
                await channel.send(fallback_sysinfo)

        # Clean up temp table files
        for table_file in extracted_tables_files:
            try:
                if os.path.exists(table_file):
                    os.remove(table_file)
            except Exception:
                pass

        print("✅ [send_discord_response] Message sent successfully")
        return StepOutput(content="sent")

    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"❌ [send_discord_response] Failed to send message: {e}")
        return StepOutput(content="failed")
