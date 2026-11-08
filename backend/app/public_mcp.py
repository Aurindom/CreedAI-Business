"""Public-read-only MCP executor for Hermes. Run with `python -m app.public_mcp`.

It can read the public catalog and record the result of an operation the app registered. It has no private
action, no account data and no run identity. The mcp package is imported only when the server starts, so the
app itself does not depend on it."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any

from . import db
from .agent import tool_execution

logger = logging.getLogger(__name__)
SERVER_NAME = "marketplace"


class ConfigError(Exception):
    pass


def settings() -> tuple[Path, str, str, int]:
    token = os.environ.get("PUBLIC_MCP_TOKEN", "")
    host = os.environ.get("PUBLIC_MCP_ALLOWED_HOST", "").strip()
    if len(token) < 16:
        raise ConfigError("PUBLIC_MCP_TOKEN must be at least 16 characters")
    if not host or "*" in host:
        raise ConfigError("PUBLIC_MCP_ALLOWED_HOST must be one exact host:port")
    path = Path(os.environ.get("APP_DB_PATH", Path(__file__).resolve().parent.parent / "data" / "app.db"))
    return path, token, host, int(os.environ.get("PUBLIC_MCP_PORT", "8000"))


def lookup(path: Path, tool_id: Any, operation: Any) -> dict[str, Any]:
    conn = db.connect(path)
    try:
        return tool_execution.execute(conn, db.read_catalog(conn), operation, tool_id)
    finally:
        conn.close()


def require_token(app: Any, token: str) -> Any:
    expected = f"Bearer {token}".encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, expected):
                from starlette.responses import JSONResponse
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await app(scope, receive, send)
    return guarded


def build() -> tuple[Any, int]:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings

    path, token, host, port = settings()
    server = MCPServer(SERVER_NAME)

    @server.tool()
    def get_tool_details(tool_id: str, operation: str) -> dict:
        """Public catalog details for one tool. operation is the label given in the instructions."""
        return lookup(path, tool_id, operation)

    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[host], allowed_origins=[])
    app = server.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
    return require_token(app, token), port


if __name__ == "__main__":
    import uvicorn

    asgi, listen = build()
    uvicorn.run(asgi, host="0.0.0.0", port=listen, log_level="warning")
