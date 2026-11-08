"""Loopback-only integration server. Identity-provider seam is synthetic; data services are real."""
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['APP_DB_PATH'] = str(ROOT / 'sandbox/favourites-qa.db')
os.environ['REDIS_URL'] = os.environ.get('QA_REDIS_URL', 'redis://127.0.0.1:6379/15')
os.environ.pop('OPENROUTER_API_KEY', None)
from app import auth
from app import db

# Reset only synthetic owners in this dedicated QA database, never app data.
conn = db.connect(Path(os.environ['APP_DB_PATH']))
with conn:
    for table in ('favourite_tool', 'chat_session_usage', 'chat_conversation', 'revoked_auth_session'):
        conn.execute(f'DELETE FROM {table} WHERE user_id IN (?,?)', (str(UUID(int=900001)), str(UUID(int=900002))))
conn.close()

async def fixture_identity(token):
    try:
        encoded = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if claims.get('qa_fixture') is not True or claims['sub'] not in (str(UUID(int=900001)), str(UUID(int=900002))):
            raise ValueError()
        return auth.Principal(claims['sub'], str(UUID(claims['session_id'])))
    except (ValueError, KeyError, IndexError, TypeError):
        raise auth.denied()

auth.remote_principal = fixture_identity
from app import chat_history
def fixture_time():
    clock = ROOT / 'sandbox/favourites-qa-clock.json'
    offset = json.loads(clock.read_text()).get('seconds', 0) if clock.exists() else 0
    return datetime.now(timezone.utc) + timedelta(seconds=offset)
chat_history.now = fixture_time
from app.main import app
import uvicorn
uvicorn.run(app, host='127.0.0.1', port=8001)
