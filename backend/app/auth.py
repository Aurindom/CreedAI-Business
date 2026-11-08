"""Supabase identity and app-local logout enforcement, independent of Redis."""
import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import Header, HTTPException, Request


@dataclass(frozen=True)
class Principal:
    user_id: str | None = None
    session_id: str | None = None

    @property
    def authenticated(self):
        return self.user_id is not None


def denied():
    return HTTPException(401, 'Sign in again to continue', headers={'WWW-Authenticate': 'Bearer'})


def configuration():
    base = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
    parsed = urlparse(base)
    if not key or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(503, 'Account verification is unavailable')
    return base, key


async def remote_principal(token):
    base, key = configuration()
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.get(base + '/auth/v1/user', headers={'apikey': key, 'Authorization': 'Bearer ' + token})
        if response.status_code in (401, 403):
            raise denied()
        if response.status_code != 200:
            raise HTTPException(503, 'Account verification is unavailable')
        user = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Account verification is unavailable') from None
    # Decode ONLY AFTER Supabase authenticated this exact token. Decoding alone
    # never establishes trust. Bind the signed subject/session to returned user.
    try:
        encoded = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        subject = str(UUID(user['id']))
        session = str(UUID(claims['session_id']))
        audience = claims.get('aud')
        if (claims.get('sub') != subject or claims.get('iss') != base + '/auth/v1'
                or 'authenticated' not in (audience if isinstance(audience, list) else [audience])
                or isinstance(claims.get('exp'), bool) or not isinstance(claims.get('exp'), (int, float))
                or claims['exp'] <= datetime.now(timezone.utc).timestamp()):
            raise ValueError('invalid claims')
    except (ValueError, KeyError, TypeError, IndexError):
        raise denied() from None
    if user.get('is_anonymous') is True:
        return Principal()
    return Principal(subject, session)


def check_active(request, principal):
    if principal.authenticated:
        with request.app.state.lock:
            revoked = request.app.state.conn.execute('SELECT 1 FROM revoked_auth_session WHERE session_id = ?', (principal.session_id,)).fetchone()
        if revoked:
            raise denied()


async def optional_account(request: Request, authorization: str | None = Header(default=None)):
    if authorization is None:
        return Principal()
    scheme, _, token = authorization.partition(' ')
    if scheme.casefold() != 'bearer' or not token or len(token) > 16000:
        raise denied()
    principal = await remote_principal(token)
    check_active(request, principal)
    return principal


async def require_account(request: Request, authorization: str | None = Header(default=None)):
    principal = await optional_account(request, authorization)
    if not principal.authenticated:
        raise denied()
    return principal
