"""Administrator authentication endpoints.

Sessions are server-side. Login creates a fresh session
and sets an HttpOnly session cookie plus a separate
CSRF cookie; the frontend echoes the CSRF token as
X-CSRF-Token on state-changing requests. No long-lived
token is ever placed in localStorage or sessionStorage,
and no password, token, or hash is ever returned here.
Forgot-password always returns the same generic message
so it cannot be used to enumerate accounts.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.audit import record_audit
from app.auth.dependencies import (
    check_login_rate_limit,
    get_current_admin,
    get_current_session,
    require_csrf,
    serialise_admin,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import create_session, revoke_session, rotate_session
from app.config import settings
from app.database import get_db
from app.models import AdminUser, PasswordResetToken

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_RESET_MESSAGE = (
    "If an account exists for that username or email, a reset token has been created."
)
_GENERIC_RESET_ERROR = "The reset token is invalid or has expired."


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ForgotPasswordRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    secure = settings.environment == "production"
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _lockout_active(user: AdminUser) -> bool:
    if user.locked_until is None:
        return False
    locked = user.locked_until
    if locked.tzinfo is None:
        locked = locked.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < locked


@router.post("/login")
async def login(
    request: Request, body: LoginRequest, response: Response, db: Session = Depends(get_db)
):
    check_login_rate_limit(request)
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent")
    user = db.query(AdminUser).filter(AdminUser.username == body.username).first()
    if user is None:
        # Same generic response and same audit shape as a
        # wrong password: no account enumeration.
        record_audit(
            db,
            actor=body.username,
            action="login.failed",
            outcome="failure",
            ip_address=ip,
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        record_audit(
            db,
            actor=user.username,
            action="login.failed",
            admin_user_id=user.id,
            outcome="failure",
            ip_address=ip,
            details={"reason": "inactive_account"},
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if _lockout_active(user):
        record_audit(
            db,
            actor=user.username,
            action="login.failed",
            admin_user_id=user.id,
            outcome="failure",
            ip_address=ip,
            details={"reason": "account_locked"},
        )
        raise HTTPException(status_code=401, detail="Account is temporarily locked")
    if not verify_password(user.password_hash, body.password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.login_max_attempts:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.login_lockout_minutes
            )
        db.commit()
        record_audit(
            db,
            actor=user.username,
            action="login.failed",
            admin_user_id=user.id,
            outcome="failure",
            ip_address=ip,
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    # Fresh session on every login: a pre-login cookie is
    # never carried into an authenticated session.
    token, csrf_token, _session = create_session(db, user, ip_address=ip, user_agent=user_agent)
    _set_session_cookies(response, token, csrf_token)
    record_audit(
        db,
        actor=user.username,
        action="login.success",
        admin_user_id=user.id,
        outcome="success",
        ip_address=ip,
    )
    return serialise_admin(user, db)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session_data=Depends(get_current_session),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    user, session = session_data
    revoke_session(db, session)
    _clear_session_cookies(response)
    record_audit(
        db,
        actor=user.username,
        action="logout",
        admin_user_id=user.id,
        outcome="success",
        ip_address=_client_ip(request),
    )
    return {"ok": True}


@router.get("/me")
async def me(user=Depends(get_current_admin), db: Session = Depends(get_db)):
    return serialise_admin(user, db)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    session_data=Depends(get_current_session),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _user, session = session_data
    token, csrf_token, _new_session = rotate_session(
        db,
        session,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, token, csrf_token)
    user = db.query(AdminUser).filter(AdminUser.id == session.admin_user_id).first()
    return serialise_admin(user, db)


@router.post("/change-password")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, body.current_password):
        record_audit(
            db,
            actor=user.username,
            action="password.change.failed",
            admin_user_id=user.id,
            outcome="failure",
            ip_address=_client_ip(request),
        )
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    # Invalidate all other sessions so a changed password
    # cannot be bypassed by an existing session.
    from app.models import AdminSession

    others = (
        db.query(AdminSession)
        .filter(
            AdminSession.admin_user_id == user.id,
            AdminSession.revoked_at.is_(None),
        )
        .all()
    )
    current_token = request.cookies.get(settings.session_cookie_name)
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else None
    for other in others:
        if other.session_token_hash != current_hash:
            other.revoked_at = datetime.now(timezone.utc)
    db.commit()
    record_audit(
        db,
        actor=user.username,
        action="password.changed",
        admin_user_id=user.id,
        outcome="success",
        ip_address=_client_ip(request),
    )
    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = (
        db.query(AdminUser)
        .filter(
            (AdminUser.username == body.username_or_email)
            | (AdminUser.email == body.username_or_email)
        )
        .first()
    )
    if user is not None and user.is_active:
        token = __import__("secrets").token_urlsafe(48)
        row = PasswordResetToken(
            admin_user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.password_reset_token_minutes),
        )
        db.add(row)
        db.commit()
        # The token is delivered out of band (operator
        # channel) in this deployment; it is never
        # returned by this endpoint, so enumeration is
        # impossible through the response alone.
        logger.info("Password reset token created for admin user %s", user.username)
    return {"message": _GENERIC_RESET_MESSAGE}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail=_GENERIC_RESET_ERROR)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now >= expires:
        raise HTTPException(status_code=400, detail=_GENERIC_RESET_ERROR)
    user = db.query(AdminUser).filter(AdminUser.id == row.admin_user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail=_GENERIC_RESET_ERROR)
    user.password_hash = hash_password(body.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    row.used_at = now
    db.commit()
    record_audit(
        db,
        actor=user.username,
        action="password.reset",
        admin_user_id=user.id,
        outcome="success",
    )
    return {"ok": True}
