"""Request guard for the web dashboard.

The dashboard has no login, so it must only answer requests that come from
the operator's own browser tab. Two attacks get around "it only listens on
localhost":

- DNS rebinding: a malicious site points its own domain at 127.0.0.1, so the
  browser treats the dashboard as same-origin with that site and lets it read
  pages and post forms. Blocked by allowing only known Host headers.
- CSRF: a page on any other site submits a form to http://localhost:17860.
  Browsers send an Origin header with every cross-site POST, so state-changing
  requests are rejected unless Origin (or Referer) matches the Host.

Requests with neither Origin nor Referer come from non-browser clients such as
curl, which cannot be driven by a web page, so they are allowed.
"""

import os
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _normalize_host(host: str) -> str:
    return host.strip().lower().strip("[]")


def allowed_hosts_from_env() -> frozenset[str]:
    """Default loopback names plus any extra hosts in WEB_ALLOWED_HOSTS."""
    extra = os.getenv("WEB_ALLOWED_HOSTS", "")
    return DEFAULT_ALLOWED_HOSTS | {_normalize_host(h) for h in extra.split(",") if h.strip()}


def _hostname(netloc: str) -> str:
    """'Example.com:17860' -> 'example.com', '[::1]:17860' -> '::1'."""
    try:
        return urlsplit(f"//{netloc}").hostname or ""
    except ValueError:
        return ""


def _netloc(url: str) -> str | None:
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return None


class DashboardGuard:
    """ASGI middleware enforcing the Host allowlist and same-origin writes."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str] | None = None):
        self.app = app
        self.allowed_hosts = (
            frozenset(_normalize_host(h) for h in allowed_hosts)
            if allowed_hosts is not None
            else allowed_hosts_from_env()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "")
        hostname = _hostname(host)

        if hostname not in self.allowed_hosts:
            print(f"🛡️ [web] Blocked request with Host {host!r}")
            response = PlainTextResponse(
                f"Host {hostname or host!r} is not allowed. Open the dashboard at "
                "http://localhost:<port>, or add this host to WEB_ALLOWED_HOSTS.",
                status_code=400,
            )
            await response(scope, receive, send)
            return

        if scope["method"] not in _SAFE_METHODS:
            source = headers.get("origin") or headers.get("referer")
            if source is not None and _netloc(source) != host.lower():
                print(f"🛡️ [web] Blocked cross-site {scope['method']} {scope['path']} from {source!r}")
                response = PlainTextResponse("Cross-site request blocked.", status_code=403)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
