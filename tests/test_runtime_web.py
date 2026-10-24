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
