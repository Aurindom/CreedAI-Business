"""The only process that holds the provider key. Hermes sends every model call here, the main turn and any
auxiliary call alike, and nothing reaches the provider without first being admitted.

Admission is one SQLite write transaction. It checks that the gateway isn't tripped, that the request cap has
room, and that settled charges plus open reservations plus this new reservation stay under the cap. Only then
does it insert the attempt row, and only after that are any bytes sent. The cap counts HTTP requests, not
turns, so a retry is just another attempt.

The charge is settled once, from the provider's reported cost. If the cost is missing, invalid or larger than
the reservation, or the stream breaks, or the process dies mid-request, the full reservation stays charged and
the gateway trips. A tripped gateway refuses everything until someone reconciles it by hand. Nothing is ever
retried here.

Caps are global to this gateway's state file. One Hermes credential can't say which user caused a call, so
these limits bound a batch, not a person."""

from __future__ import annotations

import hmac
import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .chat import DEFAULT_MODEL, MAX_OUTPUT_TOKENS, MODEL_TIMEOUT_SECONDS, usage_cost

INPUT_USD_PER_MTOK = 1.0
OUTPUT_USD_PER_MTOK = 5.0
INPUT_MARGIN = 2
FRAMING_TOKENS = 4096
MAX_REQUEST_BYTES = 40_000
MAX_RESPONSE_BYTES = 512_000
MAX_STREAM_EVENTS = 4_000
RECOVERY_OUTPUT_TOKENS = 1600
MAX_CALLS_PER_TURN = 6
TURN_MARKER = re.compile(r"\nGateway turn: ([0-9a-f]{32})\n")
ALLOWED_FIELDS = {"model", "messages", "tools", "tool_choice", "stream", "stream_options", "max_tokens",
                  "max_completion_tokens", "temperature", "top_p", "stop", "parallel_tool_calls", "n",
                  "reasoning_effort", "reasoning", "response_format"}
DROPPED_FIELDS = ("max_completion_tokens", "reasoning_effort", "reasoning", "top_p")
TEXT_PARTS = {"text"}
MARKERS = (r"sk-or-[A-Za-z0-9-]{8,}", r"(?i)bearer\s+\S", r"account_id", r"owner_hash", r"run_key",
           r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayConfig:
    upstream: str
    provider_key: str
    client_key: str
    state_path: Path
    max_requests: int
    cap_usd: float
    model: str = DEFAULT_MODEL
    tools: frozenset[str] = frozenset({"mcp__marketplace__get_tool_details"})
    forbidden: tuple[str, ...] = field(default_factory=tuple)
    timeout: float = MODEL_TIMEOUT_SECONDS
    enforce_lifetime_limits: bool = True

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        env = os.environ
        upstream = env.get("GATEWAY_UPSTREAM", "").strip()
        if not upstream.startswith(("http://", "https://")) or not upstream.endswith("/chat/completions"):
            raise ConfigError("GATEWAY_UPSTREAM must be a full .../chat/completions URL")
        provider_key, client_key = env.get("GATEWAY_PROVIDER_KEY", ""), env.get("GATEWAY_CLIENT_KEY", "")
        if len(provider_key) < 16 or len(client_key) < 16 or provider_key == client_key:
            raise ConfigError("GATEWAY_PROVIDER_KEY and GATEWAY_CLIENT_KEY must be distinct, 16+ characters")
        try:
            max_requests = int(env.get("GATEWAY_MAX_REQUESTS", ""))
            cap_usd = float(env.get("GATEWAY_CAP_USD", ""))
        except ValueError as exc:
            raise ConfigError("GATEWAY_MAX_REQUESTS and GATEWAY_CAP_USD are required numbers") from exc
        if max_requests < 0 or not math.isfinite(cap_usd) or cap_usd < 0:
            raise ConfigError("caps must be non-negative")
        state = env.get("GATEWAY_STATE_PATH", "").strip()
        if not state:
            raise ConfigError("GATEWAY_STATE_PATH is required")
        tools = frozenset(t for t in env.get("GATEWAY_TOOLS", "mcp__marketplace__get_tool_details").split(",") if t)
        forbidden = tuple(v for v in env.get("GATEWAY_FORBIDDEN", "").split(",") if len(v) >= 8)
        limits = env.get("GATEWAY_ENFORCE_LIFETIME_LIMITS", "true").lower()
        if limits not in ("true", "false"):
            raise ConfigError("GATEWAY_ENFORCE_LIFETIME_LIMITS must be true or false")
        return cls(upstream, provider_key, client_key, Path(state), max_requests, cap_usd,
                   env.get("GATEWAY_MODEL", DEFAULT_MODEL), tools, forbidden,
                   enforce_lifetime_limits=limits == "true")


def reservation(size: int, output_tokens: int = MAX_OUTPUT_TOKENS) -> float:
    """Conservative text-only reservation under the documented framing/token assumption.
    Provider rate filtering and output limits also apply; this is not an account-level billing guarantee.
    Missing or over-reservation usage holds the charge and trips further admission."""
    tokens_in = (size + FRAMING_TOKENS) * INPUT_MARGIN
    return (tokens_in * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / 1_000_000


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS gateway (id INTEGER PRIMARY KEY CHECK (id = 1), "
                         "tripped TEXT, refused INTEGER NOT NULL DEFAULT 0)")
            conn.execute("INSERT OR IGNORE INTO gateway (id) VALUES (1)")
            conn.execute("CREATE TABLE IF NOT EXISTS attempt (n INTEGER PRIMARY KEY AUTOINCREMENT, "
                         "state TEXT NOT NULL CHECK (state IN ('reserved', 'settled', 'held')), "
                         "reserved_usd REAL NOT NULL, charged_usd REAL, reason TEXT, "
                         "created REAL NOT NULL, closed REAL)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(attempt)")}
            for name in ("turn_id", "finish_reason"):
                if name not in columns:
                    conn.execute(f"ALTER TABLE attempt ADD COLUMN {name} TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS attempt_turn ON attempt(turn_id)")

    def _tx(self) -> "_Tx":
        return _Tx(self.path)

    def recover(self, stale_after_s: float = 0) -> int:
        """Rows still reserved at startup belong to a process that died mid-call. Their cost is unknown."""
        with self._tx() as conn:
            count = conn.execute("UPDATE attempt SET state = 'held', charged_usd = reserved_usd, reason = 'orphaned', "
                                 "closed = ? WHERE state = 'reserved' AND created <= ?", (time.time(),time.time()-stale_after_s)).rowcount
            if count:
                conn.execute("UPDATE gateway SET tripped = COALESCE(tripped, 'orphaned')")
        return count

    def admit(self, amount: float, max_requests: int, cap_usd: float, *,
              enforce_limits: bool = True, turn_id: str | None = None) -> tuple[int | None, str | None]:
        with self._tx() as conn:
            tripped = conn.execute("SELECT tripped FROM gateway").fetchone()[0]
            count, committed = conn.execute(
                "SELECT count(*), COALESCE(SUM(CASE WHEN state = 'reserved' THEN reserved_usd ELSE charged_usd END), 0) "
                "FROM attempt").fetchone()
            calls, lengths, active = conn.execute(
                "SELECT count(*), COALESCE(SUM(finish_reason='length'),0), COALESCE(SUM(state='reserved'),0) "
                "FROM attempt WHERE turn_id = ?", (turn_id,)).fetchone()
            code = ("usage_unverified" if tripped else
                    "turn_call_limit" if turn_id and calls >= MAX_CALLS_PER_TURN else
                    "truncation_retry_exhausted" if turn_id and lengths >= 2 else
                    "turn_inflight" if turn_id and active else
                    "request_cap" if enforce_limits and count >= max_requests else
                    "budget_exhausted" if enforce_limits and committed + amount > cap_usd else None)
            if code:
                conn.execute("UPDATE gateway SET refused = refused + 1")
                return None, code
            cursor = conn.execute("INSERT INTO attempt (state, reserved_usd, created, turn_id) VALUES ('reserved', ?, ?, ?)",
                                  (amount, time.time(), turn_id))
            return cursor.lastrowid, None

    def output_limit(self, turn_id: str | None) -> int:
        with self._tx() as conn:
            truncated = conn.execute("SELECT 1 FROM attempt WHERE turn_id=? AND finish_reason='length' LIMIT 1",
                                     (turn_id,)).fetchone()
        return RECOVERY_OUTPUT_TOKENS if truncated else MAX_OUTPUT_TOKENS

    def refused(self) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE gateway SET refused = refused + 1")

    def settle(self, number: int, cost: float, finish_reason: str | None = None) -> bool:
        with self._tx() as conn:
            return conn.execute("UPDATE attempt SET state = 'settled', charged_usd = ?, closed = ?, finish_reason = ? "
                                "WHERE n = ? AND state = 'reserved'", (cost, time.time(), finish_reason, number)).rowcount == 1

    def hold(self, number: int, reason: str, cost: float | None = None) -> None:
        """Keep at least the reservation charged and stop all further calls until reconciled."""
        with self._tx() as conn:
            conn.execute("UPDATE attempt SET state = 'held', charged_usd = MAX(reserved_usd, ?), reason = ?, closed = ? "
                         "WHERE n = ? AND state = 'reserved'", (cost or 0.0, reason, time.time(), number))
            conn.execute("UPDATE gateway SET tripped = COALESCE(tripped, ?)", (reason,))

    def status(self) -> dict[str, Any]:
        with self._tx() as conn:
            tripped, refused = conn.execute("SELECT tripped, refused FROM gateway").fetchone()
            rows = conn.execute("SELECT state, count(*), COALESCE(SUM(CASE WHEN state = 'reserved' THEN reserved_usd "
                                "ELSE charged_usd END), 0) FROM attempt GROUP BY state").fetchall()
        by_state = {state: {"count": count, "usd": round(usd, 6)} for state, count, usd in rows}
        return {"attempts": sum(v["count"] for v in by_state.values()), "by_state": by_state, "refused": refused,
                "tripped": tripped, "committed_usd": round(sum(v["usd"] for v in by_state.values()), 6)}


class _Tx:
    """BEGIN IMMEDIATE takes the write lock up front, so two gateway workers can't both pass the cap check."""

    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(path, timeout=10, isolation_level=None)

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, kind: Any, *_: Any) -> None:
        try:
            self.conn.execute("ROLLBACK" if kind else "COMMIT")
        finally:
            self.conn.close()


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"message": f"model gateway refused: {code}", "code": code}}, status_code=status)


def _check(body: Any, raw: str, config: GatewayConfig) -> str | None:
    if not isinstance(body, dict):
        return "bad_request"
    if set(body) - ALLOWED_FIELDS:
        return "unsupported_field"
    if body.get("model") != config.model:
        return "model_not_pinned"
    if body.get("n", 1) != 1:
        return "unsupported_field"
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return "bad_request"
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(not isinstance(p, dict) or p.get("type") not in TEXT_PARTS for p in content):
            return "unsupported_modality"
    for tool in body.get("tools") or []:
        name = (tool.get("function") or {}).get("name") if isinstance(tool, dict) else None
        if not isinstance(tool, dict) or tool.get("type") != "function" or name not in config.tools:
            return "tool_not_allowed"
    if any(value in raw for value in config.forbidden + (config.provider_key, config.client_key)):
        return "forbidden_marker"
    if any(re.search(pattern, raw) for pattern in MARKERS):
        return "forbidden_marker"
    return None


def _pinned(body: dict[str, Any], output_limit: int = MAX_OUTPUT_TOKENS) -> dict[str, Any]:
    for key in DROPPED_FIELDS:
        body.pop(key, None)
    requested = body.get("max_tokens")
    body["max_tokens"] = min(requested, output_limit) if type(requested) is int and requested > 0 else output_limit
    body["temperature"] = 0
    body["usage"] = {"include": True}
    body["provider"] = {"max_price": {"prompt": INPUT_USD_PER_MTOK, "completion": OUTPUT_USD_PER_MTOK},
                        "allow_fallbacks": False, "require_parameters": True}
    if any(message.get('role') == 'system' and 'penny_hermes_selection_v1' in str(message.get('content', ''))
           for message in body.get('messages', []) if isinstance(message, dict)):
        from .penny_conversation import reply_choices
        excerpts = []
        registered_reads = False
        for message in body.get('messages', []):
            content = message.get('content', '') if isinstance(message, dict) else ''
            if (message.get('role') == 'system' and isinstance(content, str)
                    and re.search(r'\nBefore answering, call get_tool_details once with tool_id "[^"\n]+" and operation "op_[0-9a-f]{24}"\.', content)):
                registered_reads = True
            if isinstance(content, str) and '\nrouting_excerpts: ' in content:
                try:
                    candidates = json.loads(content.split('\nrouting_excerpts: ', 1)[1].split('\n', 1)[0])
                    excerpts = [value for value in candidates if isinstance(value, str) and 1 <= len(value) <= 500][:24]
                except (ValueError, TypeError):
                    pass
        if not registered_reads:
            # Intent-only turns have no authorized operation label. Offering a
            # catalog tool here invites a failed call and another model round.
            for field in ('tools', 'tool_choice', 'parallel_tool_calls'):
                body.pop(field, None)
        task_text_schema = {'type': 'string', **({'enum': excerpts} if excerpts else {})}
        body['response_format'] = {'type': 'json_schema', 'json_schema': {
            'name': 'penny_selection', 'strict': True, 'schema': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'claim_ids': {'type': 'array', 'items': {'type': 'string'}},
                               'followup_id': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                               'conversation_intent': {'anyOf': [{'type': 'string', 'enum': ['greeting', 'acknowledgement', 'repair', 'help', 'scope']}, {'type': 'null'}]},
                               'reply_id': {'anyOf': [{'type': 'string', 'enum': list(reply_choices())}, {'type': 'null'}]},
                               'routes': {'anyOf': [{'type': 'array', 'maxItems': 3, 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'problem_id': {'type': 'string'}, 'task_text': task_text_schema}, 'required': ['problem_id', 'task_text']}}, {'type': 'null'}]},
                               'trade': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                               'trade_text': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                               'business_text': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                               'action': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': False,
                                   'properties': {'kind': {'type': 'string', 'enum': ['compare', 'recall', 'clarify', 'help', 'scope']},
                                                  'criterion': {'anyOf': [{'type': 'string', 'enum': ['price', 'plan', 'cost', 'fit']}, {'type': 'null'}]},
                                                  'owner_text': {'type': 'string'}},
                                   'required': ['kind', 'criterion', 'owner_text']}] }},
                'required': ['claim_ids', 'followup_id', 'conversation_intent', 'reply_id', 'routes', 'trade', 'trade_text', 'business_text', 'action']}}}
        properties = body['response_format']['json_schema']['schema']['properties']
        if any(message.get('role') == 'system' and 'conversation_plan_v3' in str(message.get('content', ''))
               for message in body.get('messages', []) if isinstance(message, dict)):
            from .conversation_plan import strict_schema
            properties['plan'] = {'type': 'null'} if registered_reads else strict_schema()
            body['response_format']['json_schema']['schema']['required'].append('plan')
            # V3 conversation must use the complete plan, not the legacy
            # single-action/generic reply escape hatch. Old instances keep V2.
            for field in ('action', 'conversation_intent', 'reply_id', 'routes', 'trade', 'trade_text'):
                properties[field] = {'type': 'null'}
        if not any(message.get('role') == 'system' and 'conversation_state_v2' in str(message.get('content', ''))
                   for message in body.get('messages', []) if isinstance(message, dict)):
            # Existing app instances keep their old contract during rolling
            # deployment and rollback; new fields require an explicit version.
            schema = body['response_format']['json_schema']['schema']
            for field in ('business_text', 'action'):
                properties.pop(field, None)
                schema['required'].remove(field)
        properties['claim_ids']['maxItems'] = 10
        properties['claim_ids']['items']['maxLength'] = 160
        task_text_schema['maxLength'] = 500
        for message in body.get('messages', []):
            content = message.get('content', '') if isinstance(message, dict) else ''
            if message.get('role') != 'system' or not isinstance(content, str):
                continue
            if '\ninitial_evidence_package: ' not in content:
                continue
            try:
                package, _ = json.JSONDecoder().raw_decode(content.rsplit('\ninitial_evidence_package: ', 1)[1].lstrip())
                ids = [claim['id'] for claim in package['claims'] if isinstance(claim.get('id'), str)]
                if ids:
                    properties['claim_ids']['items']['enum'] = ids
                else:
                    properties['claim_ids']['maxItems'] = 0
                followups = list(package.get('followups', {}))
                properties['followup_id'] = ({'anyOf': [{'type': 'string', 'enum': followups}, {'type': 'null'}]}
                                              if followups else {'type': 'null'})
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
    if body.get("stream"):
        body["stream_options"] = {"include_usage": True}
    else:
        body.pop("stream_options", None)
    return body


def _completion_tokens(usage: Any) -> int | None:
    value = usage.get("completion_tokens") if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class Gateway:
    def __init__(self, config: GatewayConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self.ledger = Ledger(config.state_path)
        self.transport = transport
        self.log_path = config.state_path.with_suffix(".jsonl")
        recovered = self.ledger.recover()
        if recovered:
            self.log({"result": "recovered_orphans", "count": recovered})

    def log(self, entry: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(entry, at=round(time.time(), 3))) + "\n")

    def authorized(self, request: Request) -> bool:
        given = request.headers.get("authorization", "")
        return hmac.compare_digest(given.encode(), f"Bearer {self.config.client_key}".encode())

    def close(self, number: int, entry: dict[str, Any], cost: float | None, usage: Any, failed: str | None,
              reserved: float) -> None:
        """Settle exactly once. Anything short of a clean, in-bounds, reported cost keeps the reservation."""
        tokens = _completion_tokens(usage)
        if failed is None and cost is None:
            failed = "usage_missing"
        if failed is None and (cost > reserved or (tokens is not None and tokens > entry.get('output_limit', MAX_OUTPUT_TOKENS))):
            failed = "usage_over_bound"
        if failed:
            self.ledger.hold(number, failed, cost)
        else:
            self.ledger.settle(number, cost, entry.get('finish_reason'))
        self.log(dict(entry, result=failed or "ok", cost_usd=cost, completion_tokens=tokens))

    async def models(self, request: Request) -> JSONResponse:
        if not self.authorized(request):
            return _error("unauthorized", 401)
        return JSONResponse({"object": "list", "data": [{"id": self.config.model, "object": "model"}]})

    async def status(self, request: Request) -> JSONResponse:
        if not self.authorized(request):
            return _error("unauthorized", 401)
        return JSONResponse(dict(self.ledger.status(), max_requests=self.config.max_requests,
                                 cap_usd=self.config.cap_usd, model=self.config.model,
                                 enforce_lifetime_limits=self.config.enforce_lifetime_limits))

    async def completions(self, request: Request) -> Any:
        if not self.authorized(request):
            return _error("unauthorized", 401)
        raw = await request.body()
        if len(raw) > MAX_REQUEST_BYTES:
            self.ledger.refused()
            return _error("too_large", 413)
        text = raw.decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        problem = _check(body, text, self.config)
        if problem:
            self.ledger.refused()
            self.log({"result": "refused", "code": problem})
            return _error(problem, 400)
        # Opaque per-run identity comes only from the trusted application's system
        # instructions. Strip it before forwarding; no user/account identifiers.
        turns = set()
        for message in body['messages']:
            if isinstance(message, dict) and message.get('role') == 'system' and isinstance(message.get('content'), str):
                turns.update(TURN_MARKER.findall(message['content']))
                message['content'] = TURN_MARKER.sub('\n', message['content'])
        if len(turns) > 1:
            return _error('ambiguous_turn', 400)
        turn_id = next(iter(turns), None)
        output_limit = self.ledger.output_limit(turn_id)
        payload = json.dumps(_pinned(body, output_limit), ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            self.ledger.refused()
            return _error("too_large", 413)
        reserved = reservation(len(payload), body['max_tokens'])
        number, code = self.ledger.admit(reserved, self.config.max_requests, self.config.cap_usd,
                                       enforce_limits=self.config.enforce_lifetime_limits, turn_id=turn_id)
        if number is None:
            self.log({"result": "refused", "code": code})
            return _error(code, 402 if code == "budget_exhausted" else 403)
        stream = bool(body.get("stream"))
        entry = {"n": number, "bytes": len(payload), "reserved_usd": round(reserved, 6), "stream": stream,
                 "output_limit": body['max_tokens'],
                 "messages": len(body["messages"]), "tools": sorted((t.get("function") or {}).get("name", "?")
                                                                  for t in body.get("tools") or [])}
        client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout, connect=10), transport=self.transport)
        headers = {"Authorization": f"Bearer {self.config.provider_key}", "Content-Type": "application/json"}
        try:
            upstream = await client.send(client.build_request("POST", self.config.upstream, content=payload,
                                                              headers=headers), stream=True)
        except BaseException as exc:
            await client.aclose()
            self.close(number, entry, None, None, f"transport_{type(exc).__name__}", reserved)
            if isinstance(exc, Exception):
                return _error("upstream_error", 502)
            raise
        if upstream.status_code != 200:
            await upstream.aclose()
            await client.aclose()
            self.close(number, dict(entry, status=upstream.status_code), None, None, "upstream_status", reserved)
            return _error("upstream_error", 502)
        if not stream:
            return await self._whole(upstream, client, number, entry, reserved)
        return Relay(self, upstream, client, number, entry, reserved)

    async def _whole(self, upstream: httpx.Response, client: httpx.AsyncClient, number: int,
                     entry: dict[str, Any], reserved: float) -> JSONResponse:
        failed, data = None, None
        try:
            chunks, size = [], 0
            async for chunk in upstream.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    failed = "response_too_large"
                    break
                chunks.append(chunk)
            if failed is None:
                data = json.loads(b"".join(chunks))
        except (httpx.HTTPError, ValueError) as exc:
            failed = f"read_{type(exc).__name__}"
        except BaseException:
            self.close(number, entry, None, None, "cancelled", reserved)
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()
                await client.aclose()
        usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(data, dict):
            reasons = [choice.get('finish_reason') for choice in data.get('choices', []) if isinstance(choice, dict)]
            entry['finish_reason'] = next((value for value in reasons if value in ('stop', 'length', 'tool_calls', 'content_filter')), None)
        self.close(number, entry, usage_cost(usage), usage, failed, reserved)
        if failed or not isinstance(data, dict):
            return _error("usage_unverified", 502)
        return JSONResponse(data)


class Relay:
    """Streams the provider's SSE to Hermes. If Hermes goes away mid-stream the provider keeps generating and
    keeps billing, so the relay keeps reading to learn the real cost instead of guessing. A server shutdown or
    a stream that ends without usage keeps the reservation."""

    def __init__(self, gateway: Gateway, upstream: httpx.Response, client: httpx.AsyncClient, number: int,
                 entry: dict[str, Any], reserved: float) -> None:
        self.gateway, self.upstream, self.client = gateway, upstream, client
        self.number, self.entry, self.reserved = number, entry, reserved

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        state: dict[str, Any] = {"cost": None, "usage": None, "failed": None, "gone": False, "done": False, "closed": False}

        async def deliver(message: dict[str, Any]) -> None:
            if state["gone"]:
                return
            try:
                await send(message)
            except OSError:
                state["gone"] = True

        async def pump(scope_to_cancel: anyio.CancelScope) -> None:
            events, size = 0, 0
            await deliver({"type": "http.response.start", "status": 200,
                           "headers": [(b"content-type", b"text/event-stream"), (b"cache-control", b"no-cache")]})
            try:
                async for line in self.upstream.aiter_lines():
                    size += len(line) + 1
                    events += 1
                    if size > MAX_RESPONSE_BYTES or events > MAX_STREAM_EVENTS:
                        state["failed"] = "stream_too_large"
                        break
                    if line.startswith(":"):
                        continue
                    data = line[5:].strip() if line.startswith("data:") else ""
                    if data == "[DONE]":
                        state["done"] = True
                        # Commit usage/retry state before Hermes can start its next
                        # request, not after it has already received the terminal frame.
                        self.gateway.close(self.number, dict(self.entry, client_gone=state['gone']),
                                           state['cost'], state['usage'], state['failed'], self.reserved)
                        state['closed'] = True
                    elif data:
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            chunk = {}
                        if isinstance(chunk, dict) and chunk.get("usage"):
                            state["usage"] = chunk["usage"]
                            state["cost"] = usage_cost(chunk["usage"])
                        if isinstance(chunk, dict):
                            for choice in chunk.get('choices', []):
                                reason = choice.get('finish_reason') if isinstance(choice, dict) else None
                                if reason in ('stop', 'length', 'tool_calls', 'content_filter'):
                                    self.entry['finish_reason'] = reason
                    await deliver({"type": "http.response.body", "body": (line + "\n").encode(), "more_body": True})
            except httpx.HTTPError as exc:
                state["failed"] = f"stream_{type(exc).__name__}"
            if state["failed"] is None and not state["done"]:
                state["failed"] = "stream_truncated"
            await deliver({"type": "http.response.body", "body": b"", "more_body": False})
            scope_to_cancel.cancel()

        async def watch() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    state["gone"] = True
                    return

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(pump, group.cancel_scope)
                group.start_soon(watch)
        except BaseException:
            state["failed"] = state["failed"] or "cancelled"
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await self.upstream.aclose()
                await self.client.aclose()
            entry = dict(self.entry, client_gone=state["gone"])
            if not state['closed']:
                self.gateway.close(self.number, entry, state["cost"], state["usage"], state["failed"], self.reserved)


def build(config: GatewayConfig | None = None, transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    gateway = Gateway(config or GatewayConfig.from_env(), transport)
    app = Starlette(routes=[
        Route("/v1/models", gateway.models),
        Route("/v1/chat/completions", gateway.completions, methods=["POST"]),
        Route("/gateway/status", gateway.status),
    ])
    app.state.gateway = gateway
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build(), host="0.0.0.0", port=int(os.environ.get("GATEWAY_PORT", "9999")), log_level="warning")
