import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.announcements.client import BinanceAnnouncementClient
from app.announcements.service import ensure_default_source
from app.database import Base, get_db
from app.intelligence.allocation import estimate_allocation
from app.intelligence.notifications import (
    format_airdrop_message,
    format_alpha_message,
    format_prime_sale_message,
    record_notification,
)
from app.intelligence.parsing import (
    airdrop_status,
    extract_eligibility,
    parse_token,
    prime_sale_status,
)
from app.intelligence.processing import (
    process_airdrops,
    process_alpha,
    process_prime_sales,
    refresh_alpha_market_data,
)
from app.main import app
from app.models import (
    AirdropCampaign,
    AlphaToken,
    Announcement,
    PrimeSale,
)
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


def _seed(db, title, category, external_id="1", code="code1"):
    source = ensure_default_source(db)
    announcement = Announcement(
        source_id=source.id,
        source_name=source.name,
        external_id=external_id,
        code=code,
        title=title,
        slug="seed",
        canonical_url=f"https://www.binance.com/en/support/announcement/seed-{code}",
        category=category,
        category_confidence="high",
        published_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        collected_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        content_hash=f"hash-{code}",
        verification_status="official_website",
        metadata_json={},
        notification_status="pending",
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    return announcement


class _FakeMarket:
    def __init__(self, price="2.50", change="0.10", volume="1000"):
        self.price = price
        self.change = change
        self.volume = volume

    async def get_ticker_24hr(self, symbol):
        return {
            "price": self.price,
            "price_change_24h": self.change,
            "volume_24h": self.volume,
            "source": "binance_spot",
        }


class _FailingMarket:
    async def get_ticker_24hr(self, symbol):
        raise RuntimeError("Binance unavailable")


# Parsing ---------------------------------------------------------------


def test_token_parsing_and_normalisation():
    parsed = parse_token("Binance Alpha Adds TestCoin (TEST) on Ethereum")
    assert parsed["token_name"] == "TestCoin"
    assert parsed["token_symbol"] == "TEST"
    assert parsed["blockchain_network"] == "Ethereum"
    assert parsed["contract_address"] is None


def test_contract_and_network_parsing():
    address = "0x" + "ab" * 20
    parsed = parse_token(f"Binance Alpha Adds ChainCoin (CHAIN) on Solana {address}")
    assert parsed["contract_address"] == address
    assert parsed["blockchain_network"] == "Solana"


def test_missing_token_metadata():
    parsed = parse_token("Binance Alpha Adds MysteryToken")
    assert parsed["token_name"] == "MysteryToken"
    assert parsed["token_symbol"] is None
    assert parsed["contract_address"] is None
    assert parsed["blockchain_network"] is None


def test_removal_and_competition_titles_do_not_become_fake_tokens():
    parsed = parse_token("Binance Alpha Will Remove AAA, BBB, CCC (2026-10-23)")
    assert parsed["is_multi_token"] is True
    assert parsed["token_symbol"] is None
    parsed2 = parse_token("Binance Alpha Trading Competition: Trade Axis Robotics (AXIS)")
    assert parsed2["token_name"] == "Axis Robotics"
    assert parsed2["token_symbol"] == "AXIS"


def test_airdrop_status_is_conservative():
    assert airdrop_status("Airdrop claim is open now") == "CLAIMING"
    assert airdrop_status("Airdrop campaign has ended") == "ENDED"
    assert airdrop_status("Airdrop coming soon") == "UPCOMING"
    assert airdrop_status("Airdrop campaign cancelled") == "CANCELLED"
    assert airdrop_status("Airdrop campaign details") == "UNKNOWN"


def test_prime_status_is_conservative():
    assert prime_sale_status("Prime Sale subscription is now open") == "ACTIVE"
    assert prime_sale_status("Prime Sale subscription coming soon") == "UPCOMING"
    assert prime_sale_status("Prime Sale distribution completed") == "DISTRIBUTION_COMPLETED"
    assert prime_sale_status("Prime Sale details announced") == "UNKNOWN"


def test_eligibility_extraction_only_when_recognisable():
    hints = extract_eligibility("Airdrop for Binance Alpha points holders, participation required")
    types = {h["requirement_type"] for h in hints}
    assert "alpha_points" in types
    assert "participation" in types
    assert all(h["is_confirmed_details"] is False for h in hints)
    assert extract_eligibility("Airdrop campaign details") == []


# Allocation ------------------------------------------------------------


def test_allocation_decimal_precision():
    result = estimate_allocation(Decimal("1"), Decimal("3"), Decimal("100"))
    assert result["is_estimate"] is True
    # Decimal division, not float: 1/3 * 100 is not 33.33 exactly.
    assert result["estimated_allocation"] != Decimal("33.33")
    assert estimate_allocation(Decimal("100"), Decimal("400"), Decimal("1000"))[
        "estimated_allocation"
    ] == Decimal("250")


def test_allocation_missing_or_zero_total_is_error():
    with pytest.raises(ValueError, match="total_commitment"):
        estimate_allocation(Decimal("10"), Decimal("0"), Decimal("100"))
    with pytest.raises(ValueError, match="total_commitment"):
        estimate_allocation(Decimal("10"), None, Decimal("100"))
    with pytest.raises(ValueError, match="user_commitment"):
        estimate_allocation(None, Decimal("100"), Decimal("100"))


# Processing ------------------------------------------------------------


def test_alpha_processing_market_data_and_duplicates():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Alpha Adds TestCoin (TEST) on Ethereum", "ALPHA")
    summary = asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    assert summary == {"created": 1, "skipped": 0}
    token = db.query(AlphaToken).first()
    assert token.token_symbol == "TEST"
    assert token.current_price == Decimal("2.50")
    assert token.market_data_status == "available"
    assert token.trading_pairs == ["TESTUSDT"]
    # Second run: duplicate announcement is skipped, no second token.
    summary2 = asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    assert summary2["skipped"] == 1
    assert db.query(AlphaToken).count() == 1


def test_alpha_processing_market_failure_leaves_null_not_zero():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Alpha Adds FailCoin (FAIL)", "ALPHA")
    asyncio.run(process_alpha(db, market_client=_FailingMarket()))
    token = db.query(AlphaToken).first()
    assert token.current_price is None
    assert token.volume_24h is None
    assert token.market_data_status == "unavailable"


def test_alpha_market_refresh_records_price_change():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Alpha Adds TestCoin (TEST)", "ALPHA")
    asyncio.run(process_alpha(db, market_client=_FakeMarket(price="2.50")))
    refreshed = asyncio.run(refresh_alpha_market_data(db, market_client=_FakeMarket(price="3.00")))
    assert refreshed["updated"] == 1
    token = db.query(AlphaToken).first()
    assert token.current_price == Decimal("3.00")
    from app.models import AlphaTokenUpdate

    updates = db.query(AlphaTokenUpdate).order_by(AlphaTokenUpdate.id.asc()).all()
    assert [u.update_type for u in updates] == ["created", "price_update"]


def test_airdrop_processing_eligibility_and_duplicates():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(
        db,
        "Binance Airdrop: Alpha points holders can claim DropCoin (DROP)",
        "AIRDROP",
        external_id="2",
        code="code2",
    )
    summary = process_airdrops(db)
    assert summary["created"] == 1
    campaign = db.query(AirdropCampaign).first()
    assert campaign.token_symbol == "DROP"
    assert campaign.status == "UNKNOWN"
    from app.models import AirdropEligibility

    assert db.query(AirdropEligibility).filter_by(campaign_id=campaign.id).count() >= 1
    assert process_airdrops(db)["skipped"] == 1
    assert db.query(AirdropCampaign).count() == 1


def test_prime_processing_creates_unknown_allocation_rule():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Prime Sale: PrimeCoin (PRIME) Subscription Coming Soon", "PRIME_SALE")
    summary = process_prime_sales(db)
    assert summary["created"] == 1
    sale = db.query(PrimeSale).first()
    assert sale.status == "UPCOMING"
    assert sale.subscription_price is None
    assert sale.min_commitment is None
    from app.models import PrimeSaleAllocationRule

    rule = db.query(PrimeSaleAllocationRule).filter_by(sale_id=sale.id).first()
    assert rule is not None
    assert rule.formula_type == "unknown"
    assert process_prime_sales(db)["skipped"] == 1


# Notifications ---------------------------------------------------------


def test_telegram_formatting_and_duplicate_notification_record():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Alpha Adds TestCoin (TEST)", "ALPHA")
    asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    token = db.query(AlphaToken).first()
    message = format_alpha_message(token)
    assert "TestCoin" in message
    assert "TEST" in message
    assert token.announcement_url in message
    assert (
        record_notification(db, "alpha_token", token.id, "new_token", token.announcement_id) is True
    )
    assert (
        record_notification(db, "alpha_token", token.id, "new_token", token.announcement_id)
        is False
    )
    assert (
        db.query(
            __import__("app.models", fromlist=["CampaignNotification"]).CampaignNotification
        ).count()
        == 1
    )


def test_airdrop_and_prime_message_formatting():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Airdrop campaign details", "AIRDROP", external_id="3", code="code3")
    _seed(db, "Prime Sale details announced", "PRIME_SALE", external_id="4", code="code4")
    process_airdrops(db)
    process_prime_sales(db)
    campaign = db.query(AirdropCampaign).first()
    sale = db.query(PrimeSale).first()
    assert campaign.official_url in format_airdrop_message(campaign)
    assert sale.official_url in format_prime_sale_message(sale)


# Scheduler -------------------------------------------------------------


def test_scheduler_registration_idempotent_with_phase4_jobs():
    register_jobs()
    register_jobs()
    for job_id in (
        "announcement_collection",
        "alpha_processing",
        "airdrop_processing",
        "prime_sale_processing",
    ):
        jobs = [job for job in scheduler.get_jobs() if job.id == job_id]
        assert len(jobs) == 1
        assert jobs[0].max_instances == 1
    for job_id in ("alpha_processing", "airdrop_processing", "prime_sale_processing"):
        scheduler.remove_job(job_id)


# API -------------------------------------------------------------------


def _api_client(db):
    def _override_db():
        yield db

    old_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    return old_db


def _restore_api(old_db):
    if old_db is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = old_db
    reset_rate_limits()


def test_api_pagination_filtering_validation_and_404():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Alpha Adds TestCoin (TEST)", "ALPHA")
    _seed(db, "Binance Alpha Adds OtherCoin (OTHER)", "ALPHA", external_id="5", code="code5")
    asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    _seed(db, "Airdrop campaign details", "AIRDROP", external_id="6", code="code6")
    process_airdrops(db)
    _seed(db, "Prime Sale subscription is now open", "PRIME_SALE", external_id="7", code="code7")
    process_prime_sales(db)
    old_db = _api_client(db)
    try:
        reset_rate_limits()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/alpha/tokens", params={"symbol": "TEST"})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["current_price"] == "2.50000000"
        response = client.get("/alpha/tokens", params={"page": 2, "page_size": 1})
        assert len(response.json()["items"]) == 1
        response = client.get("/alpha/tokens/999999")
        assert response.status_code == 404
        response = client.get("/alpha/updates")
        assert response.json()["total"] == 2
        response = client.get("/airdrops")
        assert response.json()["total"] == 1
        # No eligibility records for this campaign: the note must appear.
        assert (
            response.json()["items"][0]["eligibility_note"]
            == "Eligibility details not officially confirmed."
        )
        response = client.get("/airdrops/active")
        assert response.json()["total"] == 0
        response = client.get("/airdrops/999999")
        assert response.status_code == 404
        response = client.get("/prime-sales/active")
        assert response.json()["total"] == 1
        response = client.get("/prime-sales/999999")
        assert response.status_code == 404
        # Allocation: valid estimate, labelled as an estimate.
        response = client.post(
            "/prime-sales/estimate-allocation",
            json={
                "user_commitment": "100",
                "total_commitment": "400",
                "total_token_allocation": "1000",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["estimated_allocation"]) == Decimal("250")
        assert body["is_estimate"] is True
        assert "not a guaranteed" in body["guarantee"]
        # Allocation: zero total is a validation error, not an invented total.
        response = client.post(
            "/prime-sales/estimate-allocation",
            json={
                "user_commitment": "100",
                "total_commitment": "0",
                "total_token_allocation": "1000",
            },
        )
        assert response.status_code == 422
        response = client.post(
            "/prime-sales/estimate-allocation",
            json={"user_commitment": "100", "total_token_allocation": "1000"},
        )
        assert response.status_code == 422
    finally:
        _restore_api(old_db)


def test_api_collect_with_mock_cms():
    engine = _engine()
    db = sessionmaker(bind=engine)()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "000000",
                "data": {
                    "catalogs": [
                        {
                            "catalogId": 48,
                            "catalogName": "New Cryptocurrency Listing",
                            "articles": [
                                {
                                    "id": 201,
                                    "code": "alpha201",
                                    "title": "Binance Alpha Adds CollectCoin",
                                    "type": 1,
                                    "releaseDate": 1793274532000,
                                }
                            ],
                        }
                    ]
                },
            },
        )

    mock_client = BinanceAnnouncementClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    )
    old_db = _api_client(db)
    try:
        reset_rate_limits()
        client = TestClient(app, raise_server_exceptions=False)
        from unittest.mock import patch

        from app.api import intelligence as intelligence_api

        with patch.object(intelligence_api, "BinanceAnnouncementClient", return_value=mock_client):
            response = client.post("/alpha/collect")
            assert response.status_code == 200
            assert response.json()["created"] == 1
            response = client.post("/alpha/collect")
            assert response.json()["created"] == 0
            assert response.json()["skipped"] == 1
        assert db.query(AlphaToken).count() == 1
    finally:
        _restore_api(old_db)


def test_api_database_failure_returns_503():
    from sqlalchemy.exc import OperationalError

    class _FailingQuery:
        def filter(self, *args, **kwargs):
            raise OperationalError("select", {}, Exception("connection failed"))

        def order_by(self, *args, **kwargs):
            raise OperationalError("select", {}, Exception("connection failed"))

        def count(self):
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
        assert client.get("/alpha/tokens").status_code == 503
        assert client.get("/airdrops").status_code == 503
        assert client.get("/prime-sales").status_code == 503
    finally:
        if old_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_db
        reset_rate_limits()


# Bot -------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, text):
        self.text = text
        self.answers = []

    async def answer(self, text):
        self.answers.append(text)


def test_bot_commands():
    import app.bot as bot_module
    from app.bot import alpha_handler, airdrops_handler, prime_handler

    engine = _engine()
    db = sessionmaker(bind=engine)()
    _seed(db, "Binance Alpha Adds TestCoin (TEST)", "ALPHA")
    asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    _seed(db, "Prime Sale subscription is now open", "PRIME_SALE", external_id="8", code="code8")
    process_prime_sales(db)
    old_db_fn = bot_module._db
    bot_module._db = lambda: db
    try:
        message = _FakeMessage("/alpha TEST")
        asyncio.run(alpha_handler(message))
        assert "TestCoin" in message.answers[0]
        assert "TEST" in message.answers[0]
        empty = _FakeMessage("/airdrops active")
        asyncio.run(airdrops_handler(empty))
        assert empty.answers[0] == "None recorded yet."
        prime = _FakeMessage("/prime active")
        asyncio.run(prime_handler(prime))
        assert "Status: ACTIVE" in prime.answers[0]
        estimate = _FakeMessage("/prime estimate 100 400 1000")
        asyncio.run(prime_handler(estimate))
        assert "250" in estimate.answers[0]
        assert "estimate" in estimate.answers[0].lower()
    finally:
        bot_module._db = old_db_fn
