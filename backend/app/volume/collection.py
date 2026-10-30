"""Volume collection and backfill for Phase 6.

For each ACTIVE/UPCOMING competition (global runs;
a manual single-competition collect processes that
competition regardless of status, because the caller
asked for it explicitly), and each of its Phase 5
CompetitionTradingPair rows, missed completed
intervals are determined from the per-pair
checkpoint, or the competition start, or the last
24 hours when no start date exists. Backfill is
capped at 48 intervals per pair per run (setting
VOLUME_BACKFILL_MAX_INTERVALS_PER_PAIR) to bound
Binance API usage; intervals beyond the cap are
counted as skipped and picked up by the next run.

Fetching uses Binance Spot aggTrades only, paged
by fromId within [interval_start, interval_end),
with a bounded page guard (setting
VOLUME_MAX_PAGES_PER_INTERVAL, default 50). Binance
rejects fromId combined with startTime/endTime
("Combination of optional parameters invalid",
verified live 2026-10-30), so paging works in two
steps: the first page uses startTime/endTime only,
and later pages use fromId only (no time window),
with trades filtered to the interval by bucketing
(the interval filter is applied regardless, so
trades at or after interval_end from a fromId-only
page are excluded, never counted). If the guard is
exceeded, that interval is marked incomplete and
collection continues with the next interval. If
aggTrades is unavailable for a symbol, the interval
is marked incomplete — klines volume is never
substituted silently and no value is fabricated.

Idempotence and overlap safety: the interval unique
constraint (competition, pair, interval_start)
prevents duplicate rows; re-collecting an interval
from the same trade set yields identical totals and
is counted as skipped, while a re-fetch returning
additional late trades updates the stored totals and
marks the interval recalculated, without creating a
duplicate row and without re-sending a Telegram
report (reporting checks the sent report row).
The scheduler job runs with max_instances=1, and
collection itself relies on the unique constraint,
so overlapping runs cannot duplicate intervals.
One pair's failure never stops other pairs or
competitions; errors are recorded on the run.

Checkpoint rule: the checkpoint advances only over
the longest prefix of complete/partial intervals
starting at the run's window start. An incomplete
interval stops the advance (it is retried next run),
even though later intervals in the same run are
still collected; the next run re-processes from the
checkpoint, idempotently, so no interval is lost.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.binance.client import BinanceAPIError
from app.config import settings
from app.models import (
    Competition,
    CompetitionPairConfiguration,
    CompetitionTradingPair,
    CompetitionVolumeCheckpoint,
    CompetitionVolumeCollectionRun,
    CompetitionVolumeInterval,
)
from app.volume.aggregation import METHOD_PUBLIC, bucket_trades, estimate_eligible_volume
from app.volume.intervals import as_utc, completed_intervals_between, is_partial_interval

logger = logging.getLogger(__name__)

DEFAULT_MAX_INTERVALS = 48
DEFAULT_MAX_PAGES = 50
LOOKBACK_NO_START = timedelta(hours=24)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _config_for(db: Session, competition_id: int, pair: str):
    return (
        db.query(CompetitionPairConfiguration)
        .filter_by(competition_id=competition_id, trading_pair=pair)
        .first()
    )


def _pair_rows(db: Session, competition_id: int) -> list[CompetitionTradingPair]:
    return (
        db.query(CompetitionTradingPair)
        .filter_by(competition_id=competition_id)
        .order_by(CompetitionTradingPair.id.asc())
        .all()
    )


def _checkpoint_for(db: Session, competition_id: int, pair: str):
    return (
        db.query(CompetitionVolumeCheckpoint)
        .filter_by(competition_id=competition_id, trading_pair=pair)
        .first()
    )


async def _fetch_interval_trades(
    client, pair: str, start: datetime, end: datetime, max_pages: int
) -> tuple[list[dict], bool]:
    """Fetch all aggTrades in [start, end) for a pair.
    Returns (trades, page_guard_hit). Binance rejects
    fromId combined with startTime/endTime, so the
    first page is fetched with the time window only
    and later pages with fromId only; bucketing
    filters every page to the interval regardless.
    A BinanceAPIError propagates to the caller, which
    marks the interval incomplete."""
    trades: list[dict] = []
    page = await client.get_agg_trades(pair, start_time=start, end_time=end, limit=1000)
    pages = 1
    trades.extend(page)
    if len(page) < 1000:
        return trades, False
    from_id = page[-1].get("trade_id", page[-1].get("id"))
    while from_id is not None:
        if pages >= max_pages:
            return trades, True
        pages += 1
        page = await client.get_agg_trades(pair, from_id=int(from_id) + 1, limit=1000)
        if not page:
            break
        trades.extend(page)
        if len(page) < 1000:
            break
        first_time = page[0].get("timestamp")
        if first_time is not None and as_utc(first_time) >= as_utc(end):
            break
        from_id = page[-1].get("trade_id", page[-1].get("id"))
    return trades, False


def upsert_interval(
    db: Session,
    competition: Competition,
    pair_row: CompetitionTradingPair,
    interval_start: datetime,
    interval_end: datetime,
    bucket: dict,
    configuration,
    *,
    data_status: str,
    page_guard_hit: bool = False,
) -> str:
    """Insert or update one interval row. Returns
    "created", "updated", or "skipped" (identical
    totals). An update that changes stored totals on
    a previously complete/partial interval sets
    recalculated=True. Callers pass data_status
    "incomplete" with a null bucket on fetch failure;
    in that case volumes stay null, never zero."""
    pair = pair_row.pair
    if data_status == "incomplete":
        base = quote = estimated = None
        method = METHOD_PUBLIC
    else:
        base = bucket["public_base_volume"]
        quote = bucket["public_quote_volume"]
        estimated, method = estimate_eligible_volume(base, configuration)
        if configuration is not None and configuration.calculation_method and estimated is not None:
            method = configuration.calculation_method
    existing = (
        db.query(CompetitionVolumeInterval)
        .filter_by(
            competition_id=competition.id, trading_pair=pair, interval_start=as_utc(interval_start)
        )
        .first()
    )
    if existing is None:
        row = CompetitionVolumeInterval(
            competition_id=competition.id,
            trading_pair=pair,
            base_asset=pair_row.base_asset,
            quote_asset=pair_row.quote_asset,
            interval_start=as_utc(interval_start),
            interval_end=as_utc(interval_end),
            public_base_volume=base,
            public_quote_volume=quote,
            estimated_eligible_volume=estimated,
            official_eligible_volume=None,
            calculation_method=method,
            data_status=data_status,
            recalculated=False,
            collected_at=_now_utc(),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return "skipped"
        return "created"
    changed = (
        existing.public_base_volume != base
        or existing.public_quote_volume != quote
        or existing.estimated_eligible_volume != estimated
        or existing.data_status != data_status
    )
    if not changed:
        return "skipped"
    was_counted = existing.data_status in ("complete", "partial")
    existing.public_base_volume = base
    existing.public_quote_volume = quote
    existing.estimated_eligible_volume = estimated
    existing.official_eligible_volume = None
    existing.calculation_method = method
    existing.data_status = data_status
    existing.collected_at = _now_utc()
    if was_counted and data_status in ("complete", "partial"):
        existing.recalculated = True
    db.commit()
    return "updated"


async def collect_interval(
    db: Session,
    client,
    competition: Competition,
    pair_row: CompetitionTradingPair,
    interval_start: datetime,
    interval_end: datetime,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> tuple[str, int | None]:
    """Fetch and upsert a single interval. Returns
    (outcome, max_trade_id_seen_or_None). A fetch
    failure marks the interval incomplete with null
    volumes; a page-guard hit does the same."""
    configuration = _config_for(db, competition.id, pair_row.pair)
    try:
        trades, page_guard_hit = await _fetch_interval_trades(
            client, pair_row.pair, interval_start, interval_end, max_pages
        )
    except (BinanceAPIError, Exception) as exc:  # noqa: BLE001 - one interval failure is recorded
        logger.warning(
            "Volume fetch failed for competition %s pair %s interval %s: %s",
            competition.id,
            pair_row.pair,
            interval_start,
            exc,
        )
        bucket = {"public_base_volume": None, "public_quote_volume": None, "trade_count": 0}
        outcome = upsert_interval(
            db,
            competition,
            pair_row,
            interval_start,
            interval_end,
            bucket,
            configuration,
            data_status="incomplete",
        )
        return outcome, None
    max_trade_id = None
    for trade in trades:
        trade_id = trade.get("trade_id", trade.get("id"))
        if trade_id is not None:
            max_trade_id = trade_id if max_trade_id is None else max(max_trade_id, trade_id)
    if page_guard_hit:
        bucket = {"public_base_volume": None, "public_quote_volume": None, "trade_count": 0}
        outcome = upsert_interval(
            db,
            competition,
            pair_row,
            interval_start,
            interval_end,
            bucket,
            configuration,
            data_status="incomplete",
            page_guard_hit=True,
        )
        return outcome, max_trade_id
    bucket = bucket_trades(
        trades,
        interval_start,
        interval_end,
        as_utc(competition.start_time),
        as_utc(competition.end_time),
    )
    partial = is_partial_interval(
        interval_start, interval_end, as_utc(competition.start_time), as_utc(competition.end_time)
    )
    outcome = upsert_interval(
        db,
        competition,
        pair_row,
        interval_start,
        interval_end,
        bucket,
        configuration,
        data_status="partial" if partial else "complete",
    )
    return outcome, max_trade_id


async def collect_one_competition(
    db: Session,
    client,
    competition: Competition,
    now: datetime,
    *,
    max_intervals: int = DEFAULT_MAX_INTERVALS,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict:
    """Collect missed completed intervals for one
    competition. Returns per-competition counts; the
    caller writes the collection run row."""
    now = as_utc(now)
    pair_rows = _pair_rows(db, competition.id)
    counts = {"found": 0, "created": 0, "updated": 0, "skipped": 0, "completed": 0}
    errors: list[str] = []
    if not pair_rows:
        return {**counts, "errors": ["No trading pairs recorded; no intervals collected."]}
    comp_start = as_utc(competition.start_time)
    comp_end = as_utc(competition.end_time)
    window_end = min(now, comp_end) if comp_end is not None else now
    for pair_row in pair_rows:
        configuration = _config_for(db, competition.id, pair_row.pair)
        if configuration is not None and not configuration.tracking_enabled:
            continue
        try:
            checkpoint = _checkpoint_for(db, competition.id, pair_row.pair)
            if checkpoint is not None and checkpoint.last_interval_end is not None:
                window_start = as_utc(checkpoint.last_interval_end)
            elif comp_start is not None:
                window_start = comp_start
            else:
                window_start = now - LOOKBACK_NO_START
            if comp_start is not None and window_start < comp_start:
                window_start = comp_start
            missed = completed_intervals_between(window_start, window_end, now)
            counts["found"] += len(missed)
            if len(missed) > max_intervals:
                counts["skipped"] += len(missed) - max_intervals
                missed = missed[:max_intervals]
            prefix_end = None
            prefix_broken = False
            prefix_last_trade_id = None
            for interval_start, interval_end in missed:
                outcome, max_trade_id = await collect_interval(
                    db,
                    client,
                    competition,
                    pair_row,
                    interval_start,
                    interval_end,
                    max_pages=max_pages,
                )
                counts[outcome] += 1
                row = (
                    db.query(CompetitionVolumeInterval)
                    .filter_by(
                        competition_id=competition.id,
                        trading_pair=pair_row.pair,
                        interval_start=as_utc(interval_start),
                    )
                    .first()
                )
                if row is not None and row.data_status == "incomplete":
                    errors.append(
                        f"{pair_row.pair}: interval starting {interval_start.isoformat()} "
                        "incomplete (trade fetch failed or page guard hit)"
                    )
                if row is not None and row.data_status in ("complete", "partial"):
                    counts["completed"] += 1
                if row is not None and row.data_status in ("complete", "partial"):
                    if not prefix_broken:
                        prefix_end = as_utc(interval_end)
                        if max_trade_id is not None:
                            prefix_last_trade_id = max_trade_id
                else:
                    prefix_broken = True
            if prefix_end is not None:
                if checkpoint is None:
                    checkpoint = CompetitionVolumeCheckpoint(
                        competition_id=competition.id,
                        trading_pair=pair_row.pair,
                        last_interval_end=prefix_end,
                        last_trade_id=prefix_last_trade_id,
                    )
                    db.add(checkpoint)
                else:
                    checkpoint.last_interval_end = prefix_end
                    if prefix_last_trade_id is not None:
                        checkpoint.last_trade_id = prefix_last_trade_id
                db.commit()
        except Exception as exc:  # noqa: BLE001 - one pair must not stop other pairs
            # Roll back first (Phase 9 audit): after a DB
            # error SQLAlchemy requires rollback before
            # the session can be used again, otherwise the
            # next pair's checkpoint commit fails with
            # PendingRollbackError and the run is lost.
            db.rollback()
            logger.warning(
                "Volume collection failed for competition %s pair %s: %s",
                competition.id,
                pair_row.pair,
                exc,
            )
            errors.append(f"{pair_row.pair}: {type(exc).__name__}: {exc}")
    return {**counts, "errors": errors}


async def collect_competition_volumes(
    db: Session,
    client,
    now: datetime,
    competitions: list[Competition] | None = None,
    *,
    max_intervals: int | None = None,
    max_pages: int | None = None,
) -> dict:
    """Collect volumes for ACTIVE/UPCOMING competitions
    (or the explicit list given, e.g. a manual single
    collect). Writes one CompetitionVolumeCollectionRun
    per competition. Returns aggregate counts."""
    if max_intervals is None:
        max_intervals = settings.volume_backfill_max_intervals_per_pair
    if max_pages is None:
        max_pages = settings.volume_max_pages_per_interval
    if competitions is None:
        competitions = (
            db.query(Competition)
            .filter(Competition.status.in_(["ACTIVE", "UPCOMING"]))
            .order_by(Competition.id.asc())
            .all()
        )
    total = {
        "competitions": len(competitions),
        "intervals_found": 0,
        "intervals_created": 0,
        "intervals_updated": 0,
        "intervals_skipped": 0,
        "intervals_completed": 0,
        "errors": 0,
        "error_messages": [],
    }
    for competition in competitions:
        run = CompetitionVolumeCollectionRun(
            competition_id=competition.id, status="running", started=_now_utc()
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
            summary = await collect_one_competition(
                db,
                client,
                competition,
                now,
                max_intervals=max_intervals,
                max_pages=max_pages,
            )
        except Exception as exc:  # noqa: BLE001 - the run row must still be closed
            db.rollback()
            run.status = "failed"
            run.error_message = f"{type(exc).__name__}: {exc}"
            run.completed = _now_utc()
            db.commit()
            total["errors"] += 1
            continue
        run.intervals_found = summary["found"]
        run.intervals_created = summary["created"]
        run.intervals_updated = summary["updated"]
        run.intervals_skipped = summary["skipped"]
        run.status = "completed_with_errors" if summary["errors"] else "completed"
        run.error_message = "; ".join(summary["errors"]) if summary["errors"] else None
        run.completed = _now_utc()
        db.commit()
        total["intervals_found"] += summary["found"]
        total["intervals_created"] += summary["created"]
        total["intervals_updated"] += summary["updated"]
        total["intervals_skipped"] += summary["skipped"]
        total["intervals_completed"] += summary["completed"]
        total["errors"] += len(summary["errors"])
        total["error_messages"].extend(summary["errors"])
    return total
