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


class AnnouncementSource(Base, TimestampMixin):
    """A configured announcement source.

    Phase 3 seeds one source: the official Binance website CMS
    feed. Other sources can be added later through the API
    configuration endpoints, without changing the collector
    engine, as long as they implement the same normalised
    article shape.
    """

    __tablename__ = "announcement_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    polling_interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)


class Announcement(Base, TimestampMixin):
    """One collected announcement, stored exactly as published
    plus normalised fields for search and classification.

    Deduplication uses (source_id, external_id) and
    canonical_url, never title alone. ``content_hash`` records
    the title, code, and publication time, so a changed title
    can be detected and updated without creating a duplicate.
    ``verification_status`` describes the source, not the
    category: "official_website" means the record came from
    the official Binance website feed; category certainty is
    recorded separately in ``category_confidence``.
    """

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcement_sources.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    code: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(
        String(1024), unique=True, index=True, nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    category_confidence: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    original_content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(64), default="official_website", nullable=False
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    notification_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True, nullable=False
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_notification_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_announcements_source_external"),
    )


class CollectionRun(Base):
    """One collection attempt for one source, for observability
    and restart recovery. A run is created before fetching, so
    a failed run is visible even when no announcements arrive."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcement_sources.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    announcements_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    announcements_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class AlphaToken(Base, TimestampMixin):
    """One Binance Alpha token, derived from an official
    announcement. Fields that the announcement title does
    not contain stay null; they are never invented. The
    conventional USDT spot pair is recorded only as the
    pair probed for market data, and trading_status stays
    "announced" until trading availability is confirmed
    in an announcement title. Market data is present only
    when a Spot SYMBOLUSDT ticker was actually retrieved;
    otherwise the price fields are null and
    market_data_status is "unavailable", never zero."""

    __tablename__ = "alpha_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcements.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    token_name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_symbol: Mapped[str | None] = mapped_column(String(64), index=True)
    contract_address: Mapped[str | None] = mapped_column(String(128), index=True)
    blockchain_network: Mapped[str | None] = mapped_column(String(64), index=True)
    trading_status: Mapped[str] = mapped_column(String(64), default="announced", nullable=False)
    trading_pairs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    announcement_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    announcement_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    data_source: Mapped[str] = mapped_column(
        String(128), default="binance_website_cms", nullable=False
    )
    verification_status: Mapped[str] = mapped_column(
        String(64), default="official_website", nullable=False
    )
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    price_change_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    market_data_source: Mapped[str | None] = mapped_column(String(128))
    market_data_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    market_data_status: Mapped[str] = mapped_column(
        String(32), default="unavailable", nullable=False
    )


class AlphaTokenUpdate(Base, TimestampMixin):
    """A recorded change to an Alpha token: creation, or a
    later price or trading-status change."""

    __tablename__ = "alpha_token_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alpha_tokens.id", ondelete="CASCADE"), index=True, nullable=False
    )
    update_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    changes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AirdropCampaign(Base, TimestampMixin):
    """One Binance airdrop campaign, derived from an official
    announcement. Dates, eligibility, and reward details
    stay null when the announcement title does not contain
    them; the announcement body is not fetched in this
    phase, so most detail fields are expected to be null
    and must be read as unconfirmed, not as absent."""

    __tablename__ = "airdrop_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcements.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    campaign_name: Mapped[str] = mapped_column(String(512), nullable=False)
    token_name: Mapped[str | None] = mapped_column(String(255))
    token_symbol: Mapped[str | None] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    eligibility_summary: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distribution_schedule: Mapped[str | None] = mapped_column(Text)
    reward_info: Mapped[str | None] = mapped_column(Text)
    supported_networks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    official_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True, nullable=False)


class AirdropEligibility(Base, TimestampMixin):
    """One eligibility requirement hinted at by an
    announcement title. Title hints are not full
    conditions, so is_confirmed_details is False for
    every title-derived record in this phase."""

    __tablename__ = "airdrop_eligibility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("airdrop_campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    requirement_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    is_confirmed_details: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PrimeSale(Base, TimestampMixin):
    """One Binance Prime Sale, derived from an official
    announcement. Subscription, distribution, price, and
    commitment fields stay null when the announcement
    title does not contain them; they are never assumed
    to follow any other sale's rules."""

    __tablename__ = "prime_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcements.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    token_name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_symbol: Mapped[str | None] = mapped_column(String(64), index=True)
    sale_description: Mapped[str | None] = mapped_column(Text)
    subscription_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distribution_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trading_availability: Mapped[str | None] = mapped_column(String(255))
    subscription_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    min_commitment: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    max_commitment: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    eligible_assets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    allocation_methodology: Mapped[str | None] = mapped_column(Text)
    reward_info: Mapped[str | None] = mapped_column(Text)
    official_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True, nullable=False)


class PrimeSaleAllocationRule(Base, TimestampMixin):
    """The allocation rule recorded for one Prime Sale.
    In this phase the rule is "unknown" unless an
    announcement title states a methodology; the estimate
    endpoint then still requires the caller to supply the
    verified inputs, and never fabricates a total."""

    __tablename__ = "prime_sale_allocation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("prime_sales.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    formula_type: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    total_token_allocation: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))


class CampaignNotification(Base, TimestampMixin):
    """Duplicate prevention for module notifications:
    one row per (entity_type, entity_id,
    notification_type). A second attempt to record the
    same notification finds this row and is skipped."""

    __tablename__ = "campaign_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    announcement_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("announcements.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "notification_type",
            name="uq_campaign_notifications_entity_type",
        ),
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
