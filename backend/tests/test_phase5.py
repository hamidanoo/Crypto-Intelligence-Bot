"""Phase 5 tests: trading competition intelligence.

Mock tests are clearly separated from live tests: every
test here uses an in-memory database and seeded
announcements, except the live smoke test, which is run
manually against the real CMS feed and is not part of
this file. Nothing here claims a live integration.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competitions.notifications import (
    format_competition_message,
    format_pkt,
    record_competition_notification,
)
from app.competitions.parsing import (
    classify_competition_type,
    extract_reward_pool,
    extract_trading_pairs,
    parse_competition,
    recompute_status,
    status_from_title,
)
from app.competitions.processing import (
    process_competitions,
    run_competition_collection,
    update_competition_statuses,
)
from app.database import Base, get_db
from app.main import app
from app.models import (
    Announcement,
    Competition,
    CompetitionCollectionRun,
    CompetitionUpdate,
)
from app.rate_limit import reset_rate_limits
from app.scheduler import register_jobs, scheduler

UTC = timezone.utc


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed(db, title, external_id="1", code="code1"):
    from app.announcements.service import ensure_default_source

    source = ensure_default_source(db)
    announcement = Announcement(
        source_id=source.id,
        source_name=source.name,
        external_id=external_id,
        code=code,
        title=title,
        slug="seed",
        canonical_url=f"https://www.binance.com/en/support/announcement/seed-{code}",
        category="TRADING_COMPETITION",
        category_confidence="high",
        published_at=datetime(2026, 10, 30, tzinfo=UTC),
        collected_at=datetime(2026, 10, 30, tzinfo=UTC),
        content_hash=f"hash-{code}",
        verification_status="official_website",
        metadata_json={},
        notification_status="pending",
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    return announcement


def _client_with_db(db):
    def _override_db():
        yield db

    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    reset_rate_limits()
    return TestClient(app, raise_server_exceptions=False), old


def _auth(client, db):
    """Seed a super-admin and log in; returns CSRF headers.

    Phase 8 adaptation only: earlier tests called collect
    endpoints unauthenticated. Every original assertion is
    preserved; only authentication is added.
    """
    from app.auth.dependencies import reset_login_rate_limits
    from app.auth.passwords import hash_password
    from app.auth.permissions import PERMISSIONS, ROLE_PERMISSIONS
    from app.models import (
        AdminPermission,
        AdminRole,
        AdminRolePermission,
        AdminUser,
        AdminUserRole,
    )

    reset_login_rate_limits()
    for name in ROLE_PERMISSIONS:
        if not db.query(AdminRole).filter(AdminRole.name == name).first():
            db.add(AdminRole(name=name))
    db.commit()
    for key in PERMISSIONS:
        if not db.query(AdminPermission).filter(AdminPermission.key == key).first():
            db.add(AdminPermission(key=key))
    db.commit()
    roles = {r.name: r.id for r in db.query(AdminRole).all()}
    perms = {p.key: p.id for p in db.query(AdminPermission).all()}
    for role, keys in ROLE_PERMISSIONS.items():
        for k in keys:
            if (
                not db.query(AdminRolePermission)
                .filter(
                    AdminRolePermission.role_id == roles[role],
                    AdminRolePermission.permission_id == perms[k],
                )
                .first()
            ):
                db.add(AdminRolePermission(role_id=roles[role], permission_id=perms[k]))
    db.commit()
    user = db.query(AdminUser).filter(AdminUser.username == "phase8-admin").first()
    if user is None:
        user = AdminUser(
            username="phase8-admin",
            email="phase8-admin@example.invalid",
            password_hash=hash_password("Password123"),
            role="super_admin",
            is_superuser=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(AdminUserRole(admin_user_id=user.id, role_id=roles["super_admin"]))
        db.commit()
    response = client.post(
        "/auth/login", json={"username": "phase8-admin", "password": "Password123"}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.cookies.get("admin_csrf")}


def _restore(old):
    if old is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = old
    reset_rate_limits()


def test_competition_type_classification():
    assert classify_competition_type("Binance Futures Trading Competition") == "FUTURES"
    assert classify_competition_type("Binance Spot Trading Competition") == "SPOT"
    assert classify_competition_type("Binance Team Trading Competition") == "TEAM"
    assert classify_competition_type("Binance Trading Volume Competition") == "VOLUME"
    assert classify_competition_type("Binance Trading Competition") == "GENERAL"
    # Team wins over Futures, by documented order.
    assert classify_competition_type("Binance Futures Team Competition") == "TEAM"


def test_trading_pair_extraction():
    pairs = extract_trading_pairs(
        "Trade BTCUSDT, ETHUSDT and SOL/USDT to win in the Futures Competition"
    )
    assert pairs == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert extract_trading_pairs("Binance Trading Competition with no pairs") == []


def test_reward_pool_extraction_only_with_explicit_amount_and_currency():
    amount, currency = extract_reward_pool(
        "Binance Futures Trading Competition: Share a 100,000 USDT Prize Pool"
    )
    assert amount == Decimal("100000")
    assert currency == "USDT"
    assert extract_reward_pool("Binance Trading Competition: Trade to win") == (None, None)
    # Amount without a currency is not a confirmed pool.
    assert extract_reward_pool("Binance Trading Competition: Share 100,000 in rewards") == (
        None,
        None,
    )
    # A trading amount in a non-reward title is not a pool.
    assert extract_reward_pool("Trade 100,000 USDT in volume") == (None, None)


def test_missing_information_stays_null():
    parsed = parse_competition("Binance Futures Trading Competition: Trade to Win")
    assert parsed["reward_pool"] is None
    assert parsed["reward_currency"] is None
    assert parsed["start_time"] is None
    assert parsed["end_time"] is None
    assert parsed["eligible_trading_pairs"] == []
    assert parsed["status"] == "UNKNOWN"


def test_explicit_iso_date_range_is_parsed():
    parsed = parse_competition(
        "Binance Trading Competition from 2026-11-01 to 2026-11-15: Trade to Win"
    )
    assert parsed["start_time"] == datetime(2026, 11, 1, tzinfo=UTC)
    assert parsed["end_time"] == datetime(2026, 11, 15, tzinfo=UTC)
    # A bare date without start/end wording is not parsed.
    parsed2 = parse_competition("Binance Trading Competition (2026-11-01): Trade to Win")
    assert parsed2["start_time"] is None


def test_unreliable_name_is_flagged_for_review():
    parsed = parse_competition("Binance Trading Competition: Trade to Win")
    assert parsed["verification_status"] == "official_website"
    parsed2 = parse_competition("Futures update")
    assert parsed2["verification_status"] == "needs_review"


def test_title_status_is_conservative():
    assert status_from_title("Trading Competition cancelled") == "CANCELLED"
    assert status_from_title("Trading Competition postponed") == "POSTPONED"
    assert status_from_title("Trading Competition has ended") == "ENDED"
    assert status_from_title("Trading Competition is now live") == "UNKNOWN"
    assert status_from_title("Trading Competition coming soon") == "UNKNOWN"


# Lifecycle -------------------------------------------------------------


class _StubCompetition:
    def __init__(self, status, start=None, end=None):
        self.status = status
        self.start_time = start
        self.end_time = end


def test_status_transitions_with_dates():
    comp = _StubCompetition(
        "UNKNOWN", datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 15, tzinfo=UTC)
    )
    assert recompute_status(comp, datetime(2026, 10, 20, tzinfo=UTC)) == "UPCOMING"
    assert recompute_status(comp, datetime(2026, 11, 5, tzinfo=UTC)) == "ACTIVE"
    assert recompute_status(comp, datetime(2026, 11, 20, tzinfo=UTC)) == "ENDED"


def test_unknown_stays_unknown_without_dates_and_terminal_is_not_overwritten():
    comp = _StubCompetition("UNKNOWN")
    assert recompute_status(comp, datetime(2026, 11, 5, tzinfo=UTC)) == "UNKNOWN"
    cancelled = _StubCompetition(
        "CANCELLED", datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 15, tzinfo=UTC)
    )
    assert recompute_status(cancelled, datetime(2026, 11, 5, tzinfo=UTC)) == "CANCELLED"
    postponed = _StubCompetition("POSTPONED")
    assert recompute_status(postponed) == "POSTPONED"


def test_timezone_handling_utc_storage_and_pkt_display():
    moment = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    assert format_pkt(moment) == "2026-11-01 05:00 PKT"
    naive = datetime(2026, 11, 1, 0, 0)
    assert format_pkt(naive) == "2026-11-01 05:00 PKT"
    assert format_pkt(None) is None


# Processing ------------------------------------------------------------


def test_processing_creates_and_deduplicates():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Futures Trading Competition: Trade BTCUSDT to Win a 50,000 USDT Prize Pool")
    first = process_competitions(db)
    assert first["created"] == 1
    assert first["skipped"] == 0
    second = process_competitions(db)
    assert second["created"] == 0
    assert second["skipped"] == 1
    comp = db.query(Competition).first()
    assert comp.competition_type == "FUTURES"
    assert comp.eligible_trading_pairs == ["BTCUSDT"]
    assert comp.reward_pool == Decimal("50000")
    assert comp.reward_currency == "USDT"
    assert comp.status == "UNKNOWN"


def test_alpha_trading_competition_titles_are_also_discovered():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    from app.announcements.service import ensure_default_source

    source = ensure_default_source(db)
    announcement = Announcement(
        source_id=source.id,
        source_name=source.name,
        external_id="7",
        code="code7",
        title="Binance Alpha Trading Competition: Trade Axis Robotics (AXIS) and Share Rewards",
        slug="seed",
        canonical_url="https://www.binance.com/en/support/announcement/seed-code7",
        category="ALPHA",
        category_confidence="high",
        published_at=datetime(2026, 10, 30, tzinfo=UTC),
        collected_at=datetime(2026, 10, 30, tzinfo=UTC),
        content_hash="hash-code7",
        verification_status="official_website",
        metadata_json={},
        notification_status="pending",
    )
    db.add(announcement)
    db.commit()
    summary = process_competitions(db)
    assert summary["created"] == 1
    comp = db.query(Competition).first()
    assert comp is not None
    assert "Axis Robotics" in comp.competition_name


def test_duplicate_announcement_id_is_blocked_by_unique_constraint():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    announcement = _seed(db, "Binance Trading Competition: Trade to Win")
    process_competitions(db)
    duplicate = Competition(
        announcement_id=announcement.id,
        competition_name="Duplicate",
        official_url="https://example.com",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cancellation_announcement_updates_existing_competition():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Futures Trading Competition: Trade BTCUSDT to Win", "1", "c1")
    process_competitions(db)
    _seed(
        db,
        "Binance Futures Trading Competition: Trade BTCUSDT to Win has been cancelled",
        "2",
        "c2",
    )
    summary = process_competitions(db)
    assert summary["updated"] == 1
    assert summary["created"] == 0
    assert db.query(Competition).count() == 1
    comp = db.query(Competition).first()
    assert comp.status == "CANCELLED"
    updates = db.query(CompetitionUpdate).filter_by(competition_id=comp.id).all()
    assert any(u.update_type == "status_change" for u in updates)


def test_postponement_and_date_status_updates_are_recorded():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Trading Competition from 2026-11-01 to 2026-11-15: Trade to Win")
    process_competitions(db)
    result = update_competition_statuses(db, datetime(2026, 11, 5, tzinfo=UTC))
    assert result["status_updates"] == 1
    comp = db.query(Competition).first()
    assert comp.status == "ACTIVE"
    assert db.query(CompetitionUpdate).filter_by(update_type="status_change").count() >= 1


def test_collection_run_records_counts_and_bad_announcement_does_not_stop_run():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Trading Competition: Trade to Win", "1", "c1")
    summary = run_competition_collection(db)
    assert summary["created"] == 1
    run = db.query(CompetitionCollectionRun).first()
    assert run.status == "completed"
    assert run.created == 1
    assert run.found == 1
    assert run.completed is not None


def test_scheduler_registration_is_idempotent():
    register_jobs()
    assert scheduler.get_job("competition_processing") is not None
    before = len(scheduler.get_jobs())
    register_jobs()
    assert len(scheduler.get_jobs()) == before
    job = scheduler.get_job("competition_processing")
    assert job.max_instances == 1


# API -------------------------------------------------------------------


def test_api_pagination_filtering_and_sorting():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Futures Trading Competition: Trade BTCUSDT to Win", "1", "c1")
    _seed(db, "Binance Spot Trading Competition: Trade ETHUSDT to Win", "2", "c2")
    process_competitions(db)
    client, old = _client_with_db(db)
    try:
        response = client.get("/competitions?competition_type=FUTURES")
        assert response.status_code == 200
        assert response.json()["total"] == 1
        response = client.get("/competitions?pair=ETHUSDT")
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["competition_type"] == "SPOT"
        response = client.get("/competitions?search=ETHUSDT")
        assert response.json()["total"] == 1
        response = client.get("/competitions?page=1&page_size=1")
        assert len(response.json()["items"]) == 1
        assert response.status_code == 200
        response = client.get("/competitions?sort=invalid")
        assert response.status_code == 400
    finally:
        _restore(old)


def test_api_active_upcoming_completed_detail_updates_pairs_and_404():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Trading Competition from 2026-11-01 to 2026-11-15: Trade BTCUSDT to Win")
    process_competitions(db)
    update_competition_statuses(db, datetime(2026, 11, 5, tzinfo=UTC))
    comp = db.query(Competition).first()
    client, old = _client_with_db(db)
    try:
        assert client.get("/competitions/active").json()["total"] == 1
        assert client.get("/competitions/upcoming").json()["total"] == 0
        assert client.get("/competitions/completed").json()["total"] == 0
        detail = client.get(f"/competitions/{comp.id}")
        assert detail.status_code == 200
        assert detail.json()["duration_seconds"] == 14 * 24 * 3600
        assert detail.json()["eligible_trading_pairs"] == ["BTCUSDT"]
        updates = client.get(f"/competitions/{comp.id}/updates")
        assert updates.json()["total"] >= 2
        pairs = client.get(f"/competitions/{comp.id}/pairs")
        assert pairs.json()["pairs"][0]["pair"] == "BTCUSDT"
        assert client.get("/competitions/99999").status_code == 404
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
        assert client.get("/competitions").status_code == 503
    finally:
        if old is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old
        reset_rate_limits()


def test_api_collect_uses_mock_cms_client():
    from unittest.mock import AsyncMock, patch

    from app.announcements.client import BinanceAnnouncementClient

    engine = _engine()
    db = sessionmaker(bind=engine)()
    client, old = _client_with_db(db)
    headers = _auth(client, db)
    try:
        with patch.object(
            BinanceAnnouncementClient,
            "fetch_announcements",
            new=AsyncMock(
                return_value=[
                    {
                        "external_id": "9",
                        "code": "code9",
                        "title": "Binance Futures Trading Competition: Trade BTCUSDT to Win",
                        "slug": "seed",
                        "canonical_url": "https://www.binance.com/en/support/announcement/seed-code9",
                        "category": "TRADING_COMPETITION",
                        "category_confidence": "high",
                        "published_at": datetime(2026, 10, 30, tzinfo=UTC),
                        "content_hash": "hash-code9",
                        "metadata": {"catalog_id": 93, "catalog_name": "Latest Activities"},
                    }
                ]
            ),
        ):
            response = client.post("/competitions/collect", headers=headers)
        assert response.status_code == 200
        assert response.json()["created"] == 1
        assert db.query(Competition).count() == 1
    finally:
        _restore(old)


# Telegram --------------------------------------------------------------


def test_telegram_formatting_and_duplicate_notification_prevention():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Futures Trading Competition: Trade BTCUSDT to Win a 50,000 USDT Prize Pool")
    process_competitions(db)
    comp = db.query(Competition).first()
    message = format_competition_message(comp, "new_competition")
    assert "Trading Competition" in message
    assert "Type: FUTURES" in message
    assert "50,000" in message or "50000" in message
    assert "BTCUSDT" in message
    assert "binance.com" in message
    assert record_competition_notification(db, comp, "new_competition") is True
    assert record_competition_notification(db, comp, "new_competition") is False
    assert record_competition_notification(db, comp, "cancelled") is True
    undated = format_competition_message(comp, "cancelled")
    assert "Not officially confirmed" in undated


def test_bot_competition_commands():
    import app.bot as bot_module
    from app.bot import competition_handler

    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Futures Trading Competition: Trade BTCUSDT to Win", "1", "c1")
    process_competitions(db)
    update_competition_statuses(db, datetime(2026, 11, 5, tzinfo=UTC))

    class _FakeMessage:
        def __init__(self, text):
            self.text = text
            self.answers = []

        async def answer(self, text):
            self.answers.append(text)

    old_db_fn = bot_module._db
    bot_module._db = lambda: db
    try:
        message = _FakeMessage("/competition")
        asyncio.run(competition_handler(message))
        assert "Trading Competition" in message.answers[0]
        assert "Type: FUTURES" in message.answers[0]
        search = _FakeMessage("/competition search BTCUSDT")
        asyncio.run(competition_handler(search))
        assert "Trading Competition" in search.answers[0]
        empty = _FakeMessage("/competition active")
        asyncio.run(competition_handler(empty))
        assert empty.answers[0] == "None recorded yet."
        usage = _FakeMessage("/competition search")
        asyncio.run(competition_handler(usage))
        assert "Usage" in usage.answers[0]
    finally:
        bot_module._db = old_db_fn
