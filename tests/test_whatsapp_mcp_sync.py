import asyncio
import json
from types import SimpleNamespace

import pytest

from ChannelsWorker import sync_channels_to_stand as sync


def _result(rows, *, error=False):
    return SimpleNamespace(
        isError=error,
        structuredContent=None,
        content=[SimpleNamespace(type="text", text=json.dumps(row)) for row in rows],
    )


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.pages[arguments["page"]]


def test_metadata_pagination_and_no_message_request():
    rows = [
        {"jid": "first@s.whatsapp.net", "name": "First", "last_message_time": "2026-11-04T10:00:00Z", "last_message": None},
        {"jid": "second@s.whatsapp.net", "name": None, "last_message_time": None, "last_message": None},
    ]
    session = FakeSession([_result(rows), _result([])])
    chats = asyncio.run(sync.fetch_whatsapp_mcp_chats(session, page_size=2))
    assert len(chats) == 2
    assert chats[0]["last_active"] == 1793786400
    assert chats[1]["name"] == "second@s.whatsapp.net"
    assert [args["page"] for _, args in session.calls] == [0, 1]
    assert all(name == "list_chats" and args["include_last_message"] is False for name, args in session.calls)


@pytest.mark.parametrize("pages", [
    [_result([])],
    [_result([{"jid": "a", "name": "A"}, {"jid": "b", "name": "B"}]), _result([], error=True)],
    [_result([{"jid": "a", "last_message": "private text"}])],
    [_result([{"name": "missing jid"}])],
    [_result([{"jid": "a", "name": {"unexpected": "value"}}])],
    [_result([{"jid": "a", "last_message_time": 123}])],
    [_result([{"jid": "a"}, {"jid": "a"}])],
])
def test_incomplete_or_unsafe_metadata_never_returns_chats(pages):
    with pytest.raises(ValueError):
        asyncio.run(sync.fetch_whatsapp_mcp_chats(FakeSession(pages), page_size=2))


def test_status_count_requires_positive_integer():
    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    class Client:
        def __init__(self, body):
            self.body = body

        async def get(self, url):
            assert url == "https://example.test/status"
            return Response(self.body)

    assert asyncio.run(sync.whatsapp_mcp_chat_count(Client({"chats": 52}), "https://example.test/status")) == 52
    for bad in (None, 0, True, "52"):
        with pytest.raises(ValueError):
            asyncio.run(sync.whatsapp_mcp_chat_count(Client({"chats": bad}), "https://example.test/status"))


def test_external_mcp_takes_precedence_over_legacy_empty_db(monkeypatch, capsys):
    sync.STAND_CHANNEL_SYNC_KEY = "synthetic"
    monkeypatch.setenv("SYNC_WA_MCP_URL", "https://example.test/mcp")
    monkeypatch.setenv("SYNC_WA_MCP_TOKEN", "synthetic")
    monkeypatch.delenv("SYNC_LOOP_INTERVAL", raising=False)
    monkeypatch.setattr(sync, "ACCOUNTS", [
        {"name": "Елизавета", "required": True, "tg_session_file": "synthetic", "tg_api_id": 1,
         "tg_api_hash": "synthetic", "wa_db_path": "/legacy/empty.db", "wa_api_url": None},
    ])
    called = []
    monkeypatch.setattr(sync, "sync_telegram", lambda *args: called.append("tg"))
    monkeypatch.setattr(sync.asyncio, "run", lambda value: value.close() if asyncio.iscoroutine(value) else None)
    monkeypatch.setattr(sync, "sync_whatsapp_mcp", lambda account, url, token: called.append((account, url, token)))
    monkeypatch.setattr(sync, "sync_whatsapp", lambda *args: called.append("legacy"))
    monkeypatch.setattr(sync, "sync_bitrix", lambda: called.append("bitrix"))
    assert sync.main() is True
    assert "legacy" not in called
    assert ("WhatsApp", "https://example.test/mcp", "synthetic") in called

    def fail_mcp(*args):
        raise RuntimeError("private response")

    monkeypatch.setattr(sync, "sync_whatsapp_mcp", fail_mcp)
    assert sync.main() is False
    assert "private response" not in capsys.readouterr().out
    assert "legacy" not in called
