import asyncio
import logging
import threading

import httpx
import pytest

from app import chat
from app.agent import readiness
from test_chat_hermes import BODY, FakeHermes, answer, error_code, frames, hermes, texts  # noqa: F401

GATEWAY_KEY = 'fixture-gateway-client-key'
RESERVE = chat.DEFAULT_HERMES_RESERVE_USD


class FakeGateway:
    """Plays GET /gateway/status. Tests move `settled`, `held` and `reserved` the way real calls would."""

    def __init__(self):
        self.settled, self.held, self.reserved, self.status, self.reads = 1.80, 0.0, 0.0, 200, 0

    def handler(self, request: httpx.Request):
        assert request.url.path == '/gateway/status'
        assert request.headers['authorization'] == f'Bearer {GATEWAY_KEY}'
        self.reads += 1
        if self.status != 200:
            return httpx.Response(self.status, json={'error': 'down'})
        states = {'settled': {'count': 300, 'usd': self.settled}}
        if self.held:
            states['held'] = {'count': 1, 'usd': self.held}
        if self.reserved:
            states['reserved'] = {'count': 1, 'usd': self.reserved}
        return httpx.Response(200, json={'attempts': 301, 'by_state': states, 'refused': 0, 'tripped': False,
                                         'committed_usd': self.settled + self.held + self.reserved,
                                         'max_requests': 500, 'cap_usd': 4.0})


@pytest.fixture
def gateway(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setenv('MODEL_GATEWAY_URL', 'http://gateway:9999')
    monkeypatch.setenv('MODEL_GATEWAY_KEY', GATEWAY_KEY)
    real = httpx.AsyncClient
    transport = httpx.MockTransport(fake.handler)
    # The Hermes fake passes its own transport, which wins. Everything else reaches the gateway fake.
    monkeypatch.setattr(readiness.httpx, 'AsyncClient', lambda **kw: real(**{'transport': transport, **kw}))
    return fake


def spent():
    return chat.ledger().total()

