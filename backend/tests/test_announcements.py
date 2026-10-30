import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.announcements.classifier import CATEGORIES, classify_announcement
from app.announcements.client import BinanceAnnouncementClient, normalize_article
from app.announcements.notifications import (
    format_announcement_message,
    notify_pending_announcements,
)
from app.announcements.service import collect_from_source_async, ensure_default_source
from app.database import Base, get_db
from app.main import app
from app.models import Announcement, CollectionRun
from app.rate_limit import reset_rate_limits
from app.scheduler import register_jobs, scheduler


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _cms_payload():
    return {
        "code": "000000",
        "data": {
            "catalogs": [
                {
                    "catalogId": 48,
                    "catalogName": "New Cryptocurrency Listing",
                    "articles": [
                        {
                            "id": 111,
                            "code": "aaa111",
                            "title": "Binance Will List TestCoin (TEST) with Seed Tag Applied",
                            "type": 1,
                            "releaseDate": 1793274532000,
                        },
                        {
                            "id": 112,
                            "code": "bbb222",
                            "title": "Binance Will Delist OldCoin (OLD)",
                            "type": 1,
                            "releaseDate": 1793274533000,
                        },
                    ],
                }
            ]
        },
    }


def _mock_client(payload=None, status=200):
    payload = payload if payload is not None else _cms_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return BinanceAnnouncementClient(
        base_url="https://example.invalid",
        transport=httpx.MockTransport(handler),
    )


def test_source_parsing_and_normalization():
    article = _cms_payload()["data"]["catalogs"][0]["articles"][0]
    item = normalize_article(article, 48, "New Cryptocurrency Listing")
    assert item["external_id"] == "111"
    assert item["code"] == "aaa111"
    assert item["canonical_url"].endswith("-aaa111")
    assert item["published_at"] == datetime.fromtimestamp(1793274532, tz=timezone.utc)
    assert item["category"] == "SPOT_LISTING"
    # Missing releaseDate must not invent a time.
    bad = dict(article)
    del bad["releaseDate"]
    assert normalize_article(bad, 48, "New Cryptocurrency Listing") is None


def test_category_classification():
    assert classify_announcement("Binance Will Delist X")[0] == "DELISTING"
    assert classify_announcement("Binance Futures Will Launch X Perpetual")[0] == "FUTURES_LISTING"
    assert classify_announcement("Join the Airdrop Campaign")[0] == "AIRDROP"
    assert classify_announcement("Binance Alpha Adds Y")[0] == "ALPHA"
    assert classify_announcement("Something completely unrelated", 49)[0] == "GENERAL"
    assert classify_announcement("Something completely unrelated", None) == ("OTHER", "low")
    assert "SPOT_LISTING" in CATEGORIES and "DELISTING" in CATEGORIES


def test_duplicate_detection_and_persistence_and_uniqueness():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    source = ensure_default_source(db)
    client = _mock_client()
    run1, created1 = asyncio.run(collect_from_source_async(db, source, client))
    assert run1.status == "success"
    assert run1.announcements_found == 2
    assert run1.announcements_created == 2
    assert len(created1) == 2
    run2, created2 = asyncio.run(collect_from_source_async(db, source, client))
    assert run2.duplicates_skipped == 2
    assert created2 == []
    assert db.query(Announcement).count() == 2
    # Database uniqueness constraint: same source + external id.
    from sqlalchemy.exc import IntegrityError

    duplicate = Announcement(
        source_id=source.id,
        source_name=source.name,
        external_id="111",
        code="aaa111",
        title="Duplicate",
        canonical_url="https://example.invalid/other",
        category="OTHER",
        content_hash="x",
        collected_at=datetime.now(timezone.utc),
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_collection_failure_records_failed_run():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    source = ensure_default_source(db)
    client = _mock_client(status=500)
    with pytest.raises(Exception):
        asyncio.run(collect_from_source_async(db, source, client))
    run = db.query(CollectionRun).order_by(CollectionRun.id.desc()).first()
    assert run.status == "failed"
    assert run.error_message
    assert source.last_error_at is not None


def test_collection_retry_succeeds_after_429():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"code": -1003, "message": "Too many requests"})
        return httpx.Response(200, json=_cms_payload())

    client = BinanceAnnouncementClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    )
    engine = _engine()
    db = sessionmaker(bind=engine)()
    source = ensure_default_source(db)
    run, created = asyncio.run(collect_from_source_async(db, source, client))
    assert run.status == "success"
    assert len(created) == 2
    assert calls["count"] == 2


def test_scheduler_registration_is_idempotent():
    # Scheduler needs a running loop to start, but registration
    # itself (add_job) does not require the scheduler to be running.
    register_jobs()
    register_jobs()
    jobs = [job for job in scheduler.get_jobs() if job.id == "announcement_collection"]
    assert len(jobs) == 1
    assert jobs[0].max_instances == 1
    scheduler.remove_job("announcement_collection")


class _FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id, text, parse_mode=None):
        if self.fail:
            raise RuntimeError("Telegram unavailable")
        self.sent.append((chat_id, text))


def test_telegram_formatting_and_duplicate_prevention_and_failure():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    source = ensure_default_source(db)
    client = _mock_client()
    _run, created = asyncio.run(collect_from_source_async(db, source, client))
    announcement = created[0]
    message = format_announcement_message(announcement)
    assert announcement.title in message
    assert announcement.category in message
    assert announcement.canonical_url in message

    bot = _FakeBot()
    sent = asyncio.run(notify_pending_announcements(db, bot=bot))
    assert sent == 2
    assert len(bot.sent) == 2
    # Second pass must not resend.
    sent_again = asyncio.run(notify_pending_announcements(db, bot=bot))
    assert sent_again == 0
    assert len(bot.sent) == 2
    assert db.query(Announcement).filter_by(notification_status="sent").count() == 2

    # Delivery failure: status becomes failed, attempts increase.
    engine2 = _engine()
    db2 = sessionmaker(bind=engine2)()
    source2 = ensure_default_source(db2)
    _run2, created2 = asyncio.run(collect_from_source_async(db2, source2, _mock_client()))
    failing_bot = _FakeBot(fail=True)
    sent_failed = asyncio.run(notify_pending_announcements(db2, bot=failing_bot))
    assert sent_failed == 0
    assert db2.query(Announcement).filter_by(notification_status="failed").count() == 2


def test_api_database_failure_returns_503():
    from sqlalchemy.exc import OperationalError

    class _FailingQuery:
        def filter(self, *args, **kwargs):
            raise OperationalError("select", {}, Exception("connection failed"))

        def order_by(self, *args, **kwargs):
            raise OperationalError("select", {}, Exception("connection failed"))

    class _FailingDb:
        def query(self, *args, **kwargs):
            return _FailingQuery()

    def _failing_db():
        yield _FailingDb()

    old_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _failing_db
    try:
        reset_rate_limits()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/announcements")
        assert response.status_code == 503
    finally:
        if old_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_db
        reset_rate_limits()


def test_api_pagination_filtering_and_manual_collect():
    engine = _engine()
    db = sessionmaker(bind=engine)()

    def _override_db():
        yield db

    old_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    try:
        reset_rate_limits()
        client = TestClient(app, raise_server_exceptions=False)
        # Seed via the service directly, then test the API.
        source = ensure_default_source(db)
        asyncio.run(collect_from_source_async(db, source, _mock_client()))
        response = client.get("/announcements")
        assert response.status_code == 200
        assert response.json()["total"] == 2
        response = client.get("/announcements", params={"category": "DELISTING"})
        assert response.json()["total"] == 1
        response = client.get("/announcements", params={"search": "TestCoin"})
        assert response.json()["total"] == 1
        response = client.get("/announcements", params={"page": 2, "page_size": 1})
        assert len(response.json()["items"]) == 1
        response = client.get("/announcements/categories")
        assert "DELISTING" in response.json()["categories"]
        response = client.get("/announcements/sources")
        assert len(response.json()["sources"]) == 1
        response = client.get("/announcements/collection-runs")
        assert response.json()["total"] == 1
        first_id = client.get("/announcements").json()["items"][0]["id"]
        response = client.get(f"/announcements/{first_id}")
        assert response.status_code == 200
        response = client.get("/announcements/999999")
        assert response.status_code == 404
        response = client.patch(
            f"/announcements/sources/{source.id}", json={"polling_interval_seconds": 600}
        )
        assert response.status_code == 200
        assert response.json()["polling_interval_seconds"] == 600
        response = client.patch("/announcements/sources/999999", json={"enabled": False})
        assert response.status_code == 404
        # Manual collection endpoint, with the CMS client patched
        # to a mock transport so no live network is required.
        from unittest.mock import patch

        from app.api import announcements as announcements_api

        with patch.object(
            announcements_api, "BinanceAnnouncementClient", return_value=_mock_client()
        ):
            response = client.post("/announcements/collect", json={})
            assert response.status_code == 200
            # Second manual collect: all items are duplicates.
            assert response.json()["duplicates_skipped"] == 2
            response = client.post(f"/announcements/sources/{source.id}/collect", json={})
            assert response.status_code == 200
    finally:
        if old_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_db
        reset_rate_limits()
