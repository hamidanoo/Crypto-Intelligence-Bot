"""Telegram message formatters and duplicate prevention
for Alpha, airdrop, and Prime Sale notifications.

Formatting reuses the Phase 3 approach: HTML with the
title escaped, and a source link whenever a URL is
available. Duplicate prevention reuses the same idea as
Phase 3 (a sent record blocks a second send), here via
the CampaignNotification table: one row per
(entity_type, entity_id, notification_type).
"""

import html
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import CampaignNotification

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _link(url: str | None, label: str = "Read announcement") -> str:
    if not url:
        return ""
    return f'\n<a href="{html.escape(url)}">{label}</a>'


def format_alpha_message(token) -> str:
    symbol = f" ({token.token_symbol})" if token.token_symbol else ""
    price = f"Price: {token.current_price} USDT\n" if token.current_price is not None else ""
    network = (
        f"Network: {html.escape(token.blockchain_network)}\n" if token.blockchain_network else ""
    )
    return (
        f"🟢 <b>New Binance Alpha token</b>\n\n"
        f"{html.escape(token.token_name)}{html.escape(symbol)}\n"
        f"{price}{network}"
        f"Trading status: {html.escape(token.trading_status or 'announced')}"
        f"{_link(token.announcement_url)}"
    )


def format_airdrop_message(campaign) -> str:
    symbol = f" ({campaign.token_symbol})" if campaign.token_symbol else ""
    token = campaign.token_name or ""
    return (
        f"🎁 <b>New Binance airdrop</b>\n\n"
        f"{html.escape(campaign.campaign_name)}\n"
        f"{html.escape(token)}{html.escape(symbol)}\n"
        f"Status: {html.escape(campaign.status or 'UNKNOWN')}"
        f"{_link(campaign.official_url)}"
    )


def format_prime_sale_message(sale) -> str:
    symbol = f" ({sale.token_symbol})" if sale.token_symbol else ""
    return (
        f"💎 <b>New Binance Prime Sale</b>\n\n"
        f"{html.escape(sale.token_name)}{html.escape(symbol)}\n"
        f"Status: {html.escape(sale.status or 'UNKNOWN')}"
        f"{_link(sale.official_url)}"
    )


def record_notification(
    db: Session,
    entity_type: str,
    entity_id: int,
    notification_type: str,
    announcement_id: int | None = None,
) -> bool:
    """Record a notification, returning False (not created)
    when the same entity+type was already recorded, so a
    second run never sends a duplicate."""
    existing = (
        db.query(CampaignNotification)
        .filter_by(
            entity_type=entity_type, entity_id=entity_id, notification_type=notification_type
        )
        .first()
    )
    if existing is not None:
        return False
    record = CampaignNotification(
        entity_type=entity_type,
        entity_id=entity_id,
        notification_type=notification_type,
        announcement_id=announcement_id,
        status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return True
