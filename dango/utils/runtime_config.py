"""
Runtime configuration management with YAML persistence.

config/runtime.yml is always created on first run with sane defaults.
It is the single source of truth for runtime state across all deployment
modes (Docker + GUI, uv, embedded package).

  Docker + GUI  — the dashboard and the bot both read and update it.
  uv / package  — file is auto-created at startup; Discord commands update it.

The bot and the web dashboard run as separate processes and both edit the
file through this class, so every change re-reads the file first instead of
saving a possibly stale copy.

.env (or environment variables) is NOT used for runtime settings.
It is reserved for credentials, model names, and feature flags.
"""

import copy
import functools
import os
import re
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import TypeVar
from zoneinfo import available_timezones

import yaml

T = TypeVar("T")

MAX_ACTIVITY_LENGTH = 128  # Discord's limit for a custom status

DEFAULT_SETTINGS = {
    "timezone": "UTC",
    "discord_activity": "Surfing",
    "history_limit": 12,
}

# Anything that cannot sit inside a single-line "# ..." YAML comment: line
# breaks (including NEL and the Unicode line/paragraph separators) and
# characters PyYAML's reader rejects as non-printable anywhere in the file.
_COMMENT_UNSAFE = re.compile(
    "[^\x09\x20-\x7e\xa0-‧‪-퟿-�\U00010000-\U0010ffff]"
)


class RuntimeConfigError(Exception):
    """runtime.yml exists but cannot be read. It is never overwritten then."""


def _comment(text: object) -> str:
    """Make text safe to place after '#' on one YAML line."""
    return _COMMENT_UNSAFE.sub(" ", str(text)).strip()


def _dump(data: object) -> str:
    """Serialize with PyYAML so every value is quoted and escaped as needed.

    Server names, channel names and activity text are user-controlled; written
    raw, values like "[TW] Gaming" or "Playing: chess" produce invalid YAML.
    """
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=float("inf"),  # never wrap, so a list item stays on one line
    )


def _list_item(value: object, label: str) -> str:
    """One '- value  # label' line, indented under its key."""
    return f"  {_dump([value]).rstrip()}  # {_comment(label)}\n"


@functools.cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone(timezone: str) -> None:
    if timezone not in _timezones():
        raise ValueError(f"Unknown timezone '{timezone}'. Use an IANA name such as Asia/Taipei.")


def validate_activity(activity: str) -> None:
    if len(activity) > MAX_ACTIVITY_LENGTH:
        raise ValueError(f"Activity must be at most {MAX_ACTIVITY_LENGTH} characters.")


def validate_history_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("History limit must be at least 1.")


class RuntimeConfig:
    """Runtime configuration with YAML persistence, safe to share between processes.

    Reads are served from memory (loaded at startup). Every change re-reads
    the file, applies the change and writes it back atomically, so edits made
    by another process (the web dashboard) since the last read are kept.

    A file that cannot be parsed is reported as RuntimeConfigError on first
    use rather than on construction, so importing dango never fails because
    of it; it is never overwritten while unreadable.

    Args:
        config_path: Path to the YAML file (created automatically on first run).
        default_channels: Channel IDs to add when no YAML exists yet (first run
            only). Ignored on subsequent starts so admin /removechannel changes
            are preserved. Intended for embedded deployments where the developer
            knows the target channels upfront.
    """

    def __init__(
        self,
        config_path: str = "config/runtime.yml",
        default_channels: list[int] | None = None,
    ):
        self.config_path = Path(config_path)
        self._lock = Lock()
        self._cache: dict = {}
        self._default_channels: list[int] = default_channels or []
        self._load_error: RuntimeConfigError | None = None
        self._mtime: int | None = None  # file mtime (ns) behind the cache
        try:
            self._load()
        except RuntimeConfigError as e:
            self._load_error = e

    # ── Internal ─────────────────────────────────────────────────────────────

    def _read(self) -> dict:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RuntimeConfigError(
                f"{self.config_path} is not valid YAML ({e}). Fix the file, or delete it "
                "to start over; it is not changed until it can be read."
            ) from e
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise RuntimeConfigError(f"{self.config_path} must contain a YAML mapping, not {type(data).__name__}.")
        for key in ("allowed_channels", "allowed_users"):
            data[key] = list(data.get(key) or [])
        for key in ("channel_metadata", "user_metadata"):
            data[key] = dict(data.get(key) or {})
        return data

    def _file_mtime(self) -> int | None:
        try:
            return self.config_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _load(self) -> None:
        if self.config_path.exists():
            mtime = self._file_mtime()
            self._cache = self._read()
            self._mtime = mtime
        else:
            # First run — create file with sane defaults
            self._cache = {
                "allowed_channels": list(self._default_channels),
                "allowed_users":    [],
                "channel_metadata": {},
                "user_metadata":    {},
                **DEFAULT_SETTINGS,
            }
            self._save()
        self._load_error = None

    def _data(self) -> dict:
        """The settings for a read, refreshed if the file changed on disk.

        Picks up edits made by hand or by the dashboard on the next read. If
        the new contents cannot be parsed, the last good settings are kept
        (with a warning) so a typo does not take the bot down mid-run.
        """
        with self._lock:
            mtime = self._file_mtime()
            if mtime is not None and mtime != self._mtime:
                try:
                    self._cache = self._read()
                    self._load_error = None
                except RuntimeConfigError as e:
                    if self._load_error is None:
                        print(f"⚠️ [runtime_config] {e} Keeping the last good settings.")
                    else:
                        self._load_error = e
                self._mtime = mtime  # warn once per change, not on every read
            if self._load_error is not None:
                raise self._load_error
            return self._cache

    def _mutate(self, change: Callable[[dict], T]) -> T:
        """Apply `change` to the file's current contents and save if it changed.

        Re-reads first: the dashboard edits this file from another process,
        and saving a stale copy would silently undo its changes.
        """
        with self._lock:
            self._load()
            before = copy.deepcopy(self._cache)
            result = change(self._cache)
            if self._cache != before:
                self._save()
            return result

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        channels = self._cache.get("allowed_channels", [])
        channel_metadata = self._cache.get("channel_metadata", {})
        users = self._cache.get("allowed_users", [])
        user_metadata = self._cache.get("user_metadata", {})

        lines = [
            "# Runtime configuration - can be modified via Discord commands\n",
            "# This file is auto-generated and will be updated by the bot\n\n",
            "# List of channel IDs where the bot is allowed to respond\n",
            "allowed_channels:\n",
        ]
        if not channels:
            lines.append("  []\n")
        else:
            for cid in channels:
                meta = channel_metadata.get(str(cid), {})
                server = meta.get("server", "Unknown Server")
                channel = meta.get("channel", "Unknown Channel")
                lines.append(_list_item(cid, f"{server} / #{channel}"))

        lines.append("\n# List of user IDs allowed to DM the bot\n")
        lines.append("allowed_users:\n")
        if not users:
            lines.append("  []\n")
        else:
            for uid in users:
                meta = user_metadata.get(str(uid), {})
                lines.append(_list_item(uid, meta.get("username", "Unknown User")))

        # Keys are forced to str so lookups by str(id) keep working on reload.
        lines.append("\n# Metadata for human-readable comments (auto-managed)\n")
        lines.append(_dump({"channel_metadata": {
            str(cid): {
                "server": meta.get("server", "Unknown"),
                "channel": meta.get("channel", "Unknown"),
            }
            for cid, meta in channel_metadata.items()
        }}))

        lines.append("\n")
        lines.append(_dump({"user_metadata": {
            str(uid): {"username": meta.get("username", "Unknown")}
            for uid, meta in user_metadata.items()
        }}))

        lines.append("\n# Timezone for bot operations\n")
        lines.append(_dump({"timezone": self._cache.get("timezone", "UTC")}))
        lines.append("\n# Discord bot activity status message\n")
        lines.append(_dump({"discord_activity": self._cache.get("discord_activity", "Surfing")}))
        lines.append("\n# Number of messages to include in conversation history\n")
        lines.append(_dump({"history_limit": self._cache.get("history_limit", 12)}))

        # Write a sibling temp file and swap it in, so the other process never
        # reads a half-written file.
        tmp = self.config_path.with_name(f".{self.config_path.name}.tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        os.replace(tmp, self.config_path)
        self._mtime = self._file_mtime()

    # ── Public read API ───────────────────────────────────────────────────────

    @property
    def allowed_channels(self) -> set[int]:
        return set(self._data().get("allowed_channels", []))

    @property
    def allowed_users(self) -> set[int]:
        return set(self._data().get("allowed_users", []))

    @property
    def timezone(self) -> str:
        return self._data().get("timezone", "UTC")

    @property
    def discord_activity(self) -> str:
        return self._data().get("discord_activity", "Surfing")

    @property
    def history_limit(self) -> int:
        return self._data().get("history_limit", 12)

    def snapshot(self) -> dict:
        """Everything in the file, freshly re-read, with defaults filled in.

        For displays (the web dashboard) that must show what is on disk now.
        """
        with self._lock:
            self._load()
            c = self._cache
            return {
                "allowed_channels": list(c["allowed_channels"]),
                "allowed_users":    list(c["allowed_users"]),
                "channel_metadata": copy.deepcopy(c["channel_metadata"]),
                "user_metadata":    copy.deepcopy(c["user_metadata"]),
                "timezone":         str(c.get("timezone") or DEFAULT_SETTINGS["timezone"]),
                "discord_activity": str(c.get("discord_activity") or DEFAULT_SETTINGS["discord_activity"]),
                "history_limit":    int(c.get("history_limit") or DEFAULT_SETTINGS["history_limit"]),
            }

    # ── Mutation API (re-reads, then persists to YAML) ────────────────────────

    def add_channel(
        self, channel_id: int, server_name: str = None, channel_name: str = None
    ) -> bool:
        """Allow a channel; returns False if it was already allowed."""
        def change(c: dict) -> bool:
            if server_name or channel_name:
                c["channel_metadata"][str(channel_id)] = {
                    "server": server_name or "Unknown Server",
                    "channel": channel_name or "Unknown Channel",
                }
            if channel_id in c["allowed_channels"]:
                return False
            c["allowed_channels"].append(channel_id)
            return True
        return self._mutate(change)

    def remove_channel(self, channel_id: int) -> bool:
        """Disallow a channel and drop its metadata; returns False if it wasn't allowed."""
        def change(c: dict) -> bool:
            c["channel_metadata"].pop(str(channel_id), None)
            if channel_id not in c["allowed_channels"]:
                return False
            c["allowed_channels"].remove(channel_id)
            return True
        return self._mutate(change)

    def add_user(self, user_id: int, username: str = None) -> bool:
        """Allow a user to DM the bot; returns False if already allowed."""
        def change(c: dict) -> bool:
            if username:
                c["user_metadata"][str(user_id)] = {"username": username}
            if user_id in c["allowed_users"]:
                return False
            c["allowed_users"].append(user_id)
            return True
        return self._mutate(change)

    def remove_user(self, user_id: int) -> bool:
        """Disallow a user and drop their metadata; returns False if they weren't allowed."""
        def change(c: dict) -> bool:
            c["user_metadata"].pop(str(user_id), None)
            if user_id not in c["allowed_users"]:
                return False
            c["allowed_users"].remove(user_id)
            return True
        return self._mutate(change)

    def update_settings(
        self,
        *,
        timezone: str | None = None,
        discord_activity: str | None = None,
        history_limit: int | None = None,
    ) -> None:
        """Change any of the scalar settings at once.

        Raises ValueError (nothing is saved) if any given value is invalid.
        """
        if timezone is not None:
            validate_timezone(timezone)
        if discord_activity is not None:
            validate_activity(discord_activity)
        if history_limit is not None:
            validate_history_limit(history_limit)

        def change(c: dict) -> None:
            if timezone is not None:
                c["timezone"] = timezone
            if discord_activity is not None:
                c["discord_activity"] = discord_activity
            if history_limit is not None:
                c["history_limit"] = history_limit
        self._mutate(change)

    def set_timezone(self, timezone: str) -> None:
        self.update_settings(timezone=timezone)

    def set_discord_activity(self, activity: str) -> None:
        self.update_settings(discord_activity=activity)

    def set_history_limit(self, limit: int) -> None:
        self.update_settings(history_limit=limit)

    def reload(self) -> None:
        """Re-read the file (raises RuntimeConfigError if it cannot be read)."""
        with self._lock:
            self._load()

    def batch_update_metadata(
        self, channels: dict = None, users: dict = None
    ) -> None:
        def change(c: dict) -> None:
            if channels:
                c["channel_metadata"].update(channels)
            if users:
                c["user_metadata"].update(users)
        self._mutate(change)


# Global singleton. Reads config/runtime.yml (creating it on first run);
# an unreadable file is reported when the bot first uses it.
runtime_config = RuntimeConfig()
