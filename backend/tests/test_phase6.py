"""Phase 6 tests: competition volume tracker.

Mock tests only for the core suite: every test uses
an in-memory database and a fake Binance client or a
mocked httpx transport. Nothing here depends on live
Binance, and nothing here claims a live integration.
Live aggTrades results are recorded separately in
docs/VOLUME_TRACKER.md, not in this file.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.binance.client import BinanceAPIError, BinanceClient
from app.database import Base, get_db
from app.main import app
from app.models import (
    Announcement,
    Competition,
    CompetitionPairConfiguration,
    CompetitionTradingPair,
    CompetitionVolumeCheckpoint,
    CompetitionVolumeCollectionRun,
    CompetitionVolumeInterval,
    CompetitionVolumeReport,
)
from app.rate_limit import reset_rate_limits
from app.scheduler import register_jobs, scheduler
from app.volume.aggregation import bucket_trades, cumulative_volume, db_sum_check
from app.volume.collection import (
    collect_competition_volumes,
    collect_interval,
    collect_one_competition,
)
from app.volume.intervals import (
    completed_intervals_between,
    interval_bounds_for,
    is_partial_interval,
)
from app.volume.reporting import format_volume_message, send_volume_reports

UTC = timezone.utc
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed_competition(
    db, name="Test Competition", status="ACTIVE", start=None, end=None, pairs=("BTCUSDT",)
):
    from app.announcements.service import ensure_default_source

    source = ensure_default_source(db)
    announcement = Announcement(
        source_id=source.id,
        source_name=source.name,
        external_id=f"ext-{name}",
        code=f"code-{name}",
        title=name,
        slug="seed",
        canonical_url=f"https://www.binance.com/en/support/announcement/seed-{name}",
        category="TRADING_COMPETITION",
        category_confidence="high",
        published_at=datetime(2026, 11, 1, tzinfo=UTC),
        collected_at=datetime(2026, 11, 1, tzinfo=UTC),
        content_hash=f"hash-{name}",
        verification_status="official_website",
        metadata_json={},
        notification_status="pending",
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    competition = Competition(
        announcement_id=announcement.id,
        competition_name=name,
        competition_type="SPOT",
        official_url=announcement.canonical_url,
        start_time=start,
        end_time=end,
        status=status,
        eligible_trading_pairs=list(pairs),
    )
    db.add(competition)
    db.commit()
    db.refresh(competition)
    for pair in pairs:
        quote = "USDT" if pair.endswith("USDT") else None
        base = pair[: -len(quote)] if quote else None
        db.add(
            CompetitionTradingPair(
                competition_id=competition.id, pair=pair, base_asset=base, quote_asset=quote
            )
        )
    db.commit()
    return competition


def _trade(trade_id, moment, qty="1", quote="100"):
    return {
        "trade_id": trade_id,
        "price": "100",
        "qty": str(qty),
        "quote_qty": str(quote),
        "timestamp": moment,
        "is_buyer_maker": False,
        "source": "binance_spot_aggtrades",
    }


class FakeClient:
    """Simulates Binance aggTrades paging: filters by
    [start, end) and from_id, slices by limit, and can
    fail for selected pairs."""

    def __init__(self, trades_by_pair=None, fail_pairs=(), *args, **kwargs):
        self.trades_by_pair = trades_by_pair or {}
        self.fail_pairs = set(fail_pairs)
        self.calls = []

    async def get_agg_trades(
        self, symbol, *, from_id=None, start_time=None, end_time=None, limit=1000
    ):
        self.calls.append((symbol, from_id))
        if symbol in self.fail_pairs:
            raise BinanceAPIError("upstream boom", status=500)
        rows = []
        for trade in self.trades_by_pair.get(symbol, []):
            moment = trade["timestamp"]
            if start_time is not None and moment < start_time:
                continue
            if end_time is not None and moment >= end_time:
                continue
            if from_id is not None and trade["trade_id"] < from_id:
                continue
            rows.append(trade)
        rows.sort(key=lambda t: t["trade_id"])
        return rows[:limit]


def _client_with_db(db):
    def _override_db():
        yield db

    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    reset_rate_limits()
    return TestClient(app, raise_server_exceptions=False), old


def _restore(old):
    if old is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = old
    reset_rate_limits()


def _intervals(db, comp_id, pair="BTCUSDT"):
    return (
        db.query(CompetitionVolumeInterval)
        .filter_by(competition_id=comp_id, trading_pair=pair)
        .order_by(CompetitionVolumeInterval.interval_start.asc())
        .all()
    )


# Intervals -----------------------------------------------------------------


def test_interval_bounds_midnight_and_half_hour_edges():
    assert interval_bounds_for(datetime(2026, 11, 5, 0, 0, tzinfo=UTC)) == (
        datetime(2026, 11, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 0, 30, tzinfo=UTC),
    )
    assert interval_bounds_for(datetime(2026, 11, 5, 0, 29, 59, tzinfo=UTC))[0] == datetime(
        2026, 11, 5, 0, 0, tzinfo=UTC
    )
    assert interval_bounds_for(datetime(2026, 11, 5, 0, 30, tzinfo=UTC)) == (
        datetime(2026, 11, 5, 0, 30, tzinfo=UTC),
        datetime(2026, 11, 5, 1, 0, tzinfo=UTC),
    )
    assert interval_bounds_for(datetime(2026, 11, 5, 23, 45, tzinfo=UTC)) == (
        datetime(2026, 11, 5, 23, 30, tzinfo=UTC),
        datetime(2026, 11, 6, 0, 0, tzinfo=UTC),
    )


def test_completed_intervals_only_end_at_or_before_now():
    intervals = completed_intervals_between(
        datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 12, 0, tzinfo=UTC),
        NOW,
    )
    assert len(intervals) == 4
    assert intervals[-1][1] == NOW
    # The in-progress interval is never returned.
    intervals = completed_intervals_between(
        datetime(2026, 11, 5, 11, 30, tzinfo=UTC),
        datetime(2026, 11, 5, 12, 30, tzinfo=UTC),
        NOW,
    )
    assert intervals == [(datetime(2026, 11, 5, 11, 30, tzinfo=UTC), NOW)]
    assert completed_intervals_between(NOW, NOW, NOW) == []


def test_naive_datetimes_are_treated_as_utc():
    start, end = interval_bounds_for(datetime(2026, 11, 5, 10, 15))
    assert start.tzinfo is not None
    assert start == datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 5, 10, 30, tzinfo=UTC)


def test_partial_interval_detection():
    assert is_partial_interval(
        datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 30, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 15, tzinfo=UTC),
        None,
    )
    assert is_partial_interval(
        datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 30, tzinfo=UTC),
        None,
        datetime(2026, 11, 5, 10, 15, tzinfo=UTC),
    )
    assert not is_partial_interval(
        datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 30, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
    )
    assert not is_partial_interval(
        datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 30, tzinfo=UTC),
        None,
        None,
    )


# Bucketing -----------------------------------------------------------------


def test_bucket_dedupes_filters_and_uses_decimal():
    start = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    end = datetime(2026, 11, 5, 10, 30, tzinfo=UTC)
    trades = [
        _trade(1, datetime(2026, 11, 5, 10, 5, tzinfo=UTC), qty="0.1", quote="10"),
        _trade(1, datetime(2026, 11, 5, 10, 5, tzinfo=UTC), qty="0.1", quote="10"),
        _trade(2, datetime(2026, 11, 5, 10, 10, tzinfo=UTC), qty="0.2", quote="20"),
        _trade(3, datetime(2026, 11, 5, 10, 30, tzinfo=UTC), qty="5", quote="500"),
        _trade(4, datetime(2026, 11, 5, 9, 59, tzinfo=UTC), qty="5", quote="500"),
    ]
    result = bucket_trades(trades, start, end)
    assert result["public_base_volume"] == Decimal("0.3")
    assert isinstance(result["public_base_volume"], Decimal)
    assert result["public_quote_volume"] == Decimal("30")
    assert result["trade_count"] == 2


def test_bucket_filters_to_competition_window():
    start = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    end = datetime(2026, 11, 5, 10, 30, tzinfo=UTC)
    trades = [
        _trade(1, datetime(2026, 11, 5, 10, 5, tzinfo=UTC), qty="1", quote="100"),
        _trade(2, datetime(2026, 11, 5, 10, 20, tzinfo=UTC), qty="2", quote="200"),
    ]
    result = bucket_trades(
        trades,
        start,
        end,
        datetime(2026, 11, 5, 10, 15, tzinfo=UTC),
        datetime(2026, 11, 5, 10, 25, tzinfo=UTC),
    )
    assert result["public_base_volume"] == Decimal("2")
    assert result["trade_count"] == 1


# Collection ----------------------------------------------------------------


def _collect(db, client, comp, now=NOW, **kwargs):
    return asyncio.run(collect_one_competition(db, client, comp, now, **kwargs))


def test_collection_creates_intervals_and_cumulative_matches_db_sum():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    trades = [
        _trade(1, datetime(2026, 11, 5, 10, 5, tzinfo=UTC), qty="1.5", quote="150"),
        _trade(2, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="2", quote="200"),
    ]
    summary = _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    rows = _intervals(db, comp.id)
    assert summary["created"] == 4  # 10:00-12:00, four completed intervals
    assert len(rows) == 4
    assert rows[0].public_base_volume == Decimal("1.5")
    assert rows[0].public_quote_volume == Decimal("150")
    assert rows[0].data_status == "complete"
    assert rows[0].official_eligible_volume is None
    assert rows[0].estimated_eligible_volume is None
    assert rows[2].public_base_volume == Decimal("2")
    cum = cumulative_volume(db, comp.id, "BTCUSDT")
    assert cum["public_base_volume"] == Decimal("3.5")
    assert cum["public_quote_volume"] == Decimal("350")
    assert cum["public_base_volume"] == db_sum_check(db, comp.id, "BTCUSDT")
    assert cum["interval_count"] == 4


def test_multiple_pairs_and_multiple_competitions():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp1 = _seed_competition(
        db,
        "Comp One",
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        pairs=("BTCUSDT", "ETHUSDT"),
    )
    comp2 = _seed_competition(
        db,
        "Comp Two",
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        pairs=("BTCUSDT",),
    )
    trades = {
        "BTCUSDT": [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100")],
        "ETHUSDT": [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="3", quote="300")],
    }
    summary = asyncio.run(collect_competition_volumes(db, FakeClient(trades), NOW))
    assert summary["competitions"] == 2
    assert len(_intervals(db, comp1.id, "BTCUSDT")) == 2
    assert len(_intervals(db, comp1.id, "ETHUSDT")) == 2
    assert len(_intervals(db, comp2.id, "BTCUSDT")) == 2
    assert cumulative_volume(db, comp1.id, "ETHUSDT")["public_base_volume"] == Decimal("3")
    assert db.query(CompetitionVolumeCollectionRun).count() == 2


def test_recollection_is_idempotent_and_duplicate_row_blocked():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    trades = [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100")]
    client = FakeClient({"BTCUSDT": trades})
    first = _collect(db, client, comp)
    assert first["created"] == 2
    # Reset the checkpoint so the same intervals are re-fetched.
    db.query(CompetitionVolumeCheckpoint).delete()
    db.commit()
    second = _collect(db, client, comp)
    assert second["created"] == 0
    assert second["skipped"] == 2
    assert len(_intervals(db, comp.id)) == 2
    assert _intervals(db, comp.id)[0].public_base_volume == Decimal("1")
    duplicate = CompetitionVolumeInterval(
        competition_id=comp.id,
        trading_pair="BTCUSDT",
        interval_start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        interval_end=datetime(2026, 11, 5, 11, 30, tzinfo=UTC),
        data_status="complete",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_late_trades_recalculate_without_duplication():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    pair_row = db.query(CompetitionTradingPair).filter_by(competition_id=comp.id).first()
    start = datetime(2026, 11, 5, 11, 0, tzinfo=UTC)
    end = datetime(2026, 11, 5, 11, 30, tzinfo=UTC)
    client_v1 = FakeClient(
        {"BTCUSDT": [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100")]}
    )
    outcome, _ = asyncio.run(collect_interval(db, client_v1, comp, pair_row, start, end))
    assert outcome == "created"
    client_v2 = FakeClient(
        {
            "BTCUSDT": [
                _trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100"),
                _trade(2, datetime(2026, 11, 5, 11, 10, tzinfo=UTC), qty="4", quote="400"),
            ]
        }
    )
    outcome, _ = asyncio.run(collect_interval(db, client_v2, comp, pair_row, start, end))
    assert outcome == "updated"
    rows = _intervals(db, comp.id)
    assert len(rows) == 1
    assert rows[0].public_base_volume == Decimal("5")
    assert rows[0].recalculated is True


def test_partial_boundary_interval_counts_only_inside_window():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 15, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    trades = [
        _trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="9", quote="900"),
        _trade(2, datetime(2026, 11, 5, 11, 20, tzinfo=UTC), qty="2", quote="200"),
    ]
    _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    row = _intervals(db, comp.id)[0]
    assert row.data_status == "partial"
    assert row.public_base_volume == Decimal("2")
    assert row.public_quote_volume == Decimal("200")


def test_checkpoint_backfill_and_incomplete_recovery():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 8, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    trades = [_trade(1, datetime(2026, 11, 5, 10, 5, tzinfo=UTC), qty="1", quote="100")]
    # First run fails upstream: intervals are incomplete with null volumes, not zero.
    failing = _collect(db, FakeClient({"BTCUSDT": trades}, fail_pairs={"BTCUSDT"}), comp)
    rows = _intervals(db, comp.id)
    assert failing["created"] == 8  # 08:00-12:00
    assert all(r.data_status == "incomplete" for r in rows)
    assert all(r.public_base_volume is None for r in rows)
    assert db.query(CompetitionVolumeCheckpoint).count() == 0  # no advance past failure
    # Recovery run with a working client completes them.
    good = _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    rows = _intervals(db, comp.id)
    assert all(r.data_status == "complete" for r in rows)
    assert good["updated"] == 8
    checkpoint = db.query(CompetitionVolumeCheckpoint).first()
    assert checkpoint is not None
    # Checkpoint end is 12:00 UTC (stored naive by SQLite, read as UTC-equivalent).
    assert checkpoint.last_interval_end.replace(tzinfo=UTC) == NOW
    # A later run finds nothing new.
    third = _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    assert third["found"] == 0


def test_empty_window_is_zero_complete_not_incomplete():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    _collect(db, FakeClient({"BTCUSDT": []}), comp)
    rows = _intervals(db, comp.id)
    assert len(rows) == 2
    assert all(r.data_status == "complete" for r in rows)
    assert all(r.public_base_volume == Decimal("0") for r in rows)
    assert all(r.public_quote_volume == Decimal("0") for r in rows)


def test_partial_pair_failure_does_not_stop_other_pairs():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        pairs=("BTCUSDT", "ETHUSDT"),
    )
    trades = {
        "ETHUSDT": [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="3", quote="300")]
    }
    summary = _collect(db, FakeClient(trades, fail_pairs={"BTCUSDT"}), comp)
    assert len(_intervals(db, comp.id, "ETHUSDT")) == 2
    assert _intervals(db, comp.id, "ETHUSDT")[0].public_base_volume == Decimal("3")
    assert all(r.data_status == "incomplete" for r in _intervals(db, comp.id, "BTCUSDT"))
    assert summary["errors"]


def test_backfill_cap_is_enforced():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    summary = _collect(db, FakeClient({"BTCUSDT": []}), comp)
    assert summary["found"] == 96  # 48 hours of 30-minute intervals
    assert summary["created"] == 48
    assert summary["skipped"] == 48


def test_backfill_pagination_uses_from_id():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    base = datetime(2026, 11, 5, 11, 0, tzinfo=UTC)
    trades = [
        _trade(i, base + timedelta(seconds=i), qty="0.001", quote="0.1") for i in range(1, 2501)
    ]
    # All 2500 trades fall in the 11:00-11:30 interval (seconds 1..2500 < 1800? No:
    # seconds up to 2500 exceed 1800, so restrict to the interval by construction below).
    trades = [t for t in trades if t["timestamp"] < datetime(2026, 11, 5, 11, 30, tzinfo=UTC)]
    client = FakeClient({"BTCUSDT": trades})
    _collect(db, client, comp)
    row = _intervals(db, comp.id)[0]
    assert row.public_base_volume == Decimal("0.001") * len(trades)
    assert row.public_quote_volume == Decimal("0.1") * len(trades)
    from_ids = [call[1] for call in client.calls if call[0] == "BTCUSDT"]
    assert from_ids[0] is None
    assert 1001 in from_ids  # second page starts after trade 1000


def test_aggtrades_paging_never_combines_from_id_with_time_window():
    """Binance rejects fromId together with
    startTime/endTime (verified live 2026-10-30), so
    collection must page by fromId alone after the
    first windowed page. A strict client that raises
    on the forbidden combination must still collect
    a 1500-trade interval completely."""
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    base = datetime(2026, 11, 5, 11, 0, tzinfo=UTC)
    all_trades = [
        _trade(i, base + timedelta(seconds=i), qty="0.001", quote="0.1") for i in range(1, 1501)
    ]

    class _StrictClient:
        def __init__(self):
            self.calls = []

        async def get_agg_trades(
            self, symbol, *, from_id=None, start_time=None, end_time=None, limit=1000
        ):
            self.calls.append((from_id, start_time, end_time))
            if from_id is not None and (start_time is not None or end_time is not None):
                raise BinanceAPIError("Combination of optional parameters invalid.", status=400)
            rows = [t for t in all_trades if from_id is None or t["trade_id"] >= from_id]
            if start_time is not None:
                rows = [t for t in rows if t["timestamp"] >= start_time]
            if end_time is not None:
                rows = [t for t in rows if t["timestamp"] < end_time]
            return rows[:limit]

    client = _StrictClient()
    _collect(db, client, comp)
    row = _intervals(db, comp.id)[0]
    assert row.data_status == "complete"
    assert row.public_base_volume == Decimal("0.001") * 1500
    assert any(call[0] is None for call in client.calls)  # first page windowed
    assert any(call[0] is not None and call[1] is None for call in client.calls)


def test_page_guard_marks_interval_incomplete():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    pair_row = db.query(CompetitionTradingPair).filter_by(competition_id=comp.id).first()

    class _EndlessClient:
        async def get_agg_trades(
            self, symbol, *, from_id=None, start_time=None, end_time=None, limit=1000
        ):
            start_id = from_id or 1
            return [
                _trade(start_id + i, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100")
                for i in range(1000)
            ]

    outcome, _ = asyncio.run(
        collect_interval(
            db,
            _EndlessClient(),
            comp,
            pair_row,
            datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
            datetime(2026, 11, 5, 11, 30, tzinfo=UTC),
            max_pages=2,
        )
    )
    row = _intervals(db, comp.id)[0]
    assert row.data_status == "incomplete"
    assert row.public_base_volume is None


def test_no_start_date_uses_last_24h_and_no_pairs_records_run():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(db, start=None, end=None)
    summary = _collect(db, FakeClient({"BTCUSDT": []}), comp)
    assert summary["found"] == 48  # last 24 hours, capped at 48
    comp2 = _seed_competition(db, "No Pairs", pairs=())
    asyncio.run(collect_competition_volumes(db, FakeClient({}), NOW, competitions=[comp2]))
    run = db.query(CompetitionVolumeCollectionRun).filter_by(competition_id=comp2.id).first()
    assert run is not None
    assert run.intervals_found == 0
    assert run.error_message is not None and "No trading pairs" in run.error_message


def test_tracking_disabled_pair_is_skipped():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        pairs=("BTCUSDT", "ETHUSDT"),
    )
    db.add(
        CompetitionPairConfiguration(
            competition_id=comp.id, trading_pair="ETHUSDT", tracking_enabled=False
        )
    )
    db.commit()
    _collect(db, FakeClient({"BTCUSDT": [], "ETHUSDT": []}), comp)
    assert len(_intervals(db, comp.id, "BTCUSDT")) == 2
    assert len(_intervals(db, comp.id, "ETHUSDT")) == 0


# Multiplier / estimates -----------------------------------------------------


def test_multiplier_applied_only_when_verified():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    db.add(
        CompetitionPairConfiguration(
            competition_id=comp.id,
            trading_pair="BTCUSDT",
            multiplier=Decimal("2"),
            multiplier_verified=False,
        )
    )
    db.commit()
    trades = [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="10", quote="1000")]
    _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    row = _intervals(db, comp.id)[0]
    assert row.estimated_eligible_volume is None  # unverified multiplier never applied
    assert row.public_base_volume == Decimal("10")
    # Verify the multiplier, reset, and re-collect: estimate appears.
    config = db.query(CompetitionPairConfiguration).first()
    config.multiplier_verified = True
    db.commit()
    db.query(CompetitionVolumeCheckpoint).delete()
    db.commit()
    _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    row = _intervals(db, comp.id)[0]
    assert row.estimated_eligible_volume == Decimal("20")
    assert row.official_eligible_volume is None  # always null in Phase 6


def test_quote_asset_handling_and_missing_rules_yield_null_estimate():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    trades = [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="50000")]
    _collect(db, FakeClient({"BTCUSDT": trades}), comp)
    row = _intervals(db, comp.id)[0]
    assert row.base_asset == "BTC"
    assert row.quote_asset == "USDT"
    assert row.public_quote_volume == Decimal("50000")
    assert row.estimated_eligible_volume is None


# Binance client -------------------------------------------------------------


def test_agg_trades_parsing_and_429_retry_with_mock_transport():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/aggTrades"
        calls["count"] += 1
        if calls["count"] <= 2:
            return httpx.Response(429, json={"code": -1003, "msg": "Too many requests"})
        return httpx.Response(
            200,
            json=[
                {"a": 7, "p": "100.5", "q": "2", "Q": "201", "T": 1793876700000, "m": False},
                # aggTrades carries no quote-quantity field
                # in the live response, so this trade
                # exercises the price x qty derivation.
                {"a": 8, "p": "100.5", "q": "1", "T": 1793876760000, "m": False},
            ],
        )

    async def run():
        client = BinanceClient(
            "https://data-api.binance.vision",
            "https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        return await client.get_agg_trades(
            "BTCUSDT",
            start_time=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
            end_time=datetime(2026, 11, 5, 11, 30, tzinfo=UTC),
        )

    trades = asyncio.run(run())
    assert calls["count"] == 3
    assert len(trades) == 2
    assert trades[0]["trade_id"] == 7
    assert trades[0]["qty"] == "2"
    assert trades[0]["quote_qty"] == "201"
    assert trades[0]["timestamp"] == datetime(2026, 11, 5, 11, 5, tzinfo=UTC)
    assert trades[1]["quote_qty"] == "100.5"


# Scheduler ------------------------------------------------------------------


def test_scheduler_registration_is_idempotent_and_single_instance():
    register_jobs()
    job = scheduler.get_job("competition_volume_tracking")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    before = len(scheduler.get_jobs())
    register_jobs()
    assert len(scheduler.get_jobs()) == before
    assert scheduler.get_job("competition_volume_tracking").max_instances == 1


# Telegram -------------------------------------------------------------------


class _MockBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id, text, parse_mode=None):
        if self.fail:
            raise RuntimeError("telegram rate limited")
        self.sent.append((chat_id, text))


def _seed_interval(db, comp, pair="BTCUSDT", status="complete"):
    _collect(
        db,
        FakeClient(
            {pair: [_trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100")]}
        ),
        comp,
    )
    rows = _intervals(db, comp.id, pair)
    assert rows
    return rows[0]


def test_volume_report_format_and_duplicate_prevention():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    interval = _seed_interval(db, comp)
    message = format_volume_message(comp, interval, cumulative_volume(db, comp.id, "BTCUSDT"))
    assert "Test Competition" in message
    assert "Trading Pair: BTCUSDT" in message
    assert "Public Market Volume" in message
    assert "Estimated Eligible Volume: Unavailable" in message
    assert "Official Eligible Volume: Unavailable" in message
    assert "Data Status: complete" in message
    assert "Binance public trade data (aggTrades)" in message
    assert "PKT" in message and "UTC" in message
    bot = _MockBot()
    first = asyncio.run(send_volume_reports(db, bot=bot))
    assert first["sent"] == 2  # two completed intervals (11:00, 11:30) both reported
    assert len(bot.sent) == 2
    assert db.query(CompetitionVolumeReport).count() == 2
    assert all(
        r.status == "sent" and r.sent_at is not None
        for r in db.query(CompetitionVolumeReport).all()
    )
    second = asyncio.run(send_volume_reports(db, bot=bot))
    assert second["sent"] == 0
    assert len(bot.sent) == 2  # nothing re-sent


def test_incomplete_interval_gets_no_report_and_failed_report_retries():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
    )
    _collect(db, FakeClient({"BTCUSDT": []}, fail_pairs={"BTCUSDT"}), comp)
    bot = _MockBot()
    result = asyncio.run(send_volume_reports(db, bot=bot))
    assert result["sent"] == 0
    assert db.query(CompetitionVolumeReport).count() == 0
    # Now a complete interval with a failing bot, then a retry with a good bot.
    db.query(CompetitionVolumeInterval).delete()
    db.query(CompetitionVolumeCheckpoint).delete()
    db.commit()
    _seed_interval(db, comp)
    failing_bot = _MockBot(fail=True)
    failed = asyncio.run(send_volume_reports(db, bot=failing_bot))
    assert failed["failed"] == 2
    assert db.query(CompetitionVolumeReport).count() == 2
    assert all(r.status == "failed" for r in db.query(CompetitionVolumeReport).all())
    good_bot = _MockBot()
    retried = asyncio.run(send_volume_reports(db, bot=good_bot))
    assert retried["sent"] == 2
    assert db.query(CompetitionVolumeReport).count() == 2  # updated in place, not duplicated
    assert all(r.status == "sent" for r in db.query(CompetitionVolumeReport).all())


# API ------------------------------------------------------------------------


def test_api_filters_pagination_summary_pairs_history_and_runs():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    comp = _seed_competition(
        db,
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        end=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        pairs=("BTCUSDT", "ETHUSDT"),
    )
    _collect(
        db,
        FakeClient(
            {
                "BTCUSDT": [
                    _trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="1", quote="100")
                ],
                "ETHUSDT": [
                    _trade(1, datetime(2026, 11, 5, 11, 5, tzinfo=UTC), qty="3", quote="300")
                ],
            }
        ),
        comp,
    )
    asyncio.run(collect_competition_volumes(db, FakeClient({}), NOW, competitions=[comp]))
    client, old = _client_with_db(db)
    try:
        response = client.get("/competition-volume?competition_id=%d" % comp.id)
        assert response.status_code == 200
        assert response.json()["total"] == 4
        response = client.get("/competition-volume?trading_pair=ETHUSDT")
        assert response.json()["total"] == 2
        response = client.get("/competition-volume?data_status=complete")
        assert response.json()["total"] == 4
        response = client.get("/competition-volume?data_status=incomplete")
        assert response.json()["total"] == 0
        response = client.get("/competition-volume?page=1&page_size=1")
        assert len(response.json()["items"]) == 1
        assert response.json()["items"][0]["public_base_volume"] is not None
        assert response.json()["items"][0]["official_eligible_volume"] is None
        assert client.get("/competition-volume?sort=invalid").status_code == 400
        detail = client.get(f"/competition-volume/{comp.id}")
        assert detail.status_code == 200
        assert detail.json()["total"] == 4
        history = client.get(f"/competition-volume/{comp.id}/history?trading_pair=BTCUSDT")
        assert history.json()["total"] == 2
        pairs = client.get(f"/competition-volume/{comp.id}/pairs")
        assert len(pairs.json()["pairs"]) == 2
        assert pairs.json()["pairs"][0]["latest_interval"] is not None
        summary = client.get(f"/competition-volume/{comp.id}/summary")
        body = summary.json()
        assert body["official_eligible_volume"] is None
        assert body["official_eligible_volume_display"] == "Unavailable"
        assert len(body["per_pair"]) == 2
        btc = [p for p in body["per_pair"] if p["trading_pair"] == "BTCUSDT"][0]
        assert btc["cumulative_public_base_volume"] == "1.00000000"
        assert btc["latest_interval"] is not None
        runs = client.get("/competition-volume/collection-runs?competition_id=%d" % comp.id)
        assert runs.json()["total"] >= 1
        assert client.get("/competition-volume/99999").status_code == 404
        assert client.get("/competition-volume/99999/summary").status_code == 404
    finally:
        _restore(old)


def test_api_collect_endpoints_with_mocked_client_and_502():
    from unittest.mock import patch

    engine = _engine()
    db = sessionmaker(bind=engine)()
    # The API collect endpoint uses the real current time,
    # so the competition window must already be completed
    # relative to it: start this morning, end this afternoon.
    today = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    comp = _seed_competition(
        db,
        start=today,
        end=today + timedelta(hours=6),
    )
    client, old = _client_with_db(db)
    try:
        trades = {"BTCUSDT": [_trade(1, today + timedelta(minutes=5), qty="1", quote="100")]}

        class _PatchedClient(FakeClient):
            def __init__(self, *args, **kwargs):
                super().__init__(trades)

        with patch("app.api.volume.BinanceClient", _PatchedClient):
            response = client.post(f"/competition-volume/{comp.id}/collect")
        assert response.status_code == 200
        assert response.json()["intervals_created"] >= 1
        assert (
            client.get(f"/competition-volume/{comp.id}/summary").json()["per_pair"][0][
                "cumulative_public_base_volume"
            ]
            == "1.00000000"
        )

        class _FailingClient:
            def __init__(self, *args, **kwargs):
                pass

            async def get_agg_trades(self, *args, **kwargs):
                raise BinanceAPIError("upstream boom", status=500)

        # Reset so the failing collect has intervals to attempt.
        db.query(CompetitionVolumeCheckpoint).delete()
        db.query(CompetitionVolumeInterval).delete()
        db.commit()
        with patch("app.api.volume.BinanceClient", _FailingClient):
            response = client.post(f"/competition-volume/{comp.id}/collect")
        assert response.status_code == 502
        assert client.post("/competition-volume/99999/collect").status_code == 404
    finally:
        _restore(old)


def test_api_database_failure_returns_503():
    class _FailingQuery:
        def filter(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection failed"))

        def filter_by(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection failed"))

        def count(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection failed"))

        def order_by(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection failed"))

    class _FailingDb:
        def query(self, *a, **k):
            return _FailingQuery()

    def _failing_db():
        yield _FailingDb()

    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _failing_db
    try:
        reset_rate_limits()
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/competition-volume").status_code == 503
    finally:
        if old is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old
        reset_rate_limits()
