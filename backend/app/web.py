import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.web")

DEFAULT_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
API_PREFIX = "api"


def dist_dir() -> Path | None:
    """Read on every request so a build that appears after startup is served without a restart."""
    root = Path(os.environ.get("FRONTEND_DIST", DEFAULT_DIST)).resolve()
    return root if (root / "index.html").is_file() else None


def _safe_file(root: Path, relative: str) -> Path | None:
    """Resolves symlinks and '..' first, so nothing outside the dist folder can be returned."""
    candidate = (root / relative).resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return None


def _is_api(path: str) -> bool:
    first = path.lstrip("/").split("/", 1)[0]
    return first == API_PREFIX


async def _not_found_or_page(request: Request, exc: StarletteHTTPException):
    """Only an unmatched GET outside /api becomes a page. Everything else keeps the JSON error."""
    if exc.status_code != 404 or request.method not in ("GET", "HEAD") or _is_api(request.url.path):
        return await http_exception_handler(request, exc)
    root = dist_dir()
    if root is None:
        return await http_exception_handler(request, exc)
    relative = request.url.path.lstrip("/")
    asset = _safe_file(root, relative) if relative else None
    if asset is not None:
        return FileResponse(asset)
    if "." in Path(relative).name:
        return await http_exception_handler(request, exc)
    return FileResponse(root / "index.html")


async def _server_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again in a moment."})


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _not_found_or_page)
    app.add_exception_handler(Exception, _server_error)
