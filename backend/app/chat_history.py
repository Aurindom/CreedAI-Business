"""Short-lived, account-scoped Penny history. No credentials or chat text are logged."""

import hashlib
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from datetime import datetime, timedelta, timezone
from functools import wraps
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError
from redis import asyncio as redis
from redis.exceptions import RedisError

from .chat import ChatMemory
from .schemas import MAX_QUESTION_CHOICES, Recommendation
from . import auth

router = APIRouter()
TTL_SECONDS = 300
ACTIVE_TTL_SECONDS = 86400
MAX_SNAPSHOT_BYTES = 128_000
ALLOWED_KINDS = {"user", "assistant", "clarify", "a2ui", "result", "sources", "error"}
PENNY_CATALOG = "https://mainstreet.ai/catalogs/penny/v1"


def _valid_question_surface(item: dict[str, Any]) -> bool:
    protocol = item.get("protocol")
    if not isinstance(protocol, list) or len(protocol) != 2:
        return False
    first, second = protocol
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    created = first.get("createSurface")
    updated = second.get("updateComponents")
    if first.get("version") != "v0.9" or second.get("version") != "v0.9":
        return False
    if not isinstance(created, dict) or not isinstance(updated, dict):
        return False
    surface_id = created.get("surfaceId")
    if (not isinstance(surface_id, str) or not surface_id.startswith("penny-question-")
            or len(surface_id) > 100 or created.get("catalogId") != PENNY_CATALOG
            or updated.get("surfaceId") != surface_id):
        return False
    components = updated.get("components")
    if not isinstance(components, list) or len(components) != 1 or not isinstance(components[0], dict):
        return False
    question = components[0]
    choices = question.get("choices")
    return (question.get("id") == "root" and question.get("component") == "PennyQuestion"
            and question.get("question") == item.get("text")
            and isinstance(item.get("text"), str) and 1 <= len(item["text"]) <= 200
            and isinstance(choices, list) and 2 <= len(choices) <= MAX_QUESTION_CHOICES
            and all(isinstance(choice, str) and 1 <= len(choice) <= 80 for choice in choices)
            and isinstance(question.get("progress", ""), str) and len(question.get("progress", "")) <= 30)


def _valid_recommendation_surface(item: dict[str, Any]) -> bool:
    protocol = item.get("protocol")
    if not isinstance(protocol, list) or len(protocol) != 2:
        return False
    first, second = protocol
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    created, updated = first.get("createSurface"), second.get("updateComponents")
    if (first.get("version") != "v0.9" or second.get("version") != "v0.9"
            or not isinstance(created, dict) or not isinstance(updated, dict)):
        return False
    surface_id = created.get("surfaceId")
    if (not isinstance(surface_id, str) or not surface_id.startswith("penny-recommendation-")
            or len(surface_id) > 100 or created.get("catalogId") != PENNY_CATALOG
            or updated.get("surfaceId") != surface_id):
        return False
    components = updated.get("components")
    if not isinstance(components, list) or len(components) != 1 or not isinstance(components[0], dict):
        return False
    component = components[0]
    if component.get("id") != "root" or component.get("component") != "PennyRecommendation":
        return False
    if not isinstance(component.get("problemTitle"), str) or len(component["problemTitle"]) > 200:
        return False
    if "taskPurpose" in component and (not isinstance(component["taskPurpose"], str) or len(component["taskPurpose"]) > 200):
        return False
    try:
        recommendation = Recommendation.model_validate(component.get("recommendation"))
    except ValidationError:
        return False
    expected = {option.tool_id: option.status for option in [*recommendation.options, *recommendation.check_first]}
    return (component.get("statuses") == expected
            and item.get("text") == recommendation.message
            and isinstance(item.get("text"), str) and len(item["text"]) <= 2000)


def _valid_simple_surface(item: dict[str, Any], surface: str, component_name: str) -> bool:
    protocol = item.get("protocol")
    if not isinstance(protocol, list) or len(protocol) != 2:
        return False
    first, second = protocol
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    created, updated = first.get("createSurface"), second.get("updateComponents")
    if (first.get("version") != "v0.9" or second.get("version") != "v0.9"
            or not isinstance(created, dict) or not isinstance(updated, dict)):
        return False
    surface_id = created.get("surfaceId")
    if (not isinstance(surface_id, str) or not surface_id.startswith(f"penny-{surface}-")
            or len(surface_id) > 100 or created.get("catalogId") != PENNY_CATALOG
            or updated.get("surfaceId") != surface_id):
        return False
    components = updated.get("components")
    if not isinstance(components, list) or len(components) != 1 or not isinstance(components[0], dict):
        return False
    payload = components[0]
    if payload.get("id") != "root" or payload.get("component") != component_name:
        return False
    if surface == "text":
        return (isinstance(payload.get("text"), str) and payload["text"] == item.get("text")
                and 1 <= len(payload["text"]) <= 2000)
    sources = payload.get("items")
    return (item.get("text") in ("Sources for this comparison", "Sources for this tool")
            and isinstance(sources, list) and len(sources) <= 6
            and all(isinstance(source, dict) and isinstance(source.get("title"), str)
                    and len(source["title"]) <= 200 and isinstance(source.get("url"), str)
                    and urlparse(source["url"]).scheme in ("http", "https")
                    and isinstance(source.get("checked", ""), str) for source in sources))


def _valid_surface(item: dict[str, Any]) -> bool:
    return (_valid_question_surface(item) or _valid_recommendation_surface(item)
            or _valid_simple_surface(item, "text", "PennyText")
            or _valid_simple_surface(item, "sources", "PennySources"))


class ChatSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversationId: str = Field(min_length=1, max_length=100)
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    memory: ChatMemory = Field(default_factory=ChatMemory)

    @model_validator(mode="after")
    def validate_messages(self):
        for item in self.messages:
            if (not isinstance(item.get("id"), str) or len(item["id"]) > 100
                    or item.get("kind") not in ALLOWED_KINDS):
                raise ValueError("Invalid chat message")
            if "text" in item and (not isinstance(item["text"], str) or len(item["text"]) > 2000):
                raise ValueError("Invalid chat text")
            kind = item["kind"]
            if kind in ("user", "assistant", "clarify", "error") and not isinstance(item.get("text"), str):
                raise ValueError("Missing chat text")
            if kind == "result":
                try:
                    Recommendation.model_validate(item.get("recommendation"))
                except ValidationError:
                    raise ValueError("Invalid chat result") from None
                if not isinstance(item.get("statuses"), dict):
                    raise ValueError("Invalid chat result statuses")
            if kind == "sources":
                sources = item.get("items")
                if not isinstance(sources, list) or len(sources) > 6:
                    raise ValueError("Invalid chat sources")
                for source in sources:
                    if (not isinstance(source, dict) or not isinstance(source.get("url"), str)
                            or urlparse(source["url"]).scheme not in ("http", "https")
                            or not isinstance(source.get("title"), str) or len(source["title"]) > 200):
                        raise ValueError("Invalid chat source")
            if kind == "clarify":
                choices = item.get("choices")
                if not isinstance(choices, list) or len(choices) > MAX_QUESTION_CHOICES or any(not isinstance(choice, str) or len(choice) > 80 for choice in choices):
                    raise ValueError("Invalid chat choices")
            if item["kind"] == "a2ui" and not _valid_surface(item):
                raise ValueError("Invalid chat surface")
        if len(self.model_dump_json().encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Chat history is too large")
        return self


def now():
    return datetime.now(timezone.utc)


def _configuration():
    url = os.environ.get('REDIS_URL', '')
    if urlparse(url).scheme not in ('redis', 'rediss'):
        raise HTTPException(503, 'Conversation storage is unavailable')
    return url


def _cache():
    return redis.from_url(_configuration(), decode_responses=True, socket_timeout=3)


def _key(user_id, conversation_id):
    digest = hashlib.sha256((user_id + ':' + conversation_id).encode()).hexdigest()
    return 'penny:conversation:' + digest


def _touch(request, principal, conversation_id):
    auth.check_active(request, principal)
    with request.app.state.lock, request.app.state.conn:
        changed = request.app.state.conn.execute('UPDATE chat_conversation SET session_id=?,updated_at=?,recover_until=NULL WHERE user_id=? AND conversation_id=? AND (recover_until IS NULL OR recover_until>?)',
                                      (principal.session_id, now().isoformat(), principal.user_id, conversation_id, now().isoformat()))
        if changed.rowcount != 1:
            raise HTTPException(409, 'This conversation expired. Start a new conversation.')
        request.app.state.conn.execute('INSERT OR IGNORE INTO chat_session_usage VALUES(?,?,?)',
                                      (principal.user_id, conversation_id, principal.session_id))


def serialized(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        request = kwargs['request']
        async with request.app.state.history_lock:
            return await function(*args, **kwargs)
    return wrapped


@router.get('/api/chat/history')
@serialized
async def load_history(request: Request, conversation_id: str | None = Query(default=None, max_length=100),
                       principal: auth.Principal = Depends(auth.require_account)):
    with request.app.state.lock:
        sql = 'SELECT conversation_id FROM chat_conversation WHERE user_id=? AND (recover_until IS NULL OR recover_until>?)'
        args = [principal.user_id, now().isoformat()]
        if conversation_id is not None:
            sql += ' AND conversation_id=?'
            args.append(conversation_id)
        row = request.app.state.conn.execute(sql + ' ORDER BY updated_at DESC LIMIT 1', args).fetchone()
    if row is None:
        return Response('null', media_type='application/json', headers={'Cache-Control': 'no-store'})
    client = _cache()
    try:
        stored = await client.get(_key(principal.user_id, row[0]))
        if stored:
            snapshot = ChatSnapshot.model_validate_json(stored)
            if snapshot.conversationId != row[0]:
                raise ValueError('cache binding mismatch')
            auth.check_active(request, principal)
            _touch(request, principal, row[0])
            await client.expire(_key(principal.user_id, row[0]), ACTIVE_TTL_SECONDS)
    except (RedisError, ValueError):
        raise HTTPException(503, 'Conversation storage is unavailable') from None
    finally:
        await client.aclose()
    return Response(stored or 'null', media_type='application/json', headers={'Cache-Control': 'no-store'})


@router.put('/api/chat/history', status_code=204)
@serialized
async def save_history(request: Request, snapshot: ChatSnapshot,
                       principal: auth.Principal = Depends(auth.require_account)):
    client = _cache()
    try:
        auth.check_active(request, principal)
        with request.app.state.lock, request.app.state.conn:
            conn = request.app.state.conn
            existing = conn.execute('SELECT 1 FROM chat_conversation WHERE user_id=? AND conversation_id=?', (principal.user_id, snapshot.conversationId)).fetchone()
            count = conn.execute('SELECT COUNT(*) FROM chat_conversation WHERE user_id=?', (principal.user_id,)).fetchone()[0]
            if not existing and count >= 20:
                # Drop metadata whose temporary content has already expired.
                conn.execute('DELETE FROM chat_conversation WHERE user_id=? AND (recover_until<=? OR updated_at<?)',
                             (principal.user_id, now().isoformat(), (now()-timedelta(seconds=ACTIVE_TTL_SECONDS)).isoformat()))
                count = conn.execute('SELECT COUNT(*) FROM chat_conversation WHERE user_id=?', (principal.user_id,)).fetchone()[0]
                if count >= 20:
                    raise HTTPException(409, 'Too many active conversations')
            conn.execute('INSERT OR IGNORE INTO chat_conversation VALUES(?,?,?,?,NULL)',
                         (principal.user_id, snapshot.conversationId, principal.session_id, now().isoformat()))
        _touch(request, principal, snapshot.conversationId)
        await client.set(_key(principal.user_id, snapshot.conversationId), snapshot.model_dump_json(), ex=ACTIVE_TTL_SECONDS)
        auth.check_active(request, principal)
    except RedisError:
        raise HTTPException(503, 'Conversation storage is unavailable') from None
    finally:
        await client.aclose()
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})


@router.post('/api/auth/logout')
@serialized
async def logout(request: Request, principal: auth.Principal = Depends(auth.require_account)):
    auth.check_active(request, principal)
    current = now()
    deadline = (current + timedelta(seconds=TTL_SECONDS)).isoformat()
    with request.app.state.lock, request.app.state.conn:
        conn = request.app.state.conn
        conn.execute('INSERT OR IGNORE INTO revoked_auth_session VALUES(?,?,?)',
                     (principal.session_id, principal.user_id, current.isoformat()))
        rows = conn.execute('SELECT conversation_id FROM chat_session_usage WHERE user_id=? AND session_id=?',
                            (principal.user_id, principal.session_id)).fetchall()
        conn.execute('DELETE FROM chat_session_usage WHERE user_id=? AND session_id=?', (principal.user_id, principal.session_id))
        expire = []
        for (conversation,) in rows:
            active = conn.execute('SELECT 1 FROM chat_session_usage WHERE user_id=? AND conversation_id=?', (principal.user_id, conversation)).fetchone()
            if not active:
                conn.execute('UPDATE chat_conversation SET recover_until=? WHERE user_id=? AND conversation_id=?', (deadline, principal.user_id, conversation))
                expire.append(conversation)
    confirmed = True
    if expire:
        client = None
        try:
            client = _cache()
            for conversation in expire:
                await client.expire(_key(principal.user_id, conversation), TTL_SECONDS)
        except (RedisError, HTTPException):
            # SQLite deadline still prevents recovery after the five-minute window.
            confirmed = False
        finally:
            if client is not None:
                await client.aclose()
    return {'signed_out': True, 'cache_grace_seconds': TTL_SECONDS, 'cache_expiry_confirmed': confirmed}
