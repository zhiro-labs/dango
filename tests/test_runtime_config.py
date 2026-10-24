"""
Tests for runtime.yml persistence.

Server names, channel names, usernames and activity text come from Discord and
are user-controlled. Whatever they contain, saving must produce a file that
loads back to the same values — a broken runtime.yml stops the bot at startup.
"""

import pytest
import yaml

from dango.utils.runtime_config import RuntimeConfig

# Values that were written raw before and broke (or silently changed) the YAML.
TRICKY_NAMES = [
    "[TW] Gaming",
    "Fans: Official",
    "Club #1",
    "{brace}",
    "*star",
    "&anchor",
    "!tag",
    "@at",
    "`tick",
    "%percent",
    "- dash",
    "'single' \"double\"",
    "  padded  ",
    "🍡 團子",
]

# Strings YAML would otherwise load as bool / null / int.
TYPE_LOOKALIKES = ["on", "yes", "no", "null", "~", "123", "1.5"]


def _reload(path) -> RuntimeConfig:
    return RuntimeConfig(str(path))


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "runtime.yml"


class TestRoundTrip:
    @pytest.mark.parametrize("name", TRICKY_NAMES + TYPE_LOOKALIKES)
    def test_channel_metadata_survives_reload(self, config_path, name):
        RuntimeConfig(str(config_path)).add_channel(123456789012345678, name, name)

        reloaded = _reload(config_path)
        meta = reloaded._cache["channel_metadata"]["123456789012345678"]
        assert meta == {"server": name, "channel": name}
        assert reloaded.allowed_channels == {123456789012345678}

    @pytest.mark.parametrize("name", TRICKY_NAMES + TYPE_LOOKALIKES)
    def test_username_survives_reload(self, config_path, name):
        RuntimeConfig(str(config_path)).add_user(111222333, name)

        reloaded = _reload(config_path)
        assert reloaded._cache["user_metadata"]["111222333"] == {"username": name}
        assert reloaded.allowed_users == {111222333}

    @pytest.mark.parametrize("activity", ["Playing: chess", "#1 fan", "[AFK]"] + TYPE_LOOKALIKES)
    def test_activity_survives_reload(self, config_path, activity):
        RuntimeConfig(str(config_path)).set_discord_activity(activity)

        assert _reload(config_path).discord_activity == activity

    def test_batch_metadata_update_survives_reload(self, config_path):
        rc = RuntimeConfig(str(config_path))
        rc.add_channel(1)
        rc.add_user(2)
        rc.batch_update_metadata(
            channels={"1": {"server": "[TW] Gaming", "channel": "a: b"}},
            users={"2": {"username": "x #y"}},
        )

        reloaded = _reload(config_path)
        assert reloaded._cache["channel_metadata"]["1"] == {"server": "[TW] Gaming", "channel": "a: b"}
        assert reloaded._cache["user_metadata"]["2"] == {"username": "x #y"}

    def test_scalar_settings_keep_their_types(self, config_path):
        rc = RuntimeConfig(str(config_path))
        rc.set_timezone("Asia/Taipei")
        rc.set_history_limit(30)

        reloaded = _reload(config_path)
        assert reloaded.timezone == "Asia/Taipei"
        assert reloaded.history_limit == 30


class TestUnsafeCharacters:
    # Line breaks and control characters cannot appear in a "# ..." comment;
    # the file must still load and keep every allowed ID.
    @pytest.mark.parametrize("name", ["a\nb", "a\r\nb", "a\u2028b", "a\u2029b", "a\x85b", "bell\x07"])
    def test_file_stays_loadable(self, config_path, name):
        rc = RuntimeConfig(str(config_path))
        rc.add_channel(1, name, name)
        rc.add_user(2, name)
        rc.set_discord_activity(name)

        reloaded = _reload(config_path)
        assert reloaded.allowed_channels == {1}
        assert reloaded.allowed_users == {2}

    def test_comments_never_span_lines(self, config_path):
        RuntimeConfig(str(config_path)).add_channel(1, "evil\nallowed_channels: [999]", "x")

        # A newline smuggled through the comment must not inject a new key.
        assert _reload(config_path).allowed_channels == {1}


class TestFileFormat:
    def test_first_run_writes_loadable_defaults(self, config_path):
        RuntimeConfig(str(config_path))

        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert data["allowed_channels"] == []
        assert data["allowed_users"] == []
        assert data["channel_metadata"] == {}
        assert data["user_metadata"] == {}
        assert data["timezone"] == "UTC"
        assert data["history_limit"] == 12

    def test_ids_keep_human_readable_comments(self, config_path):
        rc = RuntimeConfig(str(config_path))
        rc.add_channel(123, "[TW] Gaming", "general")
        rc.add_user(456, "alice")

        text = config_path.read_text(encoding="utf-8")
        assert "  - 123  # [TW] Gaming / #general\n" in text
        assert "  - 456  # alice\n" in text

    def test_metadata_keys_stay_strings(self, config_path):
        RuntimeConfig(str(config_path)).add_channel(123, "s", "c")

        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert list(data["channel_metadata"]) == ["123"]
