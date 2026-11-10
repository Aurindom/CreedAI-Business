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


def account_tools(conn, lock, catalog, principal, action='list', tool_ids=()):
    """Shared API/chat service. Identity stays server-owned; writes are read back.

    Idempotent saves/removals are safe to repeat. Session revocation is checked
    within the same lock/transaction as the operation, including read-only calls.
    """
    if not principal.authenticated:
        raise auth.denied()
    if action not in ('list', 'save', 'remove') or len(tool_ids) > 6:
        raise HTTPException(422, 'Invalid favourite operation')
    available = {tool.id: tool for tool in catalog.tools if tool.status != 'rejected'}
    if action == 'save' and any(tid not in available for tid in tool_ids):
        raise HTTPException(404, 'This tool is not available in the directory')
    with lock, conn:
        if conn.execute('SELECT 1 FROM revoked_auth_session WHERE session_id=?', (principal.session_id,)).fetchone():
            raise auth.denied()
        for tid in dict.fromkeys(tool_ids):
            if action == 'save':
                conn.execute('INSERT OR IGNORE INTO favourite_tool VALUES(?,?,?,?)',
                             (principal.user_id, tid, available[tid].name, db.now_text()))
            elif action == 'remove':
                conn.execute('DELETE FROM favourite_tool WHERE user_id=? AND tool_id=?', (principal.user_id, tid))
        rows = conn.execute('SELECT tool_id,tool_name,saved_at FROM favourite_tool WHERE user_id=? ORDER BY saved_at DESC,tool_id',
                            (principal.user_id,)).fetchall()
        ids = {row[0] for row in rows}
        if action == 'save' and not set(tool_ids) <= ids or action == 'remove' and set(tool_ids) & ids:
            raise RuntimeError('favourite_not_confirmed')
    return [Favourite(tool_id=tid, tool_name=available[tid].name if tid in available else name,
                      saved_at=saved, available=tid in available) for tid, name, saved in rows]


@router.get('', response_model=list[Favourite])
def list_favourites(request: Request, principal: auth.Principal = Depends(auth.require_account)):
    return account_tools(request.app.state.conn, request.app.state.lock, request.app.state.catalog, principal)


@router.put('/{tool_id}', response_model=Favourite)
def save_favourite(request: Request, tool_id: str = Path(min_length=1, max_length=100),
                   principal: auth.Principal = Depends(auth.require_account)):
    rows = account_tools(request.app.state.conn, request.app.state.lock, request.app.state.catalog,
                         principal, 'save', [tool_id])
    return next(row for row in rows if row.tool_id == tool_id)


@router.delete('/{tool_id}', status_code=204)
def remove_favourite(request: Request, tool_id: str = Path(min_length=1, max_length=100),
                     principal: auth.Principal = Depends(auth.require_account)):
    account_tools(request.app.state.conn, request.app.state.lock, request.app.state.catalog, principal, 'remove', [tool_id])
    return Response(status_code=204)
