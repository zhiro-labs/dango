"""
Tests that the dashboard's hand-built HTML fragments escape their data.

These fragments are f-strings, not auto-escaped Jinja templates, and they show
Discord server/channel/user names (set by whoever owns that server or account)
plus values from config.yaml / runtime.yml.
"""

import pytest

from web import main as web_main

PAYLOAD = '<img src=x onerror="alert(1)">'
ESCAPED = "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"


def _assert_escaped(html: str) -> None:
    assert "<img" not in html
    assert ESCAPED in html


class TestRuntimeLists:
    def test_channel_metadata_is_escaped(self):
        rt = {
            "allowed_channels": [123],
            "channel_metadata": {"123": {"server": PAYLOAD, "channel": PAYLOAD}},
        }
        _assert_escaped(web_main._render_channel_list(rt))

    def test_username_is_escaped(self):
        rt = {"allowed_users": [456], "user_metadata": {"456": {"username": PAYLOAD}}}
        _assert_escaped(web_main._render_user_list(rt))

    def test_hand_edited_ids_cannot_break_out_of_attributes(self):
        # IDs normally come from Discord as ints, but runtime.yml is editable.
        evil_id = '1" hx-post="/api/shutdown'
        html = web_main._render_channel_list({"allowed_channels": [evil_id]})
        assert 'hx-post="/api/shutdown' not in html
        assert "1&quot; hx-post=&quot;/api/shutdown" in html

    def test_plain_names_render_unchanged(self):
        rt = {
            "allowed_channels": [123],
            "channel_metadata": {"123": {"server": "Dango HQ", "channel": "general"}},
        }
        html = web_main._render_channel_list(rt)
        assert ">Dango HQ / #general</p>" in html
        assert 'hx-post="/api/runtime/channels/123/delete"' in html


class TestToolLists:
    def test_custom_api_fields_are_escaped(self):
        apis = [{"name": PAYLOAD, "base_url": PAYLOAD, "description": PAYLOAD}]
        html = web_main._render_api_list(apis)
        _assert_escaped(html)
        assert html.count(ESCAPED) == 3

    def test_sql_database_fields_are_escaped(self):
        dbs = [{"name": PAYLOAD, "db_url": f"sqlite:///{PAYLOAD}", "description": PAYLOAD}]
        html = web_main._render_db_list(dbs)
        _assert_escaped(html)
        assert html.count(ESCAPED) == 3

    def test_db_password_is_still_masked(self):
        html = web_main._render_db_list([{"name": "db", "db_url": "postgresql://u:secret@h/db"}])
        assert "secret" not in html
        assert "postgresql://u:***@h/db" in html


def test_discord_page_renders_names_escaped(monkeypatch):
    """End to end: discord.html inserts these fragments with `| safe`."""
    from starlette.testclient import TestClient

    from web.config_store import BotConfig

    rt = {
        "allowed_channels": [123], "allowed_users": [456],
        "channel_metadata": {"123": {"server": PAYLOAD, "channel": "general"}},
        "user_metadata": {"456": {"username": PAYLOAD}},
        "timezone": "UTC", "discord_activity": "Surfing", "history_limit": 12,
    }
    monkeypatch.setattr(web_main, "is_setup_complete", lambda: True)
    monkeypatch.setattr(web_main, "load_config", lambda: BotConfig())
    monkeypatch.setattr(web_main, "_load_runtime", lambda: rt)

    r = TestClient(web_main.app, base_url="http://localhost:17860").get("/discord")
    assert r.status_code == 200
    assert PAYLOAD not in r.text
    assert r.text.count(ESCAPED) == 2


@pytest.mark.parametrize("value", [None, 0, "a & b"])
def test_esc_handles_non_strings(value):
    assert web_main._esc(value) == {None: "", 0: "0", "a & b": "a &amp; b"}[value]
