"""Account isolation and five-minute chat cache behavior."""

from types import SimpleNamespace

import pytest

from app import chat, chat_history
from app.schemas import BusinessProfile


class FakeRedis:
    def __init__(self, clock):
        self.clock = clock
        self.items = {}

    async def get(self, key):
        value = self.items.get(key)
        return value[0] if value and value[1] > self.clock[0] else None

    async def set(self, key, value, ex):
        self.items[key] = (value, self.clock[0] + ex)

    async def aclose(self):
        pass


def test_chat_history_restores_only_same_account_within_five_minutes(client, monkeypatch):
    clock = [0]
    cache = FakeRedis(clock)

    async def user(authorization):
        if authorization not in ("Bearer alice-first-session", "Bearer alice-new-session", "Bearer bob"):
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Sign in to access chat history")
        owner = "alice" if "alice" in authorization else "bob"
        return owner, "redis://test"

    monkeypatch.setattr(chat_history, "_user_id", user)
    monkeypatch.setattr(chat_history.redis, "from_url", lambda *args, **kwargs: cache)
    snapshot = {"conversationId": "c-1", "messages": [{"id": "m1", "kind": "user", "text": "Missed calls at my bakery"}], "memory": {"trade": "bakery"}}
    first = {"Authorization": "Bearer alice-first-session"}
    later = {"Authorization": "Bearer alice-new-session"}
    bob = {"Authorization": "Bearer bob"}

    assert client.put("/api/chat/history", json=snapshot, headers=first).status_code == 204
    assert client.get("/api/chat/history", headers=bob).json() is None
    clock[0] = 299
    restored = client.get("/api/chat/history", headers=later)
    assert restored.json()["messages"][0]["text"] == "Missed calls at my bakery"
    assert restored.headers["Cache-Control"] == "no-store"
    assert "alice" not in next(iter(cache.items))
    clock[0] = 300
    assert client.get("/api/chat/history", headers=later).json() is None


def test_invalid_snapshot_is_not_cached(client, monkeypatch):
    cache = FakeRedis([0])

    async def user(_authorization):
        return "alice", "redis://test"

    monkeypatch.setattr(chat_history, "_user_id", user)
    monkeypatch.setattr(chat_history.redis, "from_url", lambda *args, **kwargs: cache)
    bad = {"conversationId": "c", "messages": [{"id": "m", "kind": "loading", "text": "Private"}]}
    assert client.put("/api/chat/history", json=bad).status_code == 422
    assert cache.items == {}


def test_cache_rejects_unapproved_a2ui_component(client, monkeypatch):
    cache = FakeRedis([0])

    async def user(_authorization):
        return "alice", "redis://test"

    monkeypatch.setattr(chat_history, "_user_id", user)
    monkeypatch.setattr(chat_history.redis, "from_url", lambda *args, **kwargs: cache)
    forged = {"conversationId": "c", "messages": [{"id": "m", "kind": "a2ui", "text": "Choose", "protocol": [
        {"version": "v0.9", "createSurface": {"surfaceId": "penny-question-1", "catalogId": "https://mainstreet.ai/catalogs/penny/v1"}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "penny-question-1", "components": [{"id": "root", "component": "HTML", "html": "<script>alert(1)</script>"}]}},
    ]}]}
    assert client.put("/api/chat/history", json=forged).status_code == 422
    assert cache.items == {}


def test_cache_accepts_catalog_recommendation_surface(client, monkeypatch):
    cache = FakeRedis([0])

    async def user(_authorization):
        return "alice", "redis://test"

    monkeypatch.setattr(chat_history, "_user_id", user)
    monkeypatch.setattr(chat_history.redis, "from_url", lambda *args, **kwargs: cache)
    action = chat._run_action(client.app.state.catalog, "recommend_tools", {"problem_id": "bookkeeping"}, BusinessProfile(), chat.ChatMemory())
    event = next(event for event in action.events if event["type"] == "a2ui")
    snapshot = {"conversationId": "c", "messages": [{"id": "m", "kind": "a2ui", "surface": "recommendation", "text": event["message"], "protocol": event["messages"]}]}
    assert client.put("/api/chat/history", json=snapshot).status_code == 204
    assert client.get("/api/chat/history").json()["messages"][0]["protocol"] == event["messages"]
    snapshot["messages"][0]["protocol"][1]["updateComponents"]["components"][0]["component"] = "HTML"
    assert client.put("/api/chat/history", json=snapshot).status_code == 422


def test_cache_restores_a2ui_answer_and_sources(client, monkeypatch):
    cache = FakeRedis([0])

    async def user(_authorization):
        return "alice", "redis://test"

    monkeypatch.setattr(chat_history, "_user_id", user)
    monkeypatch.setattr(chat_history.redis, "from_url", lambda *args, **kwargs: cache)
    answer = chat._a2ui_event("text", "PennyText", {"text": "Here is what the catalog says."}, "Here is what the catalog says.")
    sources = chat._a2ui_event("sources", "PennySources", {"items": [{"title": "Vendor", "url": "https://example.com", "checked": ""}]}, "Sources for this tool")
    snapshot = {"conversationId": "c", "messages": [
        {"id": "m1", "kind": "a2ui", "surface": "text", "text": answer["message"], "protocol": answer["messages"]},
        {"id": "m2", "kind": "a2ui", "surface": "sources", "text": sources["message"], "protocol": sources["messages"]},
    ]}
    assert client.put("/api/chat/history", json=snapshot).status_code == 204
    assert len(client.get("/api/chat/history").json()["messages"]) == 2


@pytest.mark.parametrize("status,expected", [(401, 401), (403, 401), (500, 503)])
def test_supabase_verification_fails_closed(monkeypatch, status, expected):
    from fastapi import HTTPException

    monkeypatch.setattr(chat_history, "_configuration", lambda: ("https://project.supabase.co", "publishable", "redis://test"))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers):
            assert url == "https://project.supabase.co/auth/v1/user"
            assert headers["Authorization"] == "Bearer example-token"
            return SimpleNamespace(status_code=status)

    monkeypatch.setattr(chat_history.httpx, "AsyncClient", lambda **kwargs: Client())
    with pytest.raises(HTTPException) as caught:
        import asyncio
        asyncio.run(chat_history._user_id("Bearer example-token"))
    assert caught.value.status_code == expected


def test_missing_auth_config_is_unavailable(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(HTTPException) as caught:
        chat_history._configuration()
    assert caught.value.status_code == 503
