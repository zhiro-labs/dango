import os
import sys
from pathlib import Path


def _setup_log_tee() -> None:
    """Tee stdout/stderr to data/bot.log for the web GUI log viewer."""
    log_path = Path(os.getenv("DATA_DIR", "data")) / "bot.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    class _Tee:
        def __init__(self, *streams):
            self._streams = streams

        def write(self, data):
            for s in self._streams:
                try:
                    s.write(data)
                except Exception:
                    pass

        def flush(self):
            for s in self._streams:
                try:
                    s.flush()
                except Exception:
                    pass

        def fileno(self):
            return self._streams[0].fileno()

        def isatty(self):
            return False

    _log_file = open(log_path, "w", encoding="utf-8", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, _log_file)
    sys.stderr = _Tee(sys.__stderr__, _log_file)


_setup_log_tee()

from dotenv import load_dotenv

# Both load_dotenv() and inject_config_to_env() must run before any dango imports —
# importing dango triggers dango/__init__.py which pulls in chat_commands.py, and
# that reads ENABLE_MESSAGE_BATCHING etc. at module level. (Agent settings in
# dango/agent/ are read later, when create_discord_workflow() builds the agents.)
# app_config is a top-level module (not inside dango/) so importing it is safe here.
load_dotenv()

from app_config import inject_config_to_env
_chat_sys_prompt_inline = inject_config_to_env()  # None when using .env (developer path)

import discord
from discord.ext import commands

from dango.commands import AdminCog, ChatCog
from dango.utils import check_font_exists, download_noto_font, env_onoff_to_bool, runtime_config
from dango.utils import workspace_context
from dango.workflow import create_discord_workflow

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_BOT_ACTIVITY = runtime_config.discord_activity

FAST_MODEL = os.getenv("FAST_MODEL")
ENABLE_CONTEXTUAL_SYSTEM_PROMPT = env_onoff_to_bool(
    os.getenv("ENABLE_CONTEXTUAL_SYSTEM_PROMPT"), default=True
)
ENABLE_WORKSPACE = env_onoff_to_bool(os.getenv("ENABLE_WORKSPACE"))
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", "workspace")
WORKSPACE_SYS_PROMPT_PATH = os.getenv("WORKSPACE_SYS_PROMPT_PATH", "config/workspace_sys_prompt.txt")

CHAT_SYS_PROMPT_PATH = os.getenv("CHAT_SYS_PROMPT_PATH")

if _chat_sys_prompt_inline is not None:
    chat_system_prompt = _chat_sys_prompt_inline
else:
    with open(CHAT_SYS_PROMPT_PATH, encoding="utf-8") as file:
        chat_system_prompt = file.read()


# Discord setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

custom_activity = discord.CustomActivity(name=DISCORD_BOT_ACTIVITY)

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    activity=custom_activity,
    status=discord.Status.online,
)

discord_workflow = create_discord_workflow()

if not check_font_exists():
    print("🔤 Downloading Noto Sans CJK fonts for markdown table image rendering...")
    print("📦 This may take a few minutes depending on your connection (~100MB)")
    if download_noto_font():
        print("✅ Font download completed successfully!")
    else:
        print("❌ Font download failed.")
        print("⚠️  Bot will continue but table rendering may not work properly")
        print("💡 You can try running 'uv run python utils/download_font.py' later")


@bot.event
async def setup_hook():
    if ENABLE_WORKSPACE:
        await workspace_context.init(WORKSPACE_ROOT, WORKSPACE_SYS_PROMPT_PATH)
    await bot.add_cog(ChatCog(bot, discord_workflow, chat_system_prompt, runtime_config))
    await bot.add_cog(AdminCog(bot, runtime_config))

    # User-defined slash commands from custom/*.py (gitignored). Loading is
    # idempotent with the agent-tool loader; absent custom/ dir → no-op.
    from dango.extensions import load_custom_modules, register_custom_commands
    load_custom_modules()
    register_custom_commands(bot)


@bot.event
async def on_ready():
    print(f"🚀 {bot.user} has connected to Discord!")
    print(f"🤖 Bot ID: {bot.user.id}")
    print(f"🔧 Connected to {len(bot.guilds)} guilds")

    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")


def main():
    print("🚀 Hello from dango!")
    print(f"🔑 Discord token loaded: {'✅' if DISCORD_BOT_TOKEN else '❌'}")
    print(f"🤖 Fast model: {FAST_MODEL}")
    print(f"🌡️ Chat temperature: {os.getenv('GEMINI_TEMPERATURE', '(default)')}")
    print(f"📄 Chat system prompt path: {CHAT_SYS_PROMPT_PATH or '(inline from GUI)'}")
    print(f"🔌 Contextual system prompt: {ENABLE_CONTEXTUAL_SYSTEM_PROMPT}")
    print("🔌 Starting Discord bot...")
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
