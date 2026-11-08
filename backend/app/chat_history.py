"""Short-lived, account-scoped Penny history. No credentials or chat text are logged."""

import hashlib
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError
from redis import asyncio as redis
from redis.exceptions import RedisError

from .chat import ChatMemory
from .schemas import Recommendation

router = APIRouter()
TTL_SECONDS = 300
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
            and isinstance(choices, list) and 2 <= len(choices) <= 4
            and all(isinstance(choice, str) and 1 <= len(choice) <= 80 for choice in choices)
            and isinstance(question.get("progress", ""), str) and len(question.get("progress", "")) <= 30)


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
                if not isinstance(choices, list) or len(choices) > 4 or any(not isinstance(choice, str) or len(choice) > 80 for choice in choices):
                    raise ValueError("Invalid chat choices")
            if item["kind"] == "a2ui" and not _valid_question_surface(item):
                raise ValueError("Invalid chat surface")
        if len(self.model_dump_json().encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Chat history is too large")
        return self


def _configuration() -> tuple[str, str, str]:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    publishable = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    cache_url = os.environ.get("REDIS_URL", "")
    parsed = urlparse(base)
    if (not publishable or urlparse(cache_url).scheme not in ("redis", "rediss")
            or parsed.scheme != "https" or not parsed.hostname):
        raise HTTPException(status_code=503, detail="Account history is unavailable")
    return base, publishable, cache_url


async def _user_id(authorization: str | None) -> tuple[str, str]:
    base, publishable, cache_url = _configuration()
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:]:
        raise HTTPException(status_code=401, detail="Sign in to access chat history")
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            result = await client.get(
                f"{base}/auth/v1/user",
                headers={"apikey": publishable, "Authorization": authorization},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Account verification is unavailable") from None
    if result.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Sign in to access chat history")
    if result.status_code != 200:
        raise HTTPException(status_code=503, detail="Account verification is unavailable")
    try:
        user_id = result.json()["id"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Account verification is unavailable") from None
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=503, detail="Account verification is unavailable")
    return user_id, cache_url


def _key(user_id: str) -> str:
    return f"penny:history:{hashlib.sha256(user_id.encode('utf-8')).hexdigest()}"


@router.get("/api/chat/history")
async def load_history(authorization: str | None = Header(default=None)) -> Response:
    user_id, cache_url = await _user_id(authorization)
    client = redis.from_url(cache_url, decode_responses=True, socket_timeout=3)
    try:
        stored = await client.get(_key(user_id))
    except RedisError:
        raise HTTPException(status_code=503, detail="Chat history is unavailable") from None
    finally:
        await client.aclose()
    return Response(content=stored or "null", media_type="application/json", headers={"Cache-Control": "no-store"})


@router.put("/api/chat/history", status_code=204)
async def save_history(snapshot: ChatSnapshot, authorization: str | None = Header(default=None)) -> Response:
    user_id, cache_url = await _user_id(authorization)
    client = redis.from_url(cache_url, decode_responses=True, socket_timeout=3)
    try:
        await client.set(_key(user_id), snapshot.model_dump_json(), ex=TTL_SECONDS)
    except RedisError:
        raise HTTPException(status_code=503, detail="Chat history is unavailable") from None
    finally:
        await client.aclose()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
