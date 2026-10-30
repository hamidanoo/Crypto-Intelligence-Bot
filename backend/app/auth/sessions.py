"""Server-side administrator sessions.

A session is an opaque token held by the browser in an
HttpOnly cookie. Only its SHA-256 hash is stored, with a
separate CSRF token that state-changing requests must
echo back. Sessions expire on inactivity (default 60
minutes) and absolutely (default 12 hours); last_seen_at
is refreshed on every authenticated request. Login
always creates a fresh session, so a pre-login cookie
can never be fixed into a post-login session.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import AdminSession


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db, user, *, ip_address: str | None, user_agent: str | None):
    """Create a fresh session. Returns (token, csrf_token, row)."""
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    row = AdminSession(
        admin_user_id=user.id,
        session_token_hash=_hash_token(token),
        csrf_token=csrf_token,
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        last_seen_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return token, csrf_token, row


def revoke_session(db, session: AdminSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()


def _is_expired(session: AdminSession, now: datetime) -> bool:
    if session.revoked_at is not None:
        return True
    if session.expires_at is not None and now >= _aware(session.expires_at):
        return True
    last_seen = _aware(session.last_seen_at) if session.last_seen_at else now
    if now - last_seen > timedelta(minutes=settings.session_inactivity_minutes):
        return True
    return False


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def lookup_session(db, token: str | None):
    """Return (user, session) for a live session, else (None, None).

    Expired sessions are revoked on sight. A live session
    has its last_seen_at refreshed so inactivity expiry
    tracks real use.
    """
    if not token:
        return None, None
    from app.models import AdminUser

    session = (
        db.query(AdminSession).filter(AdminSession.session_token_hash == _hash_token(token)).first()
    )
    if session is None:
        return None, None
    now = datetime.now(timezone.utc)
    if _is_expired(session, now):
        revoke_session(db, session)
        return None, None
    user = db.query(AdminUser).filter(AdminUser.id == session.admin_user_id).first()
    if user is None or not user.is_active:
        return None, None
    session.last_seen_at = now
    db.commit()
    return user, session


def rotate_session(db, session: AdminSession, *, ip_address: str | None, user_agent: str | None):
    """Rotate a session: the old token stops working immediately."""
    user_id = session.admin_user_id
    revoke_session(db, session)
    from app.models import AdminUser

    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    return create_session(db, user, ip_address=ip_address, user_agent=user_agent)
