"""Client for a pinned Hermes Agent api_server (v0.23.0 /v1/runs).

Transport only. The caller owns every decision: which tools had to run, whether the session is still active,
and whether the output is grounded. A terminal event from Hermes is not success by itself."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"run.completed", "run.failed", "run.cancelled", "run.interrupted"})
DEFAULT_TIMEOUT_SECONDS = 60.0
_stops: set[asyncio.Task] = set()


class HermesError(Exception):
    """The run could not be started or read. The message is a fixed code, never upstream text."""


@dataclass(frozen=True)
class HermesConfig:
    url: str
    key: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}


def client(config: HermesConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(10, read=config.timeout))


def hermes_config() -> HermesConfig | None:
    url = os.environ.get("HERMES_API_URL", "").strip().rstrip("/")
    key = os.environ.get("HERMES_API_KEY", "")
    if not url.startswith(("http://", "https://")) or len(key) < 8:
        return None
    try:
        timeout = float(os.environ.get("HERMES_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    return HermesConfig(url, key, timeout if 1 <= timeout <= 300 else DEFAULT_TIMEOUT_SECONDS)


@dataclass
class HermesRun:
    config: HermesConfig
    client: httpx.AsyncClient
    run_id: str | None = None
    terminal: str | None = None
    output: str = ""
    tools_started: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)

    async def start(self, instructions: str, message: str, session_id: str) -> None:
        body = {"input": message, "session_id": session_id, "instructions": instructions}
        try:
            response = await self.client.post(self.config.url + "/v1/runs", json=body, headers=self.config.headers)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HermesError("start_failed") from exc
        run_id = data.get("run_id") or data.get("id") if isinstance(data, dict) else None
        if not isinstance(run_id, str) or not run_id:
            raise HermesError("start_failed")
        self.run_id = run_id

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yields tool events as they happen and returns at the first terminal event. Deltas are collected,
        never yielded, because nothing reaches the owner before the output is validated."""
        deltas: list[str] = []
        url = self.config.url + f"/v1/runs/{self.run_id}/events"
        try:
            async with self.client.stream("GET", url, headers=self.config.headers) as stream:
                if stream.status_code != 200:
                    raise HermesError("events_failed")
                async for line in stream.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:])
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("event") or event.get("type")
                    if kind == "message.delta":
                        deltas.append(str(event.get("delta") or ""))
                    elif kind in ("tool.started", "tool.completed"):
                        tool = str(event.get("tool") or "")
                        if kind == "tool.started":
                            self.tools_started.append(tool)
                        if event.get("error"):
                            self.tool_errors.append(tool)
                        yield {"kind": kind, "tool": tool}
                    elif kind in TERMINAL:
                        self.terminal = kind
                        output = event.get("output")
                        self.output = output if isinstance(output, str) and output else "".join(deltas)
                        return
        except httpx.HTTPError as exc:
            raise HermesError("events_failed") from exc
        raise HermesError("stream_ended")

    async def stop(self) -> bool:
        if not self.run_id or self.terminal:
            return False
        try:
            response = await self.client.post(self.config.url + f"/v1/runs/{self.run_id}/stop",
                                              headers=self.config.headers, timeout=5)
            return response.status_code < 400
        except httpx.HTTPError:
            logger.warning("Hermes run could not be stopped")
            return False

    def stop_later(self) -> None:
        """Used when the caller is being torn down (client disconnect) and cannot await. The task is kept
        referenced so it is not garbage collected before the stop request is sent."""
        if not self.run_id or self.terminal:
            return
        config, run_id = self.config, self.run_id

        async def send() -> None:
            async with client(config) as http:
                try:
                    await http.post(config.url + f"/v1/runs/{run_id}/stop", headers=config.headers, timeout=5)
                except httpx.HTTPError:
                    logger.warning("Hermes run could not be stopped")

        try:
            task = asyncio.get_running_loop().create_task(send())
        except RuntimeError:
            return
        _stops.add(task)
        task.add_done_callback(_stops.discard)


def health(config: HermesConfig) -> bool:
    try:
        return httpx.get(config.url + "/health", headers=config.headers, timeout=2).status_code < 400
    except httpx.HTTPError:
        return False
