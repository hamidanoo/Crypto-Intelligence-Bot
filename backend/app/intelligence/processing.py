"""Announcement-to-module processing for Phase 4.

Each function processes stored announcements of one
category, creates at most one module record per
announcement (dedupe by announcement_id, enforced by a
unique constraint as well), and returns created/skipped
counts. Processing never rebuilds the Phase 3 collector:
it reads the announcements the collector already stored.

Market data for Alpha tokens uses the existing Phase 2
Spot client when a symbol is present. A failed lookup
leaves price fields null and market_data_status
"unavailable"; it never writes zero, and it never stops
the token itself from being recorded.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import settings
from app.intelligence.parsing import (
    airdrop_status,
    extract_eligibility,
    parse_supported_networks,
    parse_token,
    prime_sale_status,
)
from app.models import (
    AirdropCampaign,
    AirdropEligibility,
    AlphaToken,
    AlphaTokenUpdate,
    Announcement,
    PrimeSale,
    PrimeSaleAllocationRule,
)

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - a bad market value must not break processing
        return None


async def _fetch_market(symbol: str, market_client):
    """Return (price, change_24h, volume_24h, source) or Nones.

    ``market_client`` is an injectable object with an async
    get_ticker_24hr(symbol) method (the real Phase 2 client
    qualifies). When no client is supplied, a real client is
    built from settings; any failure returns Nones.
    """
    if not symbol:
        return None, None, None, None
    try:
        if market_client is not None:
            data = await market_client.get_ticker_24hr(f"{symbol}USDT")
            return (
                _dec(data.get("price")),
                _dec(data.get("price_change_24h")),
                _dec(data.get("volume_24h")),
                "binance_spot",
            )
        from app.binance.client import BinanceClient

        client = BinanceClient(
            spot_base_url=settings.binance_spot_base_url,
            futures_base_url=settings.binance_futures_base_url,
        )
        data = await client.get_ticker_24hr(f"{symbol}USDT")
        return (
            _dec(data.get("price")),
            _dec(data.get("price_change_24h")),
            _dec(data.get("volume_24h")),
            "binance_spot",
        )
    except Exception as exc:  # noqa: BLE001 - market failure must not block the token
        logger.warning("Alpha market data unavailable for %s: %s", symbol, exc)
        return None, None, None, None


def _trading_status(title: str) -> str:
    text = (title or "").lower()
    if "trading" in text and ("live" in text or "available" in text or "now" in text):
        return "trading"
    return "announced"


async def process_alpha(db: Session, market_client=None) -> dict:
    created = skipped = 0
    announcements = (
        db.query(Announcement).filter_by(category="ALPHA").order_by(Announcement.id.asc()).all()
    )
    for announcement in announcements:
        existing = db.query(AlphaToken).filter_by(announcement_id=announcement.id).first()
        if existing is not None:
            skipped += 1
            continue
        parsed = parse_token(announcement.title)
        if parsed.get("is_multi_token"):
            token_name = "Multiple tokens (removal announcement)"
            symbol = None
            trading_status = "removal_announced"
        else:
            token_name = parsed["token_name"] or announcement.title
            symbol = parsed["token_symbol"]
            trading_status = _trading_status(announcement.title)
        price, change, volume, source = (
            await _fetch_market(symbol, market_client)
            if symbol
            else (
                None,
                None,
                None,
                None,
            )
        )
        token = AlphaToken(
            announcement_id=announcement.id,
            token_name=token_name,
            token_symbol=symbol,
            contract_address=parsed["contract_address"],
            blockchain_network=parsed["blockchain_network"],
            trading_status=trading_status,
            trading_pairs=[f"{symbol}USDT"] if symbol else [],
            announcement_url=announcement.canonical_url,
            announcement_timestamp=announcement.published_at,
            token_metadata={
                "category_confidence": announcement.category_confidence,
                "catalog": (announcement.metadata_json or {}).get("catalog_name"),
                "is_multi_token": bool(parsed.get("is_multi_token")),
            },
            data_source="binance_website_cms",
            verification_status="official_website",
            current_price=price,
            price_change_24h=change,
            volume_24h=volume,
            market_data_source=source,
            market_data_updated_at=_now_utc() if price is not None else None,
            market_data_status="available" if price is not None else "unavailable",
        )
        db.add(token)
        db.commit()
        db.refresh(token)
        db.add(
            AlphaTokenUpdate(
                token_id=token.id,
                update_type="created",
                changes={"announcement_id": announcement.id, "token_symbol": symbol},
            )
        )
        db.commit()
        created += 1
    return {"created": created, "skipped": skipped}


async def refresh_alpha_market_data(db: Session, market_client=None) -> dict:
    """Refresh market data for existing Alpha tokens and
    record an update whenever the price or trading status
    changes. Tokens without a symbol are skipped."""
    updated = skipped = 0
    for token in db.query(AlphaToken).order_by(AlphaToken.id.asc()).all():
        if not token.token_symbol:
            skipped += 1
            continue
        price, change, volume, source = await _fetch_market(token.token_symbol, market_client)
        if price is None:
            skipped += 1
            continue
        changes: dict = {}
        if token.current_price != price:
            changes["current_price"] = {"old": str(token.current_price), "new": str(price)}
        if token.volume_24h != volume:
            changes["volume_24h"] = {"old": str(token.volume_24h), "new": str(volume)}
        if not changes:
            skipped += 1
            continue
        token.current_price = price
        token.price_change_24h = change
        token.volume_24h = volume
        token.market_data_source = source
        token.market_data_updated_at = _now_utc()
        token.market_data_status = "available"
        db.add(AlphaTokenUpdate(token_id=token.id, update_type="price_update", changes=changes))
        db.commit()
        updated += 1
    return {"updated": updated, "skipped": skipped}


def process_airdrops(db: Session) -> dict:
    created = skipped = 0
    announcements = (
        db.query(Announcement).filter_by(category="AIRDROP").order_by(Announcement.id.asc()).all()
    )
    for announcement in announcements:
        existing = db.query(AirdropCampaign).filter_by(announcement_id=announcement.id).first()
        if existing is not None:
            skipped += 1
            continue
        parsed = parse_token(announcement.title)
        hints = extract_eligibility(announcement.title)
        campaign = AirdropCampaign(
            announcement_id=announcement.id,
            campaign_name=announcement.title,
            token_name=parsed["token_name"],
            token_symbol=parsed["token_symbol"],
            description=None,
            eligibility_summary=("; ".join(h["description"] for h in hints) if hints else None),
            supported_networks=parse_supported_networks(announcement.title),
            official_url=announcement.canonical_url,
            status=airdrop_status(announcement.title),
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        for hint in hints:
            db.add(
                AirdropEligibility(
                    campaign_id=campaign.id,
                    requirement_type=hint["requirement_type"],
                    description=hint["description"],
                    source_text=hint["source_text"],
                    is_confirmed_details=False,
                )
            )
        db.commit()
        created += 1
    return {"created": created, "skipped": skipped}


def process_prime_sales(db: Session) -> dict:
    created = skipped = 0
    announcements = (
        db.query(Announcement)
        .filter_by(category="PRIME_SALE")
        .order_by(Announcement.id.asc())
        .all()
    )
    for announcement in announcements:
        existing = db.query(PrimeSale).filter_by(announcement_id=announcement.id).first()
        if existing is not None:
            skipped += 1
            continue
        parsed = parse_token(announcement.title)
        sale = PrimeSale(
            announcement_id=announcement.id,
            token_name=parsed["token_name"] or announcement.title,
            token_symbol=parsed["token_symbol"],
            sale_description=None,
            trading_availability=None,
            allocation_methodology=None,
            official_url=announcement.canonical_url,
            status=prime_sale_status(announcement.title),
        )
        db.add(sale)
        db.commit()
        db.refresh(sale)
        db.add(
            PrimeSaleAllocationRule(
                sale_id=sale.id,
                formula_type="unknown",
                description=(
                    "Allocation methodology not officially confirmed in the "
                    "announcement title. Use the estimate endpoint with "
                    "verified inputs only."
                ),
            )
        )
        db.commit()
        created += 1
    return {"created": created, "skipped": skipped}


async def process_category(db: Session, category: str, market_client=None) -> dict:
    if category == "ALPHA":
        return await process_alpha(db, market_client=market_client)
    if category == "AIRDROP":
        return process_airdrops(db)
    if category == "PRIME_SALE":
        return process_prime_sales(db)
    raise ValueError(f"Unsupported intelligence category: {category}")
