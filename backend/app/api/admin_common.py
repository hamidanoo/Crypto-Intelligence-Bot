"""Shared helpers for admin routers: pagination, settings, audit."""

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.audit import record_audit
from app.models import SystemSetting


def paginate(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


def page_response(total: int, page: int, page_size: int, items) -> dict:
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def get_setting(db: Session, key: str, default: dict) -> dict:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None or not isinstance(row.value, dict):
        return default
    return row.value


def set_setting(db: Session, key: str, value: dict, description: str | None = None) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None:
        db.add(SystemSetting(key=key, value=value, description=description))
    else:
        row.value = value
        if description:
            row.description = description
    db.commit()


def audit(
    db,
    user,
    action: str,
    *,
    entity: str | None = None,
    entity_id=None,
    outcome="success",
    details=None,
):
    try:
        record_audit(
            db,
            actor=user.username,
            action=action,
            admin_user_id=user.id,
            entity=entity,
            entity_id=entity_id,
            outcome=outcome,
            details=details or {},
        )
    except Exception:
        pass


def db_or_503(func):
    """Run a DB block, mapping SQLAlchemy errors to 503."""

    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc

    return _wrapper
