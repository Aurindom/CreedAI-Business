"""Durable account favourites; independent of chat/Redis retention."""
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel

from . import auth, db

router = APIRouter(prefix='/api/favourites')


class Favourite(BaseModel):
    tool_id: str
    tool_name: str
    saved_at: str
    available: bool


def _available(request, tool_id):
    return next((tool for tool in request.app.state.catalog.tools
                 if tool.id == tool_id and tool.status != 'rejected'), None)


def _check_locked(request, principal):
    # Recheck within the write/read lock so a racing logout cannot authorize a write.
    if request.app.state.conn.execute('SELECT 1 FROM revoked_auth_session WHERE session_id=?',
                                      (principal.session_id,)).fetchone():
        raise auth.denied()


@router.get('', response_model=list[Favourite])
def list_favourites(request: Request, principal: auth.Principal = Depends(auth.require_account)):
    with request.app.state.lock:
        _check_locked(request, principal)
        rows = request.app.state.conn.execute(
            'SELECT tool_id,tool_name,saved_at FROM favourite_tool WHERE user_id=? ORDER BY saved_at DESC,tool_id',
            (principal.user_id,)).fetchall()
    return [Favourite(tool_id=tool_id, tool_name=(tool.name if (tool := _available(request, tool_id)) else name),
                      saved_at=saved, available=tool is not None) for tool_id, name, saved in rows]


@router.put('/{tool_id}', response_model=Favourite)
def save_favourite(request: Request, tool_id: str = Path(min_length=1, max_length=100),
                   principal: auth.Principal = Depends(auth.require_account)):
    tool = _available(request, tool_id)
    if tool is None:
        raise HTTPException(404, 'This tool is not available in the directory')
    with request.app.state.lock, request.app.state.conn:
        _check_locked(request, principal)
        request.app.state.conn.execute('INSERT OR IGNORE INTO favourite_tool VALUES(?,?,?,?)',
                                       (principal.user_id, tool.id, tool.name, db.now_text()))
        saved = request.app.state.conn.execute('SELECT saved_at FROM favourite_tool WHERE user_id=? AND tool_id=?',
                                               (principal.user_id, tool.id)).fetchone()[0]
    return Favourite(tool_id=tool.id, tool_name=tool.name, saved_at=saved, available=True)


@router.delete('/{tool_id}', status_code=204)
def remove_favourite(request: Request, tool_id: str = Path(min_length=1, max_length=100),
                     principal: auth.Principal = Depends(auth.require_account)):
    with request.app.state.lock, request.app.state.conn:
        _check_locked(request, principal)
        request.app.state.conn.execute('DELETE FROM favourite_tool WHERE user_id=? AND tool_id=?',
                                       (principal.user_id, tool_id))
    return Response(status_code=204)
