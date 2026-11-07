import asyncio
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app import anthropic_chat, chat
from app.main import app


def block(kind, **fields):
    return SimpleNamespace(type=kind, **fields)


def message(content, stop="end_turn", tokens=(1000, 200)):
    return SimpleNamespace(content=content, stop_reason=stop, usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]))


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=lambda o: o.__dict__)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_client(*responses):
    return SimpleNamespace(messages=FakeMessages(responses))


def test_request_uses_claude_shapes():
    client = fake_client(message([block("text", text="Hi")]))
    convo = anthropic_chat.ClaudeConversation("system text", [{"role": "user", "content": "earlier"}], "now", chat.ACTIONS, client=client)
    turn = asyncio.run(convo.ask())
    request = client.messages.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == "system text"
    assert request["output_config"] == {"effort": "low"}
    assert "temperature" not in request
    assert request["messages"][-1] == {"role": "user", "content": "now"}
    assert {tool["name"] for tool in request["tools"]} == {a["function"]["name"] for a in chat.ACTIONS}
    assert all("input_schema" in tool for tool in request["tools"])
    assert turn == {"text": "Hi", "calls": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}


def test_tool_results_follow_claude_format():
    thinking = block("thinking", thinking="", signature="s")
    use = block("tool_use", id="tu_1", name="get_tool_details", input={"tool_id": "jobber"})
    client = fake_client(message([thinking, use], stop="tool_use"), message([block("text", text="Done")]))
    convo = anthropic_chat.ClaudeConversation("s", [], "q", chat.ACTIONS, client=client)
    turn = asyncio.run(convo.ask())
    assert turn["calls"] == [{"id": "tu_1", "name": "get_tool_details", "arguments": {"tool_id": "jobber"}}]
    convo.add_results([("tu_1", '{"ok": true}')])
    assert convo.messages[-2]["content"] == [thinking, use]
    assert convo.messages[-1] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": '{"ok": true}'}]}


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_and_cutoff_return_no_actions(stop):
    client = fake_client(message([block("tool_use", id="x", name="get_tool_details", input={})], stop=stop))
    turn = asyncio.run(anthropic_chat.ClaudeConversation("s", [], "q", chat.ACTIONS, client=client).ask())
    assert turn["calls"] == [] and turn["text"] == ""


@pytest.fixture
def claude_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("CHAT_SPEND_PATH", str(tmp_path / "spend.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_PROVIDER", raising=False)
    monkeypatch.setattr(chat, "limiter", chat.DailyLimiter())
    with TestClient(app) as test_client:
        yield test_client


def use_fake(monkeypatch, client):
    original = anthropic_chat.ClaudeConversation.__init__

    def init(self, system, history, message_text, actions, client_arg=None):
        original(self, system, history, message_text, actions, client=client)

    monkeypatch.setattr(anthropic_chat.ClaudeConversation, "__init__", init)


def events_of(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_end_to_end_with_claude_provider(claude_app, monkeypatch):
    client = fake_client(
        message([block("tool_use", id="tu_1", name="recommend_tools", input={"problem_id": "bookkeeping"})], stop="tool_use"),
        message([block("text", text="You're covered.")]),
    )
    use_fake(monkeypatch, client)
    assert claude_app.get("/api/chat/status").json() == {"available": True}
    response = claude_app.post("/api/chat", json={"conversation_id": "c", "message": "books", "memory": {"background_done": True, "owned": ["quickbooks_online"]}})
    events = events_of(response)
    assert any(e["type"] == "recommendation" for e in events)
    assert next(e for e in events if e["type"] == "message_delta")["text"] == "You're covered."
    second = client.messages.requests[1]["messages"][-1]["content"][0]
    assert second["type"] == "tool_result" and second["tool_use_id"] == "tu_1"
    assert chat.ledger().total() == pytest.approx(2 * (1000 * 0.10 + 200 * 0.50) / 1_000_000)


def test_claude_api_error_falls_back(claude_app, monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(request=request)
    use_fake(monkeypatch, fake_client(error))
    response = claude_app.post("/api/chat", json={"conversation_id": "c", "message": "hi"})
    assert "claude-test-key" not in response.text
    assert next(e for e in events_of(response) if e["type"] == "error")["fallback"] is True
