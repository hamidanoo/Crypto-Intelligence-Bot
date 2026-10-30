"""Trade bucketing and volume arithmetic for Phase 6.

All financial math uses Decimal, converted from the
trade strings via str(), never from floats. Missing
data is never zero: the two cases are kept apart
explicitly by callers — a failed fetch produces an
incomplete interval with null volumes, while a
successful fetch that genuinely returned no trades
in the window produces Decimal 0 with status
complete. This module only sums what it is given;
that distinction lives in collection.py.
"""

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CompetitionVolumeInterval
from app.volume.intervals import as_utc

logger = logging.getLogger(__name__)

METHOD_PUBLIC = "binance_aggtrades_public_trade_data"
METHOD_PUBLIC_VERIFIED_MULTIPLIER = "binance_aggtrades_x_verified_multiplier"


def _trade_time(trade: dict) -> datetime | None:
    timestamp = trade.get("timestamp")
    if isinstance(timestamp, datetime):
        return as_utc(timestamp)
    if isinstance(timestamp, (int, float)):
        from datetime import timezone

        return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    return None


def _trade_id(trade: dict):
    for key in ("trade_id", "id", "a"):
        if trade.get(key) is not None:
            return trade[key]
    return None


def _dec(value) -> Decimal:
    return Decimal(str(value))


def bucket_trades(
    trades: list[dict],
    interval_start: datetime,
    interval_end: datetime,
    competition_start: datetime | None = None,
    competition_end: datetime | None = None,
) -> dict:
    """Bucket trades into one interval.

    Dedupes by trade id within this fetch, keeps only
    trades in [interval_start, interval_end), and,
    when competition dates exist, only trades in
    [competition_start, competition_end) — trades
    outside are excluded, never counted. Sums qty as
    public base volume and quoteQty as public quote
    volume, both as Decimal.
    """
    interval_start = as_utc(interval_start)
    interval_end = as_utc(interval_end)
    comp_start = as_utc(competition_start)
    comp_end = as_utc(competition_end)
    seen: set = set()
    base = Decimal("0")
    quote = Decimal("0")
    counted = 0
    for trade in trades or []:
        trade_id = _trade_id(trade)
        if trade_id is not None:
            if trade_id in seen:
                continue
            seen.add(trade_id)
        moment = _trade_time(trade)
        if moment is None:
            continue
        if not (interval_start <= moment < interval_end):
            continue
        if comp_start is not None and moment < comp_start:
            continue
        if comp_end is not None and moment >= comp_end:
            continue
        qty = trade.get("qty") or trade.get("q")
        quote_qty = trade.get("quote_qty") or trade.get("quoteQty") or trade.get("Q")
        if qty is None or quote_qty is None:
            continue
        base += _dec(qty)
        quote += _dec(quote_qty)
        counted += 1
    return {
        "public_base_volume": base,
        "public_quote_volume": quote,
        "trade_count": counted,
    }


def estimate_eligible_volume(public_base_volume, configuration) -> tuple[Decimal | None, str]:
    """Estimated eligible volume, or (None, method)
    when no verified multiplier exists. A multiplier
    is applied ONLY when the configuration exists,
    multiplier_verified is True, and a multiplier is
    set; an unverified multiplier, a missing
    configuration, or a null public volume all yield
    null, never zero and never an invented rule. The
    method string names exactly how the estimate was
    (or was not) produced, so every estimate carries
    its method and source."""
    if public_base_volume is None:
        return None, METHOD_PUBLIC
    if (
        configuration is not None
        and configuration.multiplier_verified
        and configuration.multiplier is not None
    ):
        return _dec(public_base_volume) * _dec(configuration.multiplier), (
            configuration.calculation_method or METHOD_PUBLIC_VERIFIED_MULTIPLIER
        )
    return None, METHOD_PUBLIC


def cumulative_volume(db: Session, competition_id: int, trading_pair: str) -> dict:
    """Cumulative volume computed ONLY by summing
    stored intervals for this competition+pair, so it
    is reproducible from interval data. Incomplete
    intervals have null volumes and contribute
    nothing; complete and partial-boundary intervals
    contribute their stored volumes. Returns Decimals
    (0 when no stored interval has volumes) and the
    count of contributing intervals."""
    rows = (
        db.query(CompetitionVolumeInterval)
        .filter_by(competition_id=competition_id, trading_pair=trading_pair)
        .filter(CompetitionVolumeInterval.data_status != "incomplete")
        .all()
    )
    base = sum(
        (row.public_base_volume for row in rows if row.public_base_volume is not None), Decimal("0")
    )
    quote = sum(
        (row.public_quote_volume for row in rows if row.public_quote_volume is not None),
        Decimal("0"),
    )
    estimated = sum(
        (
            row.estimated_eligible_volume
            for row in rows
            if row.estimated_eligible_volume is not None
        ),
        Decimal("0"),
    )
    has_estimated = any(row.estimated_eligible_volume is not None for row in rows)
    return {
        "public_base_volume": base,
        "public_quote_volume": quote,
        "estimated_eligible_volume": estimated if has_estimated else None,
        "interval_count": len(rows),
    }


def db_sum_check(db: Session, competition_id: int, trading_pair: str) -> Decimal:
    """Independent DB-side SUM used by tests to verify
    cumulative_volume equals the sum of interval rows."""
    total = (
        db.query(func.sum(CompetitionVolumeInterval.public_base_volume))
        .filter_by(competition_id=competition_id, trading_pair=trading_pair)
        .filter(CompetitionVolumeInterval.data_status != "incomplete")
        .scalar()
    )
    return total if total is not None else Decimal("0")
