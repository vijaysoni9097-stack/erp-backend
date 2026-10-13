"""Email delivery and single-use password recovery."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from hashlib import sha256
import logging
from secrets import token_urlsafe
import smtplib
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthSession, PasswordResetToken, PharmacistProfile
from app.services.security import hash_secret

logger = logging.getLogger(__name__)


def send_reset_email(email: str, token: str) -> None:
    settings = get_settings()
    url = urlsplit(settings.password_reset_url)
    query = [(key, value) for key, value in parse_qsl(url.query) if key != 'token']
    link = urlunsplit(url._replace(query=urlencode(query + [('token', token)])))
    message = EmailMessage()
    message['Subject'] = 'Reset your pharmacy account password'
    message['From'] = settings.smtp_from_email
    message['To'] = email
    message.set_content(f'Use this link to reset your password within 15 minutes:\n\n{link}\n\n'
                        'If you did not request this, you can ignore this email.')
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or '')
        smtp.send_message(message)


def request_password_reset(db: Session, email: str) -> None:
    settings = get_settings()
    url = urlsplit(settings.password_reset_url or '')
    if not settings.smtp_host or not settings.smtp_from_email or url.scheme not in ('http', 'https') or not url.netloc:
        raise HTTPException(status_code=503, detail='Password recovery is not configured')
    profile = db.scalar(select(PharmacistProfile).where(
        func.lower(PharmacistProfile.email) == email.strip().lower()))
    if profile is None or not profile.password_hash:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = db.scalar(select(PasswordResetToken).where(PasswordResetToken.profile_id == profile.id))
    # Limit repeated messages without revealing whether the account exists.
    if existing and existing.created_at > now - timedelta(minutes=1):
        return
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.profile_id == profile.id))
    token = token_urlsafe(32)
    db.add(PasswordResetToken(profile_id=profile.id, token_hash=sha256(token.encode()).hexdigest(),
                            password_hash_at_issue=profile.password_hash,
                            created_at=now, expires_at=now + timedelta(minutes=15)))
    try:
        db.flush()
    except IntegrityError:
        # A concurrent request may already have created a link for this account.
        db.rollback()
        return
    try:
        send_reset_email(profile.email, token)
    except (OSError, smtplib.SMTPException):
        db.rollback()
        # Do not log email addresses, SMTP credentials, or reset links.
        logger.warning('Password reset email delivery failed')
        return
    db.commit()


def reset_password(db: Session, token: str, password: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # DELETE ... RETURNING makes consumption atomic even for concurrent requests.
    reset = db.execute(delete(PasswordResetToken).where(
        PasswordResetToken.token_hash == sha256(token.encode()).hexdigest(),
        PasswordResetToken.expires_at > now,
    ).returning(PasswordResetToken.profile_id, PasswordResetToken.password_hash_at_issue)).first()
    if reset is None:
        db.rollback()
        raise HTTPException(status_code=400, detail='Invalid or expired reset link')
    changed = db.execute(update(PharmacistProfile).where(
        PharmacistProfile.id == reset.profile_id,
        PharmacistProfile.password_hash == reset.password_hash_at_issue,
    ).values(password_hash=hash_secret(password)))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail='Invalid or expired reset link')
    db.execute(delete(AuthSession).where(AuthSession.profile_id == reset.profile_id))
    db.commit()
