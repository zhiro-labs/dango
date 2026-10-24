"""
Tests for image / sticker downloads in the history step (past messages).

The current-message path is covered end to end in test_call_agent.py.
"""

import asyncio
from types import SimpleNamespace

import aiohttp
import pytest

from dango.steps import fetch_history

BOT_ID = 1


class _FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status, self._body = status, body

    async def read(self):
        return self._body

    async def text(self):
        return self._body.decode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(bodies={}, fetched=[], broken=set())

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url):
            state.fetched.append(url)
            if url in state.broken:
                raise aiohttp.ClientError("network down")
            body = state.bodies.get(url)
            return _FakeResponse(200 if body is not None else 404, body or b"")

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    return state


def _attachment(filename, url, content_type):
    return SimpleNamespace(filename=filename, url=url, content_type=content_type)


def _sticker(name, url, fmt):
    return SimpleNamespace(name=name, url=url, format=SimpleNamespace(name=fmt) if fmt else None)


def _msg(msg_id, author_id=2, attachments=(), stickers=()):
    return SimpleNamespace(
        id=msg_id, author=SimpleNamespace(id=author_id),
        attachments=list(attachments), stickers=list(stickers),
    )


def test_history_images(http):
    http.bodies = {"u/a.png": b"A", "u/b.jpg": b"B"}
    http.broken = {"u/broken.png"}
    msgs = [
        _msg(10, attachments=[
            _attachment("a.png", "u/a.png", "image/png"),
            _attachment("doc.pdf", "u/doc.pdf", "application/pdf"),
            _attachment("dango_replaced_table_1_1.md", "u/t", "image/png"),
            _attachment("broken.png", "u/broken.png", "image/png"),
            _attachment("nomime", "u/nomime", None),
        ]),
        _msg(11, author_id=BOT_ID, attachments=[_attachment("bot.png", "u/bot.png", "image/png")]),
        _msg(12, attachments=[_attachment("b.jpg", "u/b.jpg", "image/jpeg")]),
        _msg(13, attachments=[_attachment("gone.png", "u/gone.png", "image/png")]),
    ]
    image_map = asyncio.run(fetch_history._download_image_attachments(msgs, BOT_ID))

    assert {k: [(i.content, i.mime_type) for i in v] for k, v in image_map.items()} == {
        10: [(b"A", "image/png")],
        12: [(b"B", "image/jpeg")],
    }
    assert http.fetched == ["u/a.png", "u/broken.png", "u/b.jpg", "u/gone.png"]


def test_history_stickers(http):
    http.bodies = {"s/wave.png": b"W", "s/cat.gif": b"C"}
    msgs = [
        _msg(20, stickers=[_sticker("wave", "s/wave.png", "apng"), _sticker("party", "s/p.json", "lottie")]),
        _msg(21, author_id=BOT_ID, stickers=[_sticker("bot", "s/bot.png", "png")]),
        _msg(22, stickers=[_sticker("", "s/cat.gif", "GIF"), _sticker("odd", "s/odd", None)]),
        _msg(23),
    ]
    sticker_map = asyncio.run(fetch_history._download_sticker_map(msgs, BOT_ID))

    assert {k: ([(i.content, i.mime_type) for i in v["images"]], v["names"]) for k, v in sticker_map.items()} == {
        20: ([(b"W", "image/png")], ["wave", "party"]),
        22: ([(b"C", "image/gif")], ["odd"]),
    }
    assert http.fetched == ["s/wave.png", "s/cat.gif"]


def test_deep_attachment_images(http):
    http.bodies = {
        "d/info.json": b'{"author_name": "Alice", "author_id": 42, "content": "hi"}',
        "d/pic.png": b"P",
    }
    http.broken = {"d/broken.png"}
    msgs = [_msg(30, author_id=BOT_ID, attachments=[
        _attachment("dango_deep_42.json", "d/info.json", "application/json"),
        _attachment("pic.png", "d/pic.png", "image/png"),
        _attachment("broken.png", "d/broken.png", "image/png"),
    ])]
    deep_map = asyncio.run(fetch_history._extract_deep_attachments(msgs))

    info = deep_map[30]
    assert (info["author_name"], info["content"]) == ("Alice", "hi")
    assert [(i.content, i.mime_type) for i in info["_images"]] == [(b"P", "image/png")]
