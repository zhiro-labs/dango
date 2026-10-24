---
summary: "`runtime.yml` and all Discord slash commands for live configuration."
---

# Runtime Config

Runtime settings are stored in `config/runtime.yml` and managed through Discord slash commands or the web dashboard's **Discord** tab. Changes take effect on the next message — no restarts needed, except that a new activity status set outside `/setactivity` shows after a restart.

## What's in runtime.yml

```yaml
allowed_channels:   # channel IDs where the bot responds without a mention
  - 123456789012345678

allowed_users:      # user IDs allowed to DM the bot
  - 111222333444555666

timezone: UTC       # IANA timezone for timestamps in the system prompt
discord_activity: Surfing   # bot's Discord activity status (max 128 characters)
history_limit: 12   # messages of history sent with each request (at least 1)
```

The bot and the dashboard both write this file, and each re-reads it before saving, so changes made from one side are never lost by the other. Invalid values (an unknown timezone, an activity over 128 characters, a history limit below 1) are rejected with a message instead of being saved.

You can also edit the file by hand; the bot picks up changes on the next message. If an edit leaves the file unparseable, the bot keeps using the last good settings and logs a warning, the dashboard shows the parse error, and nothing overwrites the file until you fix it.

## Slash Commands

All settings in `runtime.yml` are managed through Discord slash commands — no file editing needed. See the [Slash Commands reference](../usage/commands.md) for the full list.

## Default behaviour

Without any `/addchannel` setup, the bot only responds when directly mentioned (`@BotName`). Add channels to let it respond to all messages there.

DMs are blocked by default. Use `/adduser` to grant DM access per user.
