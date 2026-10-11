"""Local bearer-session helpers for offline-first authentication."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, PharmacistProfile

SESSION_LIFETIME = timedelta(hours=12)
bearer_scheme = HTTPBearer(auto_error=False)


def create_session(db: Session, profile: PharmacistProfile) -> tuple[str, datetime]:
    """Create a random token and persist only its SHA-256 digest locally."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    token = token_urlsafe(32)
    expires_at = now + SESSION_LIFETIME
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    db.add(AuthSession(
        profile_id=profile.id,
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
        expires_at=expires_at,
    ))
    db.commit()
    return token, expires_at.replace(tzinfo=timezone.utc)


def get_current_profile(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> PharmacistProfile:
    """Resolve an unexpired bearer token to its local pharmacist profile."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    digest = sha256(credentials.credentials.encode("utf-8")).hexdigest()
    session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == digest,
        AuthSession.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    profile = db.get(PharmacistProfile, session.profile_id) if session else None
    if profile is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session",
                            headers={"WWW-Authenticate": "Bearer"})
    return profile
