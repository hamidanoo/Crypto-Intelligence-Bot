"""FastAPI authentication and authorisation dependencies.

Deny by default: every protected endpoint declares either
get_current_admin or require_permission(...). A failed
authorisation attempt is recorded in the audit log. CSRF
protection applies to state-changing requests under
/auth and /admin and is enforced by require_csrf, which
compares the X-CSRF-Token header with the session's
stored CSRF token.
"""

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.audit import record_audit
from app.auth.permissions import user_permissions
from app.auth.sessions import lookup_session
from app.config import settings
from app.database import get_db

_login_attempts: dict[str, deque] = defaultdict(deque)


def reset_login_rate_limits() -> None:
    _login_attempts.clear()


def check_login_rate_limit(request: Request) -> None:
    """Per-IP login rate limit, independent of other limiters."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _login_attempts[client_ip]
    while window and window[0] <= now - 60:
        window.popleft()
    if len(window) >= settings.login_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Too many login attempts, try again later")
    window.append(now)


def _client_info(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip, user_agent


def get_current_session(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.session_cookie_name)
    user, session = lookup_session(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user, session


def get_current_admin(request: Request, db: Session = Depends(get_db)):
    user, _session = get_current_session(request, db)
    return user


def require_permission(permission: str):
    async def _check(request: Request, db: Session = Depends(get_db)):
        token = request.cookies.get(settings.session_cookie_name)
        user, _session = lookup_session(db, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        permissions = user_permissions(db, user)
        if permission not in permissions:
            ip, _agent = _client_info(request)
            try:
                record_audit(
                    db,
                    actor=user.username,
                    action="authorization.denied",
                    admin_user_id=user.id,
                    outcome="failure",
                    ip_address=ip,
                    details={"permission": permission, "path": request.url.path},
                )
            except Exception:
                pass
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _check


def require_csrf(request: Request, session_data=Depends(get_current_session)):
    _user, session = session_data
    presented = request.headers.get("X-CSRF-Token")
    if not presented or presented != session.csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return _user


def serialise_admin(user, db) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
        "permissions": sorted(user_permissions(db, user)),
    }
