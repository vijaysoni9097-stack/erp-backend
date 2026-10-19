"""Remember cloud refresh sessions encrypted with this installation's secret."""
import base64
import json
from datetime import datetime
from hashlib import sha256
from cryptography.fernet import Fernet, InvalidToken
from app.config import get_settings
from app.models.sync import CloudSession


def cipher():
    secret = get_settings().sync_device_secret
    if not secret or len(secret) < 32:
        raise ValueError('This device must be enrolled before remembering cloud sessions')
    key = base64.urlsafe_b64encode(sha256(('erp-cloud-session-v1:' + secret).encode()).digest())
    return Fernet(key)


def save(db, profile_id, session):
    # Bind ciphertext to its local user as well as the installation.
    encrypted = cipher().encrypt(json.dumps({'profile_id': profile_id, 'session': session}).encode()).decode()
    row = db.get(CloudSession, profile_id)
    if row is None:
        row = CloudSession(profile_id=profile_id, encrypted_session=encrypted)
        db.add(row)
    row.encrypted_session = encrypted
    row.updated_at = datetime.utcnow()
    db.commit()


def load(db, profile_id):
    row = db.get(CloudSession, profile_id)
    if row is None: return None
    try:
        data = json.loads(cipher().decrypt(row.encrypted_session.encode()))
        session = data['session']
        if data['profile_id'] != profile_id or not session.get('refresh_token') or not session.get('access_token'):
            return None
        return session
    except (InvalidToken, ValueError, KeyError, TypeError):
        return None


def remove(db, profile_id):
    row = db.get(CloudSession, profile_id)
    if row is not None: db.delete(row)
