"""Is the selected Hermes runtime usable right now: Hermes answers, and the public MCP server accepts our token
and lists exactly the tool the app expects. Checked before any budget is reserved.

A healthy answer is cached briefly and concurrent callers share one check. Nothing holds a lock across network
IO. A cached yes is not a promise, so the run still verifies its operations at the end."""

from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from . import hermes_runtime
from .completion import check_tools

CACHE_SECONDS = 10.0
PROTOCOL = "2025-06-18"


@dataclass(frozen=True)
class Readiness:
    ok: bool
    code: str | None = None


@dataclass(frozen=True)
class McpConfig:
    url: str
    token: str
    server: str = "marketplace"


def mcp_config() -> McpConfig | None:
    url = os.environ.get("PUBLIC_MCP_URL", "").strip()
    token = os.environ.get("PUBLIC_MCP_TOKEN", "")
    if not url.startswith(("http://", "https://")) or len(token) < 16:
        return None
    return McpConfig(url, token)


_healthy_until = 0.0
_inflight: tuple[asyncio.AbstractEventLoop, asyncio.Task] | None = None


def invalidate() -> None:
    global _healthy_until
    _healthy_until = 0.0


async def _rpc(http: httpx.AsyncClient, config: McpConfig, number: int, method: str,
               params: dict[str, Any]) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {config.token}", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json", "MCP-Protocol-Version": PROTOCOL}
    response = await http.post(config.url, json={"jsonrpc": "2.0", "id": number, "method": method, "params": params},
                               headers=headers)
    if response.status_code != 200:
        return None
    data = response.json()
    if not isinstance(data, dict) or data.get('jsonrpc') != '2.0' or data.get('id') != number or 'error' in data:
        return None
    result = data.get("result") if isinstance(data, dict) else None
    return result if isinstance(result, dict) else None


async def check_now() -> Readiness:
    hermes = hermes_runtime.hermes_config()
    mcp = mcp_config()
    if hermes is None or mcp is None:
        return Readiness(False, "config_invalid")
    async with httpx.AsyncClient(timeout=httpx.Timeout(3)) as http:
        try:
            response = await http.get(hermes.url + "/health", headers=hermes.headers)
            if response.status_code >= 400:
                return Readiness(False, "hermes_unreachable")
        except httpx.HTTPError:
            return Readiness(False, "hermes_unreachable")
        try:
            hello = await _rpc(http, mcp, 1, "initialize", {
                "protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "penny-readiness", "version": "1"}})
            if hello is None:
                return Readiness(False, "mcp_unreachable")
            if not isinstance(hello.get('serverInfo'), dict) or hello['serverInfo'].get("name") != mcp.server:
                return Readiness(False, "mcp_wrong_server")
            listed = await _rpc(http, mcp, 2, "tools/list", {})
        except (httpx.HTTPError, ValueError):
            return Readiness(False, "mcp_unreachable")
    tools = listed.get("tools") if listed else None
    if not isinstance(tools, list) or not all(isinstance(t, dict) and isinstance(t.get("name"), str) for t in tools):
        return Readiness(False, "tools_absent")
    if check_tools(["get_tool_details"], {t["name"]: t.get("inputSchema") for t in tools}, layer="listed"):
        return Readiness(False, "tools_absent")
    return Readiness(True)


async def check() -> Readiness:
    global _healthy_until, _inflight
    # Gateway capacity changes after every call, so never cache it with MCP health.
    gateway = await gateway_ready()
    if not gateway.ok:
        return gateway
    if time.monotonic() < _healthy_until:
        return Readiness(True)
    loop = asyncio.get_running_loop()
    if _inflight is None or _inflight[0] is not loop or _inflight[1].done():
        _inflight = (loop, loop.create_task(check_now()))
    task = _inflight[1]
    result = await asyncio.shield(task)
    if result.ok:
        _healthy_until = time.monotonic() + CACHE_SECONDS
    else:
        invalidate()
    return result


async def gateway_ready() -> Readiness:
    url = os.environ.get("MODEL_GATEWAY_URL", "").strip().rstrip("/")
    key = os.environ.get("MODEL_GATEWAY_KEY", "")
    if not url.startswith(("http://", "https://")) or len(key) < 16:
        return Readiness(False, "gateway_config_invalid")
    try:
        async with httpx.AsyncClient(timeout=2) as http:
            response = await http.get(url + "/gateway/status", headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            data = response.json()
        if data.get("tripped"):
            return Readiness(False, "gateway_usage_unverified")
        attempts, maximum = data["attempts"], data["max_requests"]
        committed, cap = data["committed_usd"], data["cap_usd"]
        if (type(attempts) is not int or type(maximum) is not int or attempts < 0 or maximum < 0
                or isinstance(committed, bool) or isinstance(cap, bool)
                or not math.isfinite(committed) or not math.isfinite(cap) or committed < 0 or cap < 0):
            return Readiness(False, "gateway_status_invalid")
        limits = data.get("enforce_lifetime_limits", True)
        if type(limits) is not bool:
            return Readiness(False, "gateway_status_invalid")
        if limits and (attempts >= maximum or committed >= cap):
            return Readiness(False, "gateway_exhausted")
        return Readiness(True)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return Readiness(False, "gateway_unreachable")
