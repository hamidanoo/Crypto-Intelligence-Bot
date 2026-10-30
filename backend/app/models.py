from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AdminUser(Base, TimestampMixin):
    """Dashboard administrator. Passwords are stored only as hashes."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), default="admin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TelegramGroup(Base, TimestampMixin):
    """One Telegram community group. The design supports more groups later
    without changing the core tables; group-specific settings live here."""

    __tablename__ = "telegram_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled_modules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    notification_preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SystemSetting(Base, TimestampMixin):
    """A named, persisted system setting. Values are JSON so dashboard
    controls can store structured configuration without new columns."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ApiIntegration(Base, TimestampMixin):
    """A configured external integration.

    Secrets are never stored in plain text in this table. Only a masked
    key suffix and a reference to the encrypted credential store are kept
    here; the credential encryption itself is implemented in Phase 8.
    """

    __tablename__ = "api_integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    api_key_masked: Mapped[str | None] = mapped_column(String(64))
    secret_reference: Mapped[str | None] = mapped_column(String(255))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("provider", name="uq_api_integrations_provider"),)


class MarketSnapshot(Base):
    """A point-in-time Spot market snapshot, as returned by Binance.

    Financial values are stored as Numeric (Decimal in Python),
    not binary floats, so prices and volumes do not lose
    precision. ``collected_at`` is when this system recorded the
    snapshot, in UTC.
    """

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="binance_spot", nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    price_change_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    price_change_percent_24h: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    high_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    low_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    quote_volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )


class FuturesSnapshot(Base):
    """A point-in-time Futures snapshot: funding rate, next funding
    time, mark price, and open interest, as returned by Binance."""

    __tablename__ = "futures_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="binance_futures", nullable=False)
    funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )


class AuditLog(Base, TimestampMixin):
    """Append-only record of administrative actions."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity: Mapped[str | None] = mapped_column(String(128))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
