"""
Tests for runtime.yml as edited from the web dashboard and from the bot.

The dashboard (web/main.py) and the bot (RuntimeConfig, driven by admin
slash commands) run in separate processes and edit the same file. These
tests run in a temp working directory, since both use the relative path
config/runtime.yml.
"""

import os
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from dango.utils.runtime_config import RuntimeConfig

REPO = Path(__file__).resolve().parent.parent
LOCAL = "http://localhost:17860"
ORIGIN = {"origin": LOCAL}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    (tmp_path / "web").mkdir()
    os.symlink(REPO / "web" / "templates", tmp_path / "web" / "templates")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def client(workdir, monkeypatch):
    from web import main as web_main
    from web.config_store import BotConfig

    monkeypatch.setattr(web_main, "is_setup_complete", lambda: True)
    monkeypatch.setattr(web_main, "load_config", lambda: BotConfig())
    return TestClient(web_main.app, base_url=LOCAL)


def _file(workdir) -> dict:
    return yaml.safe_load((workdir / "config" / "runtime.yml").read_text(encoding="utf-8"))


def _write(workdir, data: dict) -> None:
    path = workdir / "config" / "runtime.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


EXISTING = {
    "allowed_channels": [111, 222],
    "allowed_users": [333],
    "channel_metadata": {"111": {"server": "Dango HQ", "channel": "general"}},
    "user_metadata": {"333": {"username": "alice"}},
    "timezone": "Asia/Taipei",
    "discord_activity": "Coding",
    "history_limit": 20,
}


class TestDashboard:
    def test_page_lists_channels_and_users(self, client, workdir):
        _write(workdir, EXISTING)
        html = client.get("/discord").text
        assert "Dango HQ / #general" in html
        assert 'hx-post="/api/runtime/channels/222/delete"' in html
        assert ">alice</p>" in html

    def test_add_channel(self, client, workdir):
        _write(workdir, EXISTING)
        r = client.post("/api/runtime/channels/add", data={"channel_id": " 444 "}, headers=ORIGIN)
        assert 'hx-post="/api/runtime/channels/444/delete"' in r.text
        assert _file(workdir)["allowed_channels"] == [111, 222, 444]

    def test_add_existing_channel_is_not_duplicated(self, client, workdir):
        _write(workdir, EXISTING)
        client.post("/api/runtime/channels/add", data={"channel_id": "111"}, headers=ORIGIN)
        assert _file(workdir)["allowed_channels"] == [111, 222]

    def test_add_channel_creates_missing_file(self, client, workdir):
        client.post("/api/runtime/channels/add", data={"channel_id": "444"}, headers=ORIGIN)
        assert _file(workdir)["allowed_channels"] == [444]

    def test_invalid_channel_id(self, client, workdir):
        _write(workdir, EXISTING)
        r = client.post("/api/runtime/channels/add", data={"channel_id": "abc"}, headers=ORIGIN)
        assert r.text == '<span class="text-error text-xs">Invalid channel ID</span>'
        assert _file(workdir)["allowed_channels"] == [111, 222]

    def test_remove_channel_and_its_metadata(self, client, workdir):
        _write(workdir, EXISTING)
        r = client.post("/api/runtime/channels/111/delete", headers=ORIGIN)
        assert "Dango HQ" not in r.text
        data = _file(workdir)
        assert data["allowed_channels"] == [222]
        assert data["channel_metadata"] == {}

    def test_add_and_remove_user(self, client, workdir):
        _write(workdir, EXISTING)
        client.post("/api/runtime/users/add", data={"user_id": "555"}, headers=ORIGIN)
        assert _file(workdir)["allowed_users"] == [333, 555]
        r = client.post("/api/runtime/users/add", data={"user_id": "x"}, headers=ORIGIN)
        assert r.text == '<span class="text-error text-xs">Invalid user ID</span>'
        client.post("/api/runtime/users/333/delete", headers=ORIGIN)
        data = _file(workdir)
        assert data["allowed_users"] == [555]
        assert data["user_metadata"] == {}

    def test_save_settings(self, client, workdir):
        _write(workdir, EXISTING)
        r = client.post("/api/runtime/settings", headers=ORIGIN, data={
            "timezone": " Europe/Berlin ", "discord_activity": " Reading ", "history_limit": "30",
        })
        assert "Saved" in r.text
        data = _file(workdir)
        assert (data["timezone"], data["discord_activity"], data["history_limit"]) == ("Europe/Berlin", "Reading", 30)
        assert data["allowed_channels"] == [111, 222]  # untouched

    def test_bot_reads_what_the_dashboard_wrote(self, client, workdir):
        _write(workdir, EXISTING)
        client.post("/api/runtime/channels/add", data={"channel_id": "444"}, headers=ORIGIN)
        client.post("/api/runtime/settings", headers=ORIGIN, data={
            "timezone": "Europe/Berlin", "discord_activity": "Reading", "history_limit": "30",
        })
        bot = RuntimeConfig("config/runtime.yml")
        assert bot.allowed_channels == {111, 222, 444}
        assert (bot.timezone, bot.discord_activity, bot.history_limit) == ("Europe/Berlin", "Reading", 30)


class TestBotMutations:
    def test_add_and_remove_report_changes(self, workdir):
        rc = RuntimeConfig("config/runtime.yml")
        assert rc.add_channel(1, "S", "c") is True
        assert rc.add_channel(1, "S", "c") is False
        assert rc.remove_channel(1) is True
        assert rc.remove_channel(1) is False
        assert rc.add_user(2, "bob") is True
        assert rc.add_user(2) is False
        assert rc.remove_user(2) is True
        assert rc.remove_user(2) is False

    def test_dashboard_reads_what_the_bot_wrote(self, client, workdir):
        rc = RuntimeConfig("config/runtime.yml")
        rc.add_channel(777, "[TW] Gaming", "general")
        rc.add_user(888, "carol")
        html = client.get("/discord").text
        assert "[TW] Gaming / #general" in html
        assert ">carol</p>" in html


# ── One shared implementation ─────────────────────────────────────────────────

CORRUPT = "allowed_channels:\n  - 111\nchannel_metadata:\n  '111':\n    server: [TW] Gaming\n"


class TestSharedFile:
    def test_bot_change_keeps_dashboard_edits(self, client, workdir):
        _write(workdir, EXISTING)
        bot = RuntimeConfig("config/runtime.yml")  # loaded at startup, before the dashboard edit
        client.post("/api/runtime/channels/add", data={"channel_id": "444"}, headers=ORIGIN)
        bot.add_channel(555, "Dango HQ", "bots")
        assert _file(workdir)["allowed_channels"] == [111, 222, 444, 555]
        assert bot.allowed_channels == {111, 222, 444, 555}

    def test_dashboard_change_keeps_bot_edits(self, client, workdir):
        _write(workdir, EXISTING)
        RuntimeConfig("config/runtime.yml").add_user(666, "dave")
        client.post("/api/runtime/settings", headers=ORIGIN, data={
            "timezone": "UTC", "discord_activity": "Idle", "history_limit": "5",
        })
        data = _file(workdir)
        assert data["allowed_users"] == [333, 666]
        assert data["user_metadata"]["666"] == {"username": "dave"}

    def test_both_sides_write_the_same_format(self, client, workdir):
        _write(workdir, EXISTING)
        client.post("/api/runtime/channels/add", data={"channel_id": "444"}, headers=ORIGIN)
        text = (workdir / "config" / "runtime.yml").read_text(encoding="utf-8")
        assert text.startswith("# Runtime configuration - can be modified via Discord commands\n")
        assert "  - 111  # Dango HQ / #general\n" in text
        assert [p.name for p in (workdir / "config").iterdir()] == ["runtime.yml"]  # no temp file left

    def test_bot_remove_channel_drops_metadata(self, workdir):
        rc = RuntimeConfig("config/runtime.yml")
        rc.add_channel(1, "S", "c")
        rc.remove_channel(1)
        assert _file(workdir)["channel_metadata"] == {}


class TestUnreadableFile:
    @pytest.fixture
    def corrupt(self, workdir):
        path = workdir / "config" / "runtime.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CORRUPT, encoding="utf-8")
        return path

    def test_dashboard_shows_the_error(self, client, corrupt):
        html = client.get("/discord").text
        assert "runtime.yml is not valid YAML" in html

    @pytest.mark.parametrize("path, data", [
        ("/api/runtime/channels/add", {"channel_id": "444"}),
        ("/api/runtime/channels/111/delete", {}),
        ("/api/runtime/users/add", {"user_id": "555"}),
        ("/api/runtime/settings", {"timezone": "UTC", "discord_activity": "x", "history_limit": "5"}),
    ])
    def test_dashboard_never_overwrites_it(self, client, corrupt, path, data):
        r = client.post(path, data=data, headers=ORIGIN)
        assert "not valid YAML" in r.text
        assert corrupt.read_text(encoding="utf-8") == CORRUPT

    def test_bot_reports_it_on_first_use_not_on_import(self, corrupt):
        from dango.utils.runtime_config import RuntimeConfigError

        rc = RuntimeConfig("config/runtime.yml")  # must not raise
        with pytest.raises(RuntimeConfigError, match="not valid YAML"):
            rc.allowed_channels

    def test_bot_keeps_last_good_values_and_refuses_to_save(self, workdir):
        from dango.utils.runtime_config import RuntimeConfigError

        _write(workdir, EXISTING)
        rc = RuntimeConfig("config/runtime.yml")
        (workdir / "config" / "runtime.yml").write_text(CORRUPT, encoding="utf-8")
        with pytest.raises(RuntimeConfigError):
            rc.add_channel(444)
        assert (workdir / "config" / "runtime.yml").read_text(encoding="utf-8") == CORRUPT
        assert rc.allowed_channels == {111, 222}


class TestValidation:
    @pytest.mark.parametrize("form, message", [
        ({"timezone": "Taipei"}, "Unknown timezone &#x27;Taipei&#x27;"),
        ({"discord_activity": "x" * 129}, "at most 128 characters"),
        ({"history_limit": "0"}, "History limit must be at least 1."),
        ({"history_limit": "abc"}, "History limit must be a whole number."),
    ])
    def test_dashboard_rejects_bad_settings(self, client, workdir, form, message):
        _write(workdir, EXISTING)
        data = {"timezone": "UTC", "discord_activity": "ok", "history_limit": "5", **form}
        r = client.post("/api/runtime/settings", data=data, headers=ORIGIN)
        assert message in r.text
        saved = _file(workdir)
        assert (saved["timezone"], saved["discord_activity"], saved["history_limit"]) == ("Asia/Taipei", "Coding", 20)

    def test_bot_setters_validate_too(self, workdir):
        rc = RuntimeConfig("config/runtime.yml")
        for call in (lambda: rc.set_timezone("Mars/Base"),
                     lambda: rc.set_discord_activity("x" * 129),
                     lambda: rc.set_history_limit(0)):
            with pytest.raises(ValueError):
                call()
        assert (rc.timezone, rc.history_limit) == ("UTC", 12)

    def test_sethistorylimit_reports_the_rule(self, workdir):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from dango.commands.admin_commands import AdminCog

        cog = AdminCog(SimpleNamespace(), RuntimeConfig("config/runtime.yml"))
        interaction = SimpleNamespace(guild=object(), response=SimpleNamespace(send_message=AsyncMock()))
        asyncio.run(AdminCog.sethistorylimit.callback(cog, interaction, limit=0))
        interaction.response.send_message.assert_awaited_once_with(
            "❌ History limit must be at least 1.", ephemeral=True
        )


# ── Picking up edits while running ────────────────────────────────────────────

def _bump_mtime(path: Path) -> None:
    """Make sure the next read sees a changed file, however fast the test runs."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


class TestLiveReload:
    def test_hand_edit_is_picked_up_on_next_read(self, workdir):
        _write(workdir, EXISTING)
        bot = RuntimeConfig("config/runtime.yml")
        _write(workdir, {**EXISTING, "allowed_channels": [999], "timezone": "Europe/Berlin"})
        _bump_mtime(workdir / "config" / "runtime.yml")
        assert bot.allowed_channels == {999}
        assert bot.timezone == "Europe/Berlin"

    def test_dashboard_edit_is_picked_up_without_a_restart(self, client, workdir):
        _write(workdir, EXISTING)
        bot = RuntimeConfig("config/runtime.yml")
        client.post("/api/runtime/channels/add", data={"channel_id": "444"}, headers=ORIGIN)
        _bump_mtime(workdir / "config" / "runtime.yml")
        assert 444 in bot.allowed_channels

    def test_broken_edit_keeps_last_good_settings_until_fixed(self, workdir, capsys):
        path = workdir / "config" / "runtime.yml"
        _write(workdir, EXISTING)
        bot = RuntimeConfig("config/runtime.yml")

        path.write_text(CORRUPT, encoding="utf-8")
        _bump_mtime(path)
        assert bot.allowed_channels == {111, 222}
        assert bot.timezone == "Asia/Taipei"
        assert capsys.readouterr().out.count("Keeping the last good settings") == 1

        _write(workdir, {**EXISTING, "allowed_channels": [5]})
        _bump_mtime(path)
        assert bot.allowed_channels == {5}

    def test_unchanged_file_is_not_reread(self, workdir, monkeypatch):
        _write(workdir, EXISTING)
        bot = RuntimeConfig("config/runtime.yml")
        reads = []
        original = RuntimeConfig._read
        monkeypatch.setattr(RuntimeConfig, "_read", lambda self: reads.append(1) or original(self))
        for _ in range(5):
            bot.allowed_channels
        assert reads == []
