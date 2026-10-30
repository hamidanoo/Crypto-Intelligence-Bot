"""Append-only audit logging with secret redaction.

Audit rows are written for administrative activity and
are never updated or deleted through any API endpoint.
Values under secret-like keys are replaced before the
row is written, so passwords, session tokens, reset
tokens, API secrets, and bot tokens can never leak into
audit history or logs.
"""

import re
from datetime import datetime, timezone

from app.models import AuditLog

_SECRET_KEY = re.compile(r"password|token|secret|api_key|bot_token|apikey", re.IGNORECASE)


def _sanitize(value):
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if _SECRET_KEY.search(str(key)) else _sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def record_audit(
    db,
    *,
    actor: str,
    action: str,
    admin_user_id: int | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    outcome: str = "success",
    ip_address: str | None = None,
    correlation_id: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        admin_user_id=admin_user_id,
        actor=actor,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=_sanitize(details or {}),
        correlation_id=correlation_id,
        ip_address=ip_address,
        outcome=outcome,
    )
    db.add(row)
    db.commit()
    return row


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
