"""
Runtime configuration management with YAML persistence.

config/runtime.yml is always created on first run with sane defaults.
It is the single source of truth for runtime state across all deployment
modes (Docker + GUI, uv, embedded package).

  Docker + GUI  — GUI writes the file; bot reads and updates it.
  uv / package  — file is auto-created at startup; Discord commands update it.

.env (or environment variables) is NOT used for runtime settings.
It is reserved for credentials, model names, and feature flags.
"""

import re
from pathlib import Path
from threading import Lock

import yaml

# Anything that cannot sit inside a single-line "# ..." YAML comment: line
# breaks (including NEL and the Unicode line/paragraph separators) and
# characters PyYAML's reader rejects as non-printable anywhere in the file.
_COMMENT_UNSAFE = re.compile(
    "[^\x09\x20-\x7e\xa0-‧‪-퟿-�\U00010000-\U0010ffff]"
)


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


class RuntimeConfig:
    """Thread-safe runtime configuration with YAML persistence.

    Loads config/runtime.yml on startup, creating it with sane defaults if
    absent. All mutations persist to YAML so Discord commands survive restarts.

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
        self._load()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self.config_path.exists():
            with open(self.config_path, encoding="utf-8") as f:
                self._cache = yaml.safe_load(f) or {}
            self._cache.setdefault("channel_metadata", {})
            self._cache.setdefault("user_metadata", {})
        else:
            # First run — create file with sane defaults
            self._cache = {
                "allowed_channels": list(self._default_channels),
                "allowed_users":    [],
                "channel_metadata": {},
                "user_metadata":    {},
                "timezone":         "UTC",
                "discord_activity": "Surfing",
                "history_limit":    12,
            }
            self._save()

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

        with open(self.config_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    # ── Public read API ───────────────────────────────────────────────────────

    @property
    def allowed_channels(self) -> set[int]:
        return set(self._cache.get("allowed_channels", []))

    @property
    def allowed_users(self) -> set[int]:
        return set(self._cache.get("allowed_users", []))

    @property
    def timezone(self) -> str:
        return self._cache.get("timezone", "UTC")

    @property
    def discord_activity(self) -> str:
        return self._cache.get("discord_activity", "Surfing")

    @property
    def history_limit(self) -> int:
        return self._cache.get("history_limit", 12)

    # ── Mutation API (always persists to YAML, creating file on first write) ──

    def add_channel(
        self, channel_id: int, server_name: str = None, channel_name: str = None
    ) -> bool:
        with self._lock:
            channels = self._cache.get("allowed_channels", [])
            metadata = self._cache.get("channel_metadata", {})
            if server_name or channel_name:
                metadata[str(channel_id)] = {
                    "server": server_name or "Unknown Server",
                    "channel": channel_name or "Unknown Channel",
                }
                self._cache["channel_metadata"] = metadata
            if channel_id not in channels:
                channels.append(channel_id)
                self._cache["allowed_channels"] = channels
                self._save()
                return True
            if server_name or channel_name:
                self._save()
            return False

    def remove_channel(self, channel_id: int) -> bool:
        with self._lock:
            channels = self._cache.get("allowed_channels", [])
            if channel_id in channels:
                channels.remove(channel_id)
                self._cache["allowed_channels"] = channels
                self._save()
                return True
            return False

    def add_user(self, user_id: int, username: str = None) -> bool:
        with self._lock:
            users = self._cache.get("allowed_users", [])
            metadata = self._cache.get("user_metadata", {})
            if username:
                metadata[str(user_id)] = {"username": username}
                self._cache["user_metadata"] = metadata
            if user_id not in users:
                users.append(user_id)
                self._cache["allowed_users"] = users
                self._save()
                return True
            if username:
                self._save()
            return False

    def remove_user(self, user_id: int) -> bool:
        with self._lock:
            users = self._cache.get("allowed_users", [])
            if user_id in users:
                users.remove(user_id)
                self._cache["allowed_users"] = users
                self._save()
                return True
            return False

    def set_timezone(self, timezone: str) -> None:
        with self._lock:
            self._cache["timezone"] = timezone
            self._save()

    def set_discord_activity(self, activity: str) -> None:
        with self._lock:
            self._cache["discord_activity"] = activity
            self._save()

    def set_history_limit(self, limit: int) -> None:
        with self._lock:
            self._cache["history_limit"] = limit
            self._save()

    def reload(self) -> None:
        """Reload from source (YAML file or env vars)."""
        with self._lock:
            self._load()

    def batch_update_metadata(
        self, channels: dict = None, users: dict = None
    ) -> None:
        with self._lock:
            if channels:
                channel_metadata = self._cache.get("channel_metadata", {})
                channel_metadata.update(channels)
                self._cache["channel_metadata"] = channel_metadata
            if users:
                user_metadata = self._cache.get("user_metadata", {})
                user_metadata.update(users)
                self._cache["user_metadata"] = user_metadata
            self._save()


# Global singleton.
# Startup: reads YAML if present, otherwise bootstraps from env vars.
# Mutations: always persist to YAML (creating it on first write).
runtime_config = RuntimeConfig()
