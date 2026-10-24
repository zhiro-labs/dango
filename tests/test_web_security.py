"""
Tests for the web dashboard's request guard (web/security.py).

The dashboard has no login, so it must refuse requests a malicious web page
can make the operator's browser send: DNS-rebinding requests (foreign Host
header) and cross-site form posts (foreign Origin / Referer).
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from web.security import DashboardGuard, allowed_hosts_from_env

LOCAL = "http://localhost:17860"


async def _ok(request):
    return PlainTextResponse("ok")


def _client(allowed_hosts=None, base_url=LOCAL) -> TestClient:
    app = Starlette(routes=[Route("/", _ok, methods=["GET", "POST", "DELETE"])])
    app.add_middleware(DashboardGuard, allowed_hosts=allowed_hosts)
    return TestClient(app, base_url=base_url)


class TestHostAllowlist:
    @pytest.mark.parametrize(
        "host", ["localhost:17860", "127.0.0.1:17860", "[::1]:17860", "LOCALHOST:8080", "localhost"]
    )
    def test_loopback_hosts_are_allowed(self, host):
        assert _client().get("/", headers={"host": host}).status_code == 200

    @pytest.mark.parametrize("host", ["evil.example", "evil.example:17860", "192.168.1.50:17860", ""])
    def test_other_hosts_are_rejected(self, host):
        # DNS rebinding: the browser sends the attacker's domain as Host.
        r = _client().get("/", headers={"host": host})
        assert r.status_code == 400
        assert "WEB_ALLOWED_HOSTS" in r.text

    def test_extra_hosts_from_env(self, monkeypatch):
        monkeypatch.setenv("WEB_ALLOWED_HOSTS", " 192.168.1.50 , Dango.Lan,[fd00::1] ")
        hosts = allowed_hosts_from_env()
        assert {"localhost", "127.0.0.1", "::1", "192.168.1.50", "dango.lan", "fd00::1"} <= hosts

        client = _client(allowed_hosts=hosts)
        assert client.get("/", headers={"host": "192.168.1.50:17860"}).status_code == 200
        assert client.get("/", headers={"host": "dango.lan"}).status_code == 200
        assert client.get("/", headers={"host": "[fd00::1]:17860"}).status_code == 200
        assert client.get("/", headers={"host": "evil.example"}).status_code == 400

    def test_env_unset_means_loopback_only(self, monkeypatch):
        monkeypatch.delenv("WEB_ALLOWED_HOSTS", raising=False)
        assert allowed_hosts_from_env() == {"localhost", "127.0.0.1", "::1"}


class TestSameOriginWrites:
    def test_same_origin_post_is_allowed(self):
        assert _client().post("/", headers={"origin": LOCAL}).status_code == 200

    def test_same_origin_referer_is_allowed(self):
        assert _client().post("/", headers={"referer": f"{LOCAL}/discord"}).status_code == 200

    def test_post_without_origin_or_referer_is_allowed(self):
        # curl and other non-browser clients; a web page cannot strip Origin.
        assert _client().post("/").status_code == 200

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.example",
            "http://localhost:3000",  # another local app on a different port
            "http://127.0.0.1:17860",  # same machine, but not the Host in use
            "null",  # sandboxed iframes and some redirects
            "http://[::1",  # malformed
        ],
    )
    def test_cross_site_origin_is_rejected(self, origin):
        assert _client().post("/", headers={"origin": origin}).status_code == 403

    def test_cross_site_referer_is_rejected(self):
        r = _client().post("/", headers={"referer": "https://evil.example/page"})
        assert r.status_code == 403

    def test_origin_wins_over_referer(self):
        headers = {"origin": "https://evil.example", "referer": f"{LOCAL}/"}
        assert _client().post("/", headers=headers).status_code == 403

    def test_other_unsafe_methods_are_checked(self):
        assert _client().delete("/", headers={"origin": "https://evil.example"}).status_code == 403

    def test_reads_are_not_origin_checked(self):
        # Cross-site GETs are harmless once the Host check passes: the browser
        # will not let the other site read the response.
        assert _client().get("/", headers={"origin": "https://evil.example"}).status_code == 200


@pytest.fixture(scope="module")
def app():
    from web.main import app
    return app


class TestDashboardApp:
    """The guard must be installed on the real dashboard app."""

    def test_foreign_host_is_rejected(self, app):
        r = TestClient(app, base_url="http://evil.example").get("/api/bot/status")
        assert r.status_code == 400

    def test_cross_site_post_never_reaches_handler(self, app):
        # Rejected before /api/shutdown runs, so nothing is stopped.
        r = TestClient(app, base_url=LOCAL).post(
            "/api/shutdown", headers={"origin": "https://evil.example"}
        )
        assert r.status_code == 403

    def test_local_requests_still_work(self, app):
        client = TestClient(app, base_url=LOCAL)
        assert client.get("/api/bot/status").status_code == 200
        r = client.post("/api/validate/discord", data={"token": " "}, headers={"origin": LOCAL})
        assert r.status_code == 200
        assert "Please enter a token" in r.text
