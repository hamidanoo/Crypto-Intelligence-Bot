"""Market, futures, and news collection services.

Market prices reuse MarketSnapshot and futures data
reuses FuturesSnapshot; only watchlists, alerts,
news, ratios, and collection runs are new tables.
All financial values are Decimal, converted via
str() so a binary float never introduces error.
Futures collection degrades on restriction (HTTP
451): the failure is recorded and returned, never
raised to break Spot collection or the app.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.binance.client import BinanceAPIError
from app.config import settings
from app.marketintel.classification import (
    classify_news,
    extract_related_symbols,
    news_fingerprint,
)
from app.models import (
    Announcement,
    CryptoNews,
    FuturesMarketRatio,
    FuturesSnapshot,
    MarketAlert,
    MarketCollectionRun,
    MarketSnapshot,
    NewsCollectionRun,
    NewsSource,
)

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _aware(value):
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# Market overview -------------------------------------------------------


def parse_ticker(row: dict) -> dict:
    """Normalise one 24h ticker row to Decimal fields."""
    return {
        "symbol": row["symbol"],
        "price": _dec(row["price"]),
        "price_change_24h": _dec(row.get("price_change_24h")),
        "price_change_percent_24h": _dec(row.get("price_change_percent_24h")),
        "high_24h": _dec(row.get("high_24h")),
        "low_24h": _dec(row.get("low_24h")),
        "volume_24h": _dec(row.get("volume_24h")),
        "quote_volume_24h": _dec(row.get("quote_volume_24h")),
        "source": row.get("source", "binance_spot"),
    }


def gainers_losers(tickers: list[dict], limit: int = 10, min_quote_volume=None) -> dict:
    """Top gainers and losers by 24h percent change.

    Symbols below the minimum quote volume are
    excluded from both lists (counted, not hidden):
    low-liquidity tokens are never presented as
    reliable opportunities. Rows without a percent
    change are excluded as unavailable records.
    """
    limit = max(1, min(int(limit), 50))
    minimum = _dec(min_quote_volume) if min_quote_volume is not None else None
    eligible = []
    excluded_low_liquidity = 0
    for row in tickers:
        parsed = parse_ticker(row)
        if parsed["price_change_percent_24h"] is None:
            continue
        quote = parsed["quote_volume_24h"]
        if minimum is not None and (quote is None or quote < minimum):
            excluded_low_liquidity += 1
            continue
        eligible.append(parsed)
    # Losers: most negative first; gainers: most positive first.
    losers = sorted(eligible, key=lambda r: r["price_change_percent_24h"])[:limit]
    gainers = sorted(eligible, key=lambda r: r["price_change_percent_24h"], reverse=True)[:limit]
    return {
        "gainers": gainers,
        "losers": losers,
        "excluded_low_liquidity": excluded_low_liquidity,
        "eligible_count": len(eligible),
    }


def latest_snapshots_by_symbol(db: Session) -> dict[str, MarketSnapshot]:
    """Latest MarketSnapshot per symbol, newest first."""
    rows = (
        db.query(MarketSnapshot)
        .order_by(MarketSnapshot.collected_at.desc(), MarketSnapshot.id.desc())
        .all()
    )
    latest: dict[str, MarketSnapshot] = {}
    for row in rows:
        if row.symbol not in latest:
            latest[row.symbol] = row
    return latest


def is_stale(
    collected_at, freshness_minutes: int | None = None, now: datetime | None = None
) -> bool:
    """True when a snapshot is older than the freshness window."""
    if collected_at is None:
        return True
    window = (
        freshness_minutes if freshness_minutes is not None else settings.market_freshness_minutes
    )
    moment = _aware(collected_at)
    return ((now or _now_utc()) - moment) > timedelta(minutes=window)


def detect_movements(
    db: Session,
    latest: list[MarketSnapshot],
    previous: dict[str, MarketSnapshot],
    *,
    price_threshold=None,
    volume_spike_multiplier=None,
    cooldown_minutes: int | None = None,
    now: datetime | None = None,
) -> list[MarketAlert]:
    """Create alerts for threshold crossings, once per cooldown.

    Compares each latest snapshot with the previous
    snapshot for the same symbol. A price alert fires
    when the move reaches the configured threshold
    (the stored threshold is the highest crossed
    level: 10% when reached, else the configured
    level); a volume alert fires when quote volume
    reaches the configured multiple of the previous
    snapshot. An alert of the same symbol + type
    within the cooldown window is skipped, so the
    same movement is never alerted repeatedly.
    """
    moment = now or _now_utc()
    threshold = Decimal(
        str(
            price_threshold
            if price_threshold is not None
            else settings.market_price_alert_threshold_percent
        )
    )
    spike = Decimal(
        str(
            volume_spike_multiplier
            if volume_spike_multiplier is not None
            else settings.market_volume_spike_multiplier
        )
    )
    cooldown = (
        cooldown_minutes if cooldown_minutes is not None else settings.market_alert_cooldown_minutes
    )
    created: list[MarketAlert] = []
    for snapshot in latest:
        baseline = previous.get(snapshot.symbol)
        if baseline is None or baseline.price is None or snapshot.price is None:
            continue
        if baseline.price == 0:
            continue
        change = (snapshot.price - baseline.price) / baseline.price * Decimal(100)
        candidates: list[tuple[str, Decimal]] = []
        if change >= threshold:
            crossed = Decimal(10) if change >= Decimal(10) else threshold
            candidates.append(("price_up", crossed))
        elif change <= -threshold:
            crossed = Decimal(10) if change <= Decimal(-10) else threshold
            candidates.append(("price_down", crossed))
        if (
            baseline.quote_volume_24h
            and baseline.quote_volume_24h > 0
            and snapshot.quote_volume_24h is not None
            and snapshot.quote_volume_24h >= baseline.quote_volume_24h * spike
        ):
            candidates.append(("volume_spike", spike))
        for alert_type, level in candidates:
            recent = (
                db.query(MarketAlert)
                .filter(
                    MarketAlert.symbol == snapshot.symbol,
                    MarketAlert.alert_type == alert_type,
                    MarketAlert.triggered_at >= moment - timedelta(minutes=cooldown),
                )
                .first()
            )
            if recent is not None:
                continue
            alert = MarketAlert(
                symbol=snapshot.symbol,
                alert_type=alert_type,
                threshold_percent=level,
                baseline_price=baseline.price,
                current_price=snapshot.price,
                change_percent=change if alert_type != "volume_spike" else None,
                triggered_at=moment,
                cooldown_until=moment + timedelta(minutes=cooldown),
                status="triggered",
                source="binance_spot",
            )
            db.add(alert)
            created.append(alert)
    if created:
        db.commit()
        for alert in created:
            db.refresh(alert)
    return created


# Futures ---------------------------------------------------------------


def _record_run(
    db: Session,
    job_name: str,
    status: str,
    requested: int,
    collected: int,
    error: str | None,
    started: datetime,
) -> MarketCollectionRun:
    run = MarketCollectionRun(
        job_name=job_name,
        started_at=started,
        completed_at=_now_utc(),
        status=status,
        symbols_requested=requested,
        symbols_collected=collected,
        error_message=error,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def collect_futures(db: Session, client, symbols: list[str]) -> dict:
    """Collect funding + open interest into FuturesSnapshot.

    Returns availability explicitly: "available" when
    at least one symbol collected, "degraded" when
    some failed, "unavailable" when all failed (for
    example HTTP 451). Failures never raise here, so
    a Futures outage cannot break Spot collection.
    """
    started = _now_utc()
    collected = 0
    errors: list[str] = []
    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        try:
            funding = await client.get_funding_rate(symbol)
            premium = await client.get_premium_index(symbol)
            interest = await client.get_open_interest(symbol)
        except BinanceAPIError as exc:
            errors.append(f"{symbol}: {exc}")
            logger.warning("Futures collection failed for %s: %s", symbol, exc)
            continue
        except Exception as exc:  # noqa: BLE001 - degraded mode must not crash
            errors.append(f"{symbol}: {exc}")
            logger.warning("Futures collection failed for %s: %s", symbol, exc)
            continue
        db.add(
            FuturesSnapshot(
                symbol=symbol,
                source="binance_futures",
                funding_rate=_dec(funding.get("funding_rate")),
                next_funding_time=premium.get("next_funding_time"),
                mark_price=_dec(premium.get("mark_price")),
                open_interest=_dec(interest.get("open_interest")),
                collected_at=_now_utc(),
            )
        )
        collected += 1
    db.commit()
    if collected == len(symbols) and symbols:
        status = "available"
    elif collected > 0:
        status = "degraded"
    else:
        status = "unavailable"
    _record_run(
        db,
        "futures_collection",
        status,
        len(symbols),
        collected,
        "; ".join(errors) or None,
        started,
    )
    return {"status": status, "collected": collected, "requested": len(symbols), "errors": errors}


async def collect_futures_ratios(db: Session, client, symbols: list[str]) -> dict:
    """Collect long/short datasets, each labelled by type."""
    started = _now_utc()
    collected = 0
    errors: list[str] = []
    kinds = ["global_account", "top_account", "top_position", "taker"]
    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        for kind in kinds:
            try:
                data = await client.get_futures_long_short(symbol, kind)
            except BinanceAPIError as exc:
                errors.append(f"{symbol}/{kind}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - degraded mode
                errors.append(f"{symbol}/{kind}: {exc}")
                continue
            db.add(
                FuturesMarketRatio(
                    symbol=symbol,
                    ratio_type=data["ratio_type"],
                    long_ratio=_dec(data.get("long_ratio")),
                    short_ratio=_dec(data.get("short_ratio")),
                    long_short_ratio=_dec(data.get("long_short_ratio")),
                    period=data.get("period"),
                    source="binance_futures",
                    collected_at=_now_utc(),
                )
            )
            collected += 1
    db.commit()
    status = "available" if collected else "unavailable"
    if errors and collected:
        status = "degraded"
    _record_run(
        db,
        "futures_ratios",
        status,
        len(symbols) * len(kinds),
        collected,
        "; ".join(errors) or None,
        started,
    )
    return {"status": status, "collected": collected, "errors": errors}


def latest_futures_by_symbol(db: Session) -> dict[str, FuturesSnapshot]:
    rows = (
        db.query(FuturesSnapshot)
        .order_by(FuturesSnapshot.collected_at.desc(), FuturesSnapshot.id.desc())
        .all()
    )
    latest: dict[str, FuturesSnapshot] = {}
    for row in rows:
        if row.symbol not in latest:
            latest[row.symbol] = row
    return latest


def funding_alerts(
    db: Session, *, threshold=None, now: datetime | None = None
) -> list[MarketAlert]:
    """Funding-rate alerts from the latest snapshots.

    Fires funding_high when the rate is at or above
    the threshold and funding_low when at or below
    its negative, reusing the MarketAlert cooldown
    logic (one alert per symbol + type per window).
    """
    moment = now or _now_utc()
    limit = Decimal(
        str(threshold if threshold is not None else settings.futures_funding_alert_threshold)
    )
    cooldown = settings.market_alert_cooldown_minutes
    created: list[MarketAlert] = []
    for symbol, snapshot in latest_futures_by_symbol(db).items():
        if snapshot.funding_rate is None:
            continue
        alert_type = None
        if snapshot.funding_rate >= limit:
            alert_type = "funding_high"
        elif snapshot.funding_rate <= -limit:
            alert_type = "funding_low"
        if alert_type is None:
            continue
        recent = (
            db.query(MarketAlert)
            .filter(
                MarketAlert.symbol == symbol,
                MarketAlert.alert_type == alert_type,
                MarketAlert.triggered_at >= moment - timedelta(minutes=cooldown),
            )
            .first()
        )
        if recent is not None:
            continue
        created.append(
            MarketAlert(
                symbol=symbol,
                alert_type=alert_type,
                threshold_percent=limit * Decimal(100),
                baseline_price=None,
                current_price=snapshot.mark_price,
                change_percent=snapshot.funding_rate * Decimal(100),
                triggered_at=moment,
                cooldown_until=moment + timedelta(minutes=cooldown),
                status="triggered",
                source="binance_futures",
            )
        )
    if created:
        db.add_all(created)
        db.commit()
        for alert in created:
            db.refresh(alert)
    return created


def open_interest_change(db: Session, symbol: str) -> Decimal | None:
    """Percent change between the two latest OI snapshots."""
    rows = (
        db.query(FuturesSnapshot)
        .filter(FuturesSnapshot.symbol == symbol)
        .order_by(FuturesSnapshot.collected_at.desc(), FuturesSnapshot.id.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return None
    latest, previous = rows[0], rows[1]
    if not previous.open_interest or previous.open_interest == 0 or latest.open_interest is None:
        return None
    return (latest.open_interest - previous.open_interest) / previous.open_interest * Decimal(100)


# News ------------------------------------------------------------------


_ANNOUNCEMENT_TO_NEWS = {
    "SPOT_LISTING": "LISTINGS",
    "FUTURES_LISTING": "LISTINGS",
    "DELISTING": "DELISTINGS",
}


def ensure_binance_news_source(db: Session) -> NewsSource:
    source = db.query(NewsSource).filter(NewsSource.name == "Binance Announcements").first()
    if source is None:
        source = NewsSource(
            name="Binance Announcements",
            source_type="binance_announcements",
            feed_url=None,
            enabled=True,
            reliability_note=(
                "Official Binance website announcement feed, "
                "the same source as Phase 3. Undocumented website "
                "feed, not a documented public API."
            ),
        )
        db.add(source)
        db.commit()
        db.refresh(source)
    return source


def process_news(db: Session, categories: list[str] | None = None) -> dict:
    """Create CryptoNews rows from stored announcements.

    Dedupe by announcement_id (unique) and by
    fingerprint; a second run creates nothing new.
    Summary stays null because article bodies are
    unavailable — never invented.
    """
    started = _now_utc()
    source = ensure_binance_news_source(db)
    query = db.query(Announcement)
    if categories:
        query = query.filter(Announcement.category.in_(categories))
    announcements = query.order_by(Announcement.id.asc()).all()
    found = len(announcements)
    created = 0
    skipped = 0
    for announcement in announcements:
        existing = (
            db.query(CryptoNews).filter(CryptoNews.announcement_id == announcement.id).first()
        )
        if existing is not None:
            skipped += 1
            continue
        fingerprint = news_fingerprint(announcement.title, announcement.canonical_url)
        if db.query(CryptoNews).filter(CryptoNews.fingerprint == fingerprint).first() is not None:
            skipped += 1
            continue
        category = classify_news(announcement.title, announcement.category)
        db.add(
            CryptoNews(
                source_id=source.id,
                announcement_id=announcement.id,
                headline=announcement.title,
                summary=None,
                original_url=announcement.canonical_url,
                publisher="Binance",
                category=category,
                related_symbols=extract_related_symbols(announcement.title),
                published_at=announcement.published_at,
                fingerprint=fingerprint,
                processing_status="processed",
            )
        )
        created += 1
    db.commit()
    run = NewsCollectionRun(
        source_id=source.id,
        started_at=started,
        completed_at=_now_utc(),
        status="success",
        found=found,
        created=created,
        skipped=skipped,
    )
    db.add(run)
    db.commit()
    return {"found": found, "created": created, "skipped": skipped}


def parse_rss(xml_text: str) -> list[dict]:
    """Parse an RSS/Atom feed with stdlib XML only.

    Returns headline, URL, published text, and
    description (used as the summary only when the
    publisher supplied it; truncated to 500 chars).
    Malformed items are skipped, never guessed.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = published = description = None
        for child in element:
            child_tag = child.tag.split("}")[-1]
            text = (child.text or "").strip() or None
            if child_tag == "title":
                title = text
            elif child_tag == "link":
                link = text or child.attrib.get("href")
            elif child_tag in ("pubDate", "published", "updated"):
                published = published or text
            elif child_tag == "description":
                description = text
        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "published": published,
                    "description": description[:500] if description else None,
                }
            )
    return items


def _parse_rss_date(text: str | None):
    if not text:
        return None
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return _aware(parsed)


def collect_rss_items(db: Session, source: NewsSource, items: list[dict]) -> dict:
    """Persist parsed RSS items, deduped by fingerprint/URL."""
    created = 0
    skipped = 0
    for item in items:
        fingerprint = news_fingerprint(item["title"], item["link"])
        existing = (
            db.query(CryptoNews)
            .filter(
                (CryptoNews.fingerprint == fingerprint) | (CryptoNews.original_url == item["link"])
            )
            .first()
        )
        if existing is not None:
            skipped += 1
            continue
        db.add(
            CryptoNews(
                source_id=source.id,
                announcement_id=None,
                headline=item["title"],
                summary=item.get("description"),
                original_url=item["link"],
                publisher=source.name,
                category=classify_news(item["title"]),
                related_symbols=extract_related_symbols(item["title"]),
                published_at=_parse_rss_date(item.get("published")),
                fingerprint=fingerprint,
                processing_status="processed",
            )
        )
        created += 1
    db.commit()
    return {"found": len(items), "created": created, "skipped": skipped}
