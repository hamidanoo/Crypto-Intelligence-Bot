"""30-minute UTC interval arithmetic for volume tracking.

Intervals are half-open [start, end) aligned to UTC
00:00-00:30, 00:30-01:00, and so on. Only intervals
whose end is at or before ``now`` are "completed" and
eligible for collection or reporting; an interval
still in progress is never published. APScheduler
interval triggers are not guaranteed to fire exactly
on :00/:30 wall-clock boundaries, which is safe
precisely because only completed intervals are
processed: a late trigger simply collects the same
completed intervals, idempotently.
"""

from datetime import datetime, timedelta, timezone

INTERVAL_MINUTES = 30


def as_utc(value: datetime | None) -> datetime | None:
    """Normalise a datetime to aware UTC. SQLite returns
    naive datetimes; treating them as UTC (which is how
    they were stored) keeps comparisons correct."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def interval_bounds_for(moment: datetime) -> tuple[datetime, datetime]:
    """Return the [start, end) 30-minute interval
    containing ``moment``. ``moment`` itself may be
    inside the interval; the returned interval is the
    completed-or-current interval containing it, so
    callers must still check end <= now before
    treating it as completed."""
    moment = as_utc(moment)
    start = moment.replace(
        minute=(moment.minute // INTERVAL_MINUTES) * INTERVAL_MINUTES, second=0, microsecond=0
    )
    return start, start + timedelta(minutes=INTERVAL_MINUTES)


def completed_intervals_between(
    start: datetime, end: datetime, now: datetime
) -> list[tuple[datetime, datetime]]:
    """All 30-minute intervals overlapping [start, end)
    whose end is at or before ``now``. Intervals are
    generated from the interval containing ``start``,
    so a window starting mid-interval still yields
    that (partial) interval. An empty list means there
    is nothing completed to collect yet."""
    start = as_utc(start)
    end = as_utc(end)
    now = as_utc(now)
    if end <= start:
        return []
    first_start, _ = interval_bounds_for(start)
    intervals: list[tuple[datetime, datetime]] = []
    cursor = first_start
    while cursor < end:
        interval_end = cursor + timedelta(minutes=INTERVAL_MINUTES)
        if interval_end <= now:
            intervals.append((cursor, interval_end))
        cursor = interval_end
    return intervals


def is_partial_interval(
    interval_start: datetime,
    interval_end: datetime,
    competition_start: datetime | None,
    competition_end: datetime | None,
) -> bool:
    """True when the competition starts or ends inside
    this interval, so only trades inside the
    competition window count for it. A competition
    with no dates never makes an interval partial."""
    interval_start = as_utc(interval_start)
    interval_end = as_utc(interval_end)
    comp_start = as_utc(competition_start)
    comp_end = as_utc(competition_end)
    if comp_start is not None and interval_start < comp_start < interval_end:
        return True
    if comp_end is not None and interval_start < comp_end < interval_end:
        return True
    return False
