"""Telegram volume reports for Phase 6.

After collection, every newly completed (complete or
partial) interval with no sent CompetitionVolumeReport
row gets one report. Incomplete intervals get no
report, ever — an incomplete interval is never
published as complete. A sent report is never
re-sent: the unique constraint on (competition,
pair, interval_start) plus the status check blocks
retries and re-collections. A failed row may be
retried and is updated in place, never duplicated.

Sending follows the Phase 3 pattern: an injectable
sender (``bot``) for tests, otherwise a real bot
created from the configured token and group id.
Notifications follow the existing config style:
VOLUME_NOTIFICATIONS_ENABLED (default on) gates
the pass, and without a token/group id sending is
skipped without marking anything sent, so live
delivery remains honestly unverified without a
token. Telegram errors and rate limits are recorded
on the report row, never raised to break other
competitions.

Every report keeps the three volumes strictly
separate and labelled: public market volume (from
public trade data), estimated eligible volume (only
with a verified multiplier, otherwise "Unavailable"),
and official eligible volume, which is always
"Unavailable" in Phase 6.
"""

import html
import logging
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.announcements.notifications import send_telegram_message
from app.config import settings
from app.models import Competition, CompetitionVolumeInterval, CompetitionVolumeReport
from app.volume.aggregation import cumulative_volume
from app.volume.intervals import as_utc

logger = logging.getLogger(__name__)
PKT = ZoneInfo("Asia/Karachi")


def _now_utc():
    from datetime import datetime

    return datetime.now(timezone.utc)


def format_utc(value) -> str:
    if value is None:
        return "Unavailable"
    return as_utc(value).strftime("%Y-%m-%d %H:%M UTC")


def format_pkt(value) -> str:
    if value is None:
        return "Unavailable"
    return as_utc(value).astimezone(PKT).strftime("%Y-%m-%d %H:%M PKT")


def _dec(value) -> str:
    return str(value) if value is not None else "Unavailable"


def format_volume_message(
    competition: Competition,
    interval: CompetitionVolumeInterval,
    cumulative: dict | None = None,
) -> str:
    """Format one interval report. Public, estimated,
    and official volumes are never blurred: official
    eligible volume is always "Unavailable" here."""
    if cumulative is None:
        cumulative = {
            "public_base_volume": interval.public_base_volume,
            "public_quote_volume": interval.public_quote_volume,
        }
    lines = [
        "📊 <b>Competition volume update</b>",
        "",
        html.escape(competition.competition_name),
        f"Trading Pair: {html.escape(interval.trading_pair)}",
        (
            f"Reporting Period: {format_utc(interval.interval_start)} "
            f"– {format_utc(interval.interval_end)} "
            f"({format_pkt(interval.interval_start)} – {format_pkt(interval.interval_end)})"
        ),
    ]
    if interval.public_base_volume is not None and interval.public_quote_volume is not None:
        quote = interval.quote_asset or "quote"
        base_label = interval.base_asset or ""
        public_line = (
            f"Public Market Volume: {interval.public_base_volume} "
            f"{base_label} / {interval.public_quote_volume} {quote}"
        )
        lines.append(" ".join(public_line.split()))
    else:
        lines.append("Public Market Volume: Unavailable")
    if interval.estimated_eligible_volume is not None:
        lines.append(
            f"Estimated Eligible Volume: {interval.estimated_eligible_volume} "
            f"(method: {interval.calculation_method or 'verified multiplier'})"
        )
    else:
        lines.append("Estimated Eligible Volume: Unavailable")
    lines.append("Official Eligible Volume: Unavailable")
    lines.append(f"Data Status: {html.escape(interval.data_status or 'incomplete')}")
    if cumulative.get("public_base_volume") is not None:
        lines.append(f"Cumulative Public Volume: {cumulative['public_base_volume']}")
    if cumulative.get("public_quote_volume") is not None:
        lines.append(f"Cumulative Public Quote Volume: {cumulative['public_quote_volume']}")
    lines.append(f"Last Updated: {format_utc(interval.collected_at)}")
    lines.append("Calculation Method: Binance public trade data (aggTrades)")
    if interval.recalculated:
        lines.append("Note: This interval was recalculated from updated trade data.")
    if competition.official_url:
        lines.append(f'<a href="{html.escape(competition.official_url)}">Read announcement</a>')
    return "\n".join(lines)


async def send_volume_reports(db: Session, *, bot=None) -> dict:
    """Report every completed/partial interval with no
    sent report row. Returns sent/failed/skipped
    counts. Skipped covers notifications disabled and
    Telegram not configured (nothing is marked sent
    in those cases)."""
    if not settings.volume_notifications_enabled:
        return {"sent": 0, "failed": 0, "skipped": 0, "disabled": True}
    if bot is None and (not settings.telegram_bot_token or not settings.telegram_group_id):
        logger.warning("Telegram not configured; volume reports skipped, not marked sent")
        return {"sent": 0, "failed": 0, "skipped": 0, "disabled": False, "unconfigured": True}
    intervals = (
        db.query(CompetitionVolumeInterval)
        .filter(CompetitionVolumeInterval.data_status.in_(["complete", "partial"]))
        .order_by(CompetitionVolumeInterval.interval_start.asc())
        .all()
    )
    sent = failed = skipped = 0
    for interval in intervals:
        existing = (
            db.query(CompetitionVolumeReport)
            .filter_by(
                competition_id=interval.competition_id,
                trading_pair=interval.trading_pair,
                interval_start=as_utc(interval.interval_start),
            )
            .first()
        )
        if existing is not None and existing.status == "sent":
            skipped += 1
            continue
        competition = db.query(Competition).filter_by(id=interval.competition_id).first()
        if competition is None:
            skipped += 1
            continue
        cumulative = cumulative_volume(db, interval.competition_id, interval.trading_pair)
        text = format_volume_message(competition, interval, cumulative)
        if existing is None:
            report = CompetitionVolumeReport(
                competition_id=interval.competition_id,
                trading_pair=interval.trading_pair,
                interval_start=as_utc(interval.interval_start),
                interval_end=as_utc(interval.interval_end),
                message_text=text,
                status="pending",
            )
            db.add(report)
            try:
                db.commit()
            except Exception:  # noqa: BLE001 - concurrent reporter won the race
                # A concurrent reporting pass created the
                # same (competition, pair, interval) row
                # first; skip instead of aborting the
                # whole reporting pass (Phase 9 audit).
                db.rollback()
                skipped += 1
                continue
            db.refresh(report)
        else:
            report = existing
            report.message_text = text
            report.status = "pending"
            db.commit()
        try:
            await send_telegram_message(settings.telegram_group_id, text, bot=bot)
        except Exception as exc:  # noqa: BLE001 - delivery failures are recorded, not raised
            report.status = "failed"
            report.error_message = f"{type(exc).__name__}: {exc}"
            db.commit()
            logger.warning(
                "Volume report failed for competition %s pair %s interval %s: %s",
                interval.competition_id,
                interval.trading_pair,
                interval.interval_start,
                exc,
            )
            failed += 1
            continue
        report.status = "sent"
        report.sent_at = _now_utc()
        report.error_message = None
        db.commit()
        sent += 1
    return {"sent": sent, "failed": failed, "skipped": skipped}
