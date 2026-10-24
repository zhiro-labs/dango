"""Admin-related Discord Cog"""

from zoneinfo import available_timezones

import discord
from discord import app_commands
from discord.ext import commands

# Cache timezones at module load for better performance
TIMEZONES = sorted(available_timezones())
TIMEZONES_LOWER = [(tz.lower(), tz) for tz in TIMEZONES]


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot, runtime_config):
        self.bot = bot
        self.runtime_config = runtime_config

    @app_commands.command(
        name="addchannel", description="Add current channel to bot's allowed list"
    )
    @app_commands.default_permissions(administrator=True)
    async def addchannel(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            channel_id = interaction.channel.id
            server_name = interaction.guild.name if interaction.guild else "DM"
            channel_name = (
                interaction.channel.name
                if hasattr(interaction.channel, "name")
                else "Unknown"
            )
            was_added = self.runtime_config.add_channel(
                channel_id, server_name, channel_name
            )

            if was_added:
                await interaction.response.send_message(
                    f"✅ Added {interaction.channel.mention} to allowed channels list",
                    ephemeral=True,
                )
                print(f"✅ [addchannel] Added channel {channel_id} to allowed list")
            else:
                await interaction.response.send_message(
                    f"ℹ️ {interaction.channel.mention} is already in the allowed list",
                    ephemeral=True,
                )
                print(f"ℹ️ [addchannel] Channel {channel_id} already in allowed list")
        except Exception as e:
            print(f"❌ [addchannel] Error adding channel: {e}")
            await interaction.response.send_message(
                "Failed to add channel to allowed list.", ephemeral=True
            )

    @app_commands.command(
        name="removechannel",
        description="Remove current channel from bot's allowed list",
    )
    @app_commands.default_permissions(administrator=True)
    async def removechannel(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            channel_id = interaction.channel.id
            was_removed = self.runtime_config.remove_channel(channel_id)

            if was_removed:
                await interaction.response.send_message(
                    f"✅ Removed {interaction.channel.mention} from allowed channels list",
                    ephemeral=True,
                )
                print(
                    f"✅ [removechannel] Removed channel {channel_id} from allowed list"
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ {interaction.channel.mention} was not in the allowed list",
                    ephemeral=True,
                )
                print(
                    f"ℹ️ [removechannel] Channel {channel_id} not found in allowed list"
                )
        except Exception as e:
            print(f"❌ [removechannel] Error removing channel: {e}")
            await interaction.response.send_message(
                "Failed to remove channel from allowed list.", ephemeral=True
            )

    @app_commands.command(
        name="listchannels",
        description="List all channels where bot is allowed in this server",
    )
    @app_commands.default_permissions(administrator=True)
    async def listchannels(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            allowed = self.runtime_config.allowed_channels
            if not allowed:
                await interaction.response.send_message(
                    "ℹ️ No channels in allowed list. Bot will only respond to mentions.",
                    ephemeral=True,
                )
            else:
                channel_mentions = []
                for channel_id in allowed:
                    channel = self.bot.get_channel(channel_id)
                    if (
                        channel
                        and channel.guild
                        and channel.guild.id == interaction.guild.id
                    ):
                        channel_mentions.append(
                            f"• {channel.mention} (ID: {channel_id})"
                        )

                if not channel_mentions:
                    await interaction.response.send_message(
                        f"ℹ️ No allowed channels in **{interaction.guild.name}**.",
                        ephemeral=True,
                    )
                else:
                    message = (
                        f"**Allowed Channels in {interaction.guild.name}:**\n"
                        + "\n".join(channel_mentions)
                    )
                    await interaction.response.send_message(message, ephemeral=True)
                    print(
                        f"✅ [listchannels] Listed {len(channel_mentions)} allowed channels for guild {interaction.guild.id}"
                    )
        except Exception as e:
            print(f"❌ [listchannels] Error listing channels: {e}")
            await interaction.response.send_message(
                "Failed to list allowed channels.", ephemeral=True
            )

    @app_commands.command(name="adduser", description="Add a user to bot's allowed DM list")
    @app_commands.default_permissions(administrator=True)
    async def adduser(self, interaction: discord.Interaction, user: discord.User):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            user_id = user.id
            username = (
                f"{user.name}#{user.discriminator}"
                if user.discriminator != "0"
                else user.name
            )
            was_added = self.runtime_config.add_user(user_id, username)

            if was_added:
                await interaction.response.send_message(
                    f"✅ Added {user.mention} to allowed DM users list",
                    ephemeral=True,
                )
                print(
                    f"✅ [adduser] Added user {user_id} ({user.name}) to allowed list"
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ {user.mention} is already in the allowed DM list",
                    ephemeral=True,
                )
                print(
                    f"ℹ️ [adduser] User {user_id} ({user.name}) already in allowed list"
                )
        except Exception as e:
            print(f"❌ [adduser] Error adding user: {e}")
            await interaction.response.send_message(
                "Failed to add user to allowed DM list.", ephemeral=True
            )

    @app_commands.command(
        name="removeuser", description="Remove a user from bot's allowed DM list"
    )
    @app_commands.default_permissions(administrator=True)
    async def removeuser(self, interaction: discord.Interaction, user: discord.User):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            user_id = user.id
            was_removed = self.runtime_config.remove_user(user_id)

            if was_removed:
                await interaction.response.send_message(
                    f"✅ Removed {user.mention} from allowed DM users list",
                    ephemeral=True,
                )
                print(
                    f"✅ [removeuser] Removed user {user_id} ({user.name}) from allowed list"
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ {user.mention} was not in the allowed DM list",
                    ephemeral=True,
                )
                print(
                    f"ℹ️ [removeuser] User {user_id} ({user.name}) not found in allowed list"
                )
        except Exception as e:
            print(f"❌ [removeuser] Error removing user: {e}")
            await interaction.response.send_message(
                "Failed to remove user from allowed DM list.", ephemeral=True
            )

    @app_commands.command(
        name="listusers", description="List all users allowed to DM the bot"
    )
    @app_commands.default_permissions(administrator=True)
    async def listusers(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            allowed = self.runtime_config.allowed_users
            if not allowed:
                await interaction.response.send_message(
                    "ℹ️ No users in allowed DM list.",
                    ephemeral=True,
                )
            else:
                user_mentions = []
                for user_id in allowed:
                    user = await self.bot.fetch_user(user_id)
                    if user:
                        user_mentions.append(f"• {user.mention} (ID: {user_id})")
                    else:
                        user_mentions.append(f"• Unknown user (ID: {user_id})")

                message = "**Allowed DM Users:**\n" + "\n".join(user_mentions)
                await interaction.response.send_message(message, ephemeral=True)
                print(f"✅ [listusers] Listed {len(allowed)} allowed users")
        except Exception as e:
            print(f"❌ [listusers] Error listing users: {e}")
            await interaction.response.send_message(
                "Failed to list allowed users.", ephemeral=True
            )

    @app_commands.command(
        name="refreshmetadata",
        description="Refresh all channel and user names in config comments",
    )
    @app_commands.default_permissions(administrator=True)
    async def refreshmetadata(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=True)

            channel_updates = {}
            user_updates = {}

            for channel_id in self.runtime_config.allowed_channels:
                channel = self.bot.get_channel(channel_id)
                if channel and hasattr(channel, "guild"):
                    channel_updates[channel_id] = {
                        "server": channel.guild.name,
                        "channel": channel.name,
                    }

            for user_id in self.runtime_config.allowed_users:
                try:
                    user = await self.bot.fetch_user(user_id)
                    if user:
                        username = (
                            f"{user.name}#{user.discriminator}"
                            if user.discriminator != "0"
                            else user.name
                        )
                        user_updates[user_id] = {"username": username}
                except Exception as e:
                    print(f"⚠️ [refreshmetadata] Could not fetch user {user_id}: {e}")

            self.runtime_config.batch_update_metadata(
                channels=channel_updates if channel_updates else None,
                users=user_updates if user_updates else None,
            )

            await interaction.followup.send(
                f"✅ Refreshed metadata for {len(channel_updates)} channel(s) and {len(user_updates)} user(s)",
                ephemeral=True,
            )
            print(
                f"✅ [refreshmetadata] Updated {len(channel_updates)} channels and {len(user_updates)} users"
            )
        except Exception as e:
            print(f"❌ [refreshmetadata] Error refreshing metadata: {e}")
            try:
                await interaction.followup.send(
                    "Failed to refresh metadata.", ephemeral=True
                )
            except Exception:
                await interaction.response.send_message(
                    "Failed to refresh metadata.", ephemeral=True
                )

    @app_commands.command(
        name="sethistorylimit",
        description="Set the number of messages to include in conversation history",
    )
    @app_commands.default_permissions(administrator=True)
    async def sethistorylimit(self, interaction: discord.Interaction, limit: int):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            self.runtime_config.set_history_limit(limit)
            await interaction.response.send_message(
                f"✅ History limit set to {limit} messages",
                ephemeral=True,
            )
            print(f"✅ [sethistorylimit] History limit updated to {limit}")
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception as e:
            print(f"❌ [sethistorylimit] Error setting history limit: {e}")
            await interaction.response.send_message(
                "Failed to set history limit.", ephemeral=True
            )

    @app_commands.command(
        name="setactivity",
        description="Set the bot's Discord activity status message",
    )
    @app_commands.default_permissions(administrator=True)
    async def setactivity(self, interaction: discord.Interaction, activity: str):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            if len(activity) > 128:
                await interaction.response.send_message(
                    "❌ Activity message is too long (max 128 characters).",
                    ephemeral=True,
                )
                return

            self.runtime_config.set_discord_activity(activity)

            custom_activity = discord.CustomActivity(name=activity)
            await self.bot.change_presence(
                activity=custom_activity, status=discord.Status.online
            )

            await interaction.response.send_message(
                f"✅ Bot activity updated to: {activity}\n(Will persist after bot restart)",
                ephemeral=True,
            )
            print(f"✅ [setactivity] Activity updated to: {activity}")
        except Exception as e:
            print(f"❌ [setactivity] Error setting activity: {e}")
            await interaction.response.send_message(
                "Failed to set activity status.", ephemeral=True
            )

    @app_commands.command(
        name="settimezone",
        description="Set the bot's timezone for timestamps",
    )
    @app_commands.describe(timezone="The timezone to set (e.g., Asia/Tokyo)")
    @app_commands.default_permissions(administrator=True)
    async def settimezone(self, interaction: discord.Interaction, timezone: str):
        try:
            if not interaction.guild:
                await interaction.response.send_message(
                    "❌ This command can only be used in a server, not in DMs.",
                    ephemeral=True,
                )
                return

            if timezone not in available_timezones():
                await interaction.response.send_message(
                    f"❌ Invalid timezone: {timezone}",
                    ephemeral=True,
                )
                return

            self.runtime_config.set_timezone(timezone)
            await interaction.response.send_message(
                f"✅ Timezone set to: {timezone}",
                ephemeral=True,
            )
            print(f"✅ [settimezone] Timezone updated to: {timezone}")
        except Exception as e:
            print(f"❌ [settimezone] Error setting timezone: {e}")
            await interaction.response.send_message(
                "Failed to set timezone.", ephemeral=True
            )

    @settimezone.autocomplete("timezone")
    async def timezone_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        print(f"🔍 [timezone_autocomplete] Called with: '{current}'")
        try:
            if not current:
                results = [
                    app_commands.Choice(name=tz, value=tz)
                    for tz in TIMEZONES[:25]
                ]
                print(
                    f"🔍 [timezone_autocomplete] Returning {len(results)} default results"
                )
                return results

            query = current.lower()
            filtered = [tz for tz_lower, tz in TIMEZONES_LOWER if query in tz_lower][
                :25
            ]
            results = [
                app_commands.Choice(name=tz, value=tz) for tz in filtered
            ]
            print(
                f"🔍 [timezone_autocomplete] Query '{current}' returned {len(results)} results"
            )
            return results
        except Exception as e:
            print(f"❌ [timezone_autocomplete] Error: {e}")
            return []
