"""Phase 7 tests: market, futures, and news intelligence.

Mock tests only for the core suite: every test uses
an in-memory database and fake clients or mocked
httpx transports. Nothing here depends on live
Binance, and nothing here claims a live integration.
Live Spot/Futures results are recorded separately
in docs/MARKET_FUTURES_NEWS.md, not in this file.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.bot as bot_module
from app.binance.client import BinanceAPIError, BinanceClient, validate_symbol
from app.bot import market_handler, news_handler, price_handler
from app.database import Base, get_db
from app.main import app
from app.marketintel.classification import (
    classify_news,
    extract_listing_token,
    extract_related_symbols,
    news_fingerprint,
)
from app.marketintel.notifications import format_market_alert_message
from app.marketintel.service import (
    collect_futures,
    collect_futures_ratios,
    collect_rss_items,
    detect_movements,
    funding_alerts,
    gainers_losers,
    is_stale,
    open_interest_change,
    parse_rss,
    parse_ticker,
    process_news,
)
from app.marketintel.scheduler_jobs import (
    JOB_FUNDING,
    JOB_LISTINGS,
    JOB_MARKET_SNAPSHOT,
    JOB_MOVEMENT,
    JOB_NEWS,
    JOB_OPEN_INTEREST,
)
from app.models import (
    Announcement,
    CryptoNews,
    FuturesMarketRatio,
    FuturesSnapshot,
    MarketAlert,
    MarketSnapshot,
    MarketWatchlist,
    NewsSource,
)
from app.rate_limit import reset_rate_limits
from app.scheduler import register_jobs, scheduler

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


def _db():
    return sessionmaker(bind=_engine())()


def _announcement(db, title, category, code="c1", external="ext-1"):
    from app.announcements.service import ensure_default_source

    source = ensure_default_source(db)
    row = Announcement(
        source_id=source.id,
        source_name=source.name,
        external_id=external,
        code=code,
        title=title,
        slug="seed",
        canonical_url=f"https://www.binance.com/en/support/announcement/seed-{code}",
        category=category,
        category_confidence="high",
        published_at=datetime(2026, 11, 1, tzinfo=UTC),
        collected_at=datetime(2026, 11, 1, tzinfo=UTC),
        content_hash=f"hash-{code}",
        verification_status="official_website",
        metadata_json={},
        notification_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _snapshot(db, symbol, price, change_pct, quote_volume, collected_at=NOW):
    row = MarketSnapshot(
        symbol=symbol,
        source="binance_spot",
        price=Decimal(str(price)),
        price_change_24h=Decimal("0"),
        price_change_percent_24h=Decimal(str(change_pct)),
        high_24h=Decimal(str(price)),
        low_24h=Decimal(str(price)),
        volume_24h=Decimal("1"),
        quote_volume_24h=Decimal(str(quote_volume)),
        collected_at=collected_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _futures(db, symbol, funding, oi, collected_at=NOW):
    row = FuturesSnapshot(
        symbol=symbol,
        source="binance_futures",
        funding_rate=Decimal(str(funding)) if funding is not None else None,
        next_funding_time=None,
        mark_price=Decimal("100"),
        open_interest=Decimal(str(oi)) if oi is not None else None,
        collected_at=collected_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


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


# Market parsing / sorting ------------------------------------------------


def test_parse_ticker_decimal():
    parsed = parse_ticker(
        {
            "symbol": "BTCUSDT",
            "price": "0.00001234",
            "price_change_percent_24h": "2.5",
            "quote_volume_24h": "1234567",
        }
    )
    assert parsed["price"] == Decimal("0.00001234")
    assert isinstance(parsed["price"], Decimal)


def test_gainers_losers_sorting_and_volume_filter():
    rows = [
        {
            "symbol": "AAAUSDT",
            "price": "1",
            "price_change_percent_24h": "20",
            "quote_volume_24h": "2000000",
        },
        {
            "symbol": "BBBUSDT",
            "price": "1",
            "price_change_percent_24h": "-15",
            "quote_volume_24h": "2000000",
        },
        {
            "symbol": "CCCUSDT",
            "price": "1",
            "price_change_percent_24h": "99",
            "quote_volume_24h": "10",
        },
        {
            "symbol": "DDDUSDT",
            "price": "1",
            "price_change_percent_24h": None,
            "quote_volume_24h": "2000000",
        },
    ]
    result = gainers_losers(rows, limit=10, min_quote_volume=1000000)
    assert [r["symbol"] for r in result["gainers"]] == ["AAAUSDT", "BBBUSDT"]
    assert [r["symbol"] for r in result["losers"]] == ["BBBUSDT", "AAAUSDT"]
    assert result["excluded_low_liquidity"] == 1


def test_symbol_validation():
    assert validate_symbol("btcusdt") == "BTCUSDT"
    with pytest.raises(ValueError):
        validate_symbol("btc usdt!")


# Movement detection ------------------------------------------------------


def test_movement_threshold_and_cooldown():
    db = _db()
    old = _snapshot(db, "BTCUSDT", "100", "0", "1000", NOW - timedelta(minutes=10))
    new = _snapshot(db, "BTCUSDT", "107", "7", "1000", NOW)
    alerts = detect_movements(db, [new], {"BTCUSDT": old}, now=NOW)
    assert len(alerts) == 1
    assert alerts[0].alert_type == "price_up"
    assert alerts[0].threshold_percent == Decimal("5")
    # Same movement within cooldown: no duplicate.
    again = detect_movements(db, [new], {"BTCUSDT": old}, now=NOW)
    assert again == []
    # A 12% move crosses the 10% level.
    newer = _snapshot(db, "BTCUSDT", "112", "12", "1000", NOW)
    alerts = detect_movements(db, [newer], {"BTCUSDT": old}, now=NOW + timedelta(hours=2))
    assert alerts[0].threshold_percent == Decimal("10")


def test_movement_below_threshold_and_volume_spike():
    db = _db()
    old = _snapshot(db, "ETHUSDT", "100", "0", "1000", NOW - timedelta(minutes=10))
    new = _snapshot(db, "ETHUSDT", "102", "2", "3000", NOW)
    alerts = detect_movements(db, [new], {"ETHUSDT": old}, now=NOW)
    assert [a.alert_type for a in alerts] == ["volume_spike"]


def test_stale_market_data():
    assert is_stale(NOW - timedelta(minutes=30), freshness_minutes=10, now=NOW) is True
    assert is_stale(NOW, freshness_minutes=10, now=NOW) is False
    assert is_stale(None) is True


# Futures -----------------------------------------------------------------


def test_funding_sorting_and_decimal():
    db = _db()
    _futures(db, "BTCUSDT", "0.0001", "1000")
    _futures(db, "ETHUSDT", "-0.0005", "2000")
    client, old = _client_with_db(db)
    try:
        response = client.get("/futures/funding?sort=highest")
        assert response.status_code == 200
        assert response.json()["items"][0]["symbol"] == "BTCUSDT"
        assert Decimal(response.json()["items"][0]["funding_rate"]) == Decimal("0.0001")
        lowest = client.get("/futures/funding?sort=lowest")
        assert lowest.json()["items"][0]["symbol"] == "ETHUSDT"
        bad = client.get("/futures/funding?sort=bogus")
        assert bad.status_code == 400
    finally:
        _restore(old)


def test_open_interest_change():
    db = _db()
    _futures(db, "BTCUSDT", "0.0001", "1000", NOW - timedelta(minutes=15))
    _futures(db, "BTCUSDT", "0.0001", "1100", NOW)
    assert open_interest_change(db, "BTCUSDT") == Decimal("10")
    assert open_interest_change(db, "ETHUSDT") is None


def test_funding_alerts_threshold_and_cooldown():
    db = _db()
    _futures(db, "BTCUSDT", "0.002", "1000")
    _futures(db, "ETHUSDT", "0.0001", "1000")
    alerts = funding_alerts(db, now=NOW)
    assert len(alerts) == 1
    assert alerts[0].alert_type == "funding_high"
    assert funding_alerts(db, now=NOW) == []


class _FailingFuturesClient:
    async def get_funding_rate(self, symbol):
        raise BinanceAPIError("Service unavailable from a restricted location", status=451, code=0)

    async def get_premium_index(self, symbol):
        raise BinanceAPIError("Service unavailable from a restricted location", status=451, code=0)

    async def get_open_interest(self, symbol):
        raise BinanceAPIError("Service unavailable from a restricted location", status=451, code=0)

    async def get_futures_long_short(self, symbol, kind, period="5m", limit=1):
        raise BinanceAPIError("Service unavailable from a restricted location", status=451, code=0)


def test_futures_451_degraded_without_spot_failure():
    db = _db()
    _snapshot(db, "BTCUSDT", "100", "1", "2000000")
    result = asyncio.run(collect_futures(db, _FailingFuturesClient(), ["BTCUSDT"]))
    assert result["status"] == "unavailable"
    assert result["collected"] == 0
    # Spot data is untouched by the Futures failure.
    assert db.query(MarketSnapshot).count() == 1
    assert db.query(FuturesSnapshot).count() == 0


def test_futures_summary_unavailable():
    db = _db()
    client, old = _client_with_db(db)
    try:
        response = client.get("/futures/summary")
        assert response.status_code == 200
        assert response.json()["availability"] == "unavailable"
    finally:
        _restore(old)


def test_long_short_client_labelling():
    def handler(request):
        path = request.url.path
        if "takerlongshortRatio" in path:
            return httpx.Response(
                200,
                json=[
                    {
                        "buyVol": "10",
                        "sellVol": "5",
                        "buySellRatio": "2.0",
                        "timestamp": 1762000000000,
                    }
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "longAccount": "0.6",
                    "shortAccount": "0.4",
                    "longShortRatio": "1.5",
                    "timestamp": 1762000000000,
                }
            ],
        )

    client = BinanceClient(
        "https://spot.example", "https://fapi.example", transport=httpx.MockTransport(handler)
    )
    account = asyncio.run(client.get_futures_long_short("BTCUSDT", "global_account"))
    assert account["ratio_type"] == "global_account"
    assert account["long_ratio"] == "0.6"
    taker = asyncio.run(client.get_futures_long_short("BTCUSDT", "taker"))
    assert taker["ratio_type"] == "taker_buy_sell_volume"
    assert taker["long_short_ratio"] == "2.0"
    with pytest.raises(ValueError):
        asyncio.run(client.get_futures_long_short("BTCUSDT", "bogus"))


def test_ratios_persisted_with_types():
    db = _db()

    class _RatioClient:
        async def get_futures_long_short(self, symbol, kind, period="5m", limit=1):
            return {
                "symbol": symbol,
                "ratio_type": kind,
                "long_ratio": "0.6",
                "short_ratio": "0.4",
                "long_short_ratio": "1.5",
                "period": period,
                "timestamp": NOW,
                "source": "binance_futures",
            }

    result = asyncio.run(collect_futures_ratios(db, _RatioClient(), ["BTCUSDT"]))
    assert result["collected"] == 4
    assert db.query(FuturesMarketRatio).filter_by(ratio_type="taker").count() == 1


def test_all_tickers_client():
    def handler(request):
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "100",
                    "priceChange": "1",
                    "priceChangePercent": "1.0",
                    "highPrice": "101",
                    "lowPrice": "99",
                    "volume": "10",
                    "quoteVolume": "1000",
                    "openTime": 1762000000000,
                    "closeTime": 1762086400000,
                }
            ],
        )

    client = BinanceClient(
        "https://spot.example", "https://fapi.example", transport=httpx.MockTransport(handler)
    )
    tickers = asyncio.run(client.get_all_tickers_24hr())
    assert tickers[0]["symbol"] == "BTCUSDT"
    assert tickers[0]["price"] == "100"


def test_client_429_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"msg": "slow down"}, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "lastPrice": "100",
                "priceChange": "1",
                "priceChangePercent": "1.0",
                "highPrice": "101",
                "lowPrice": "99",
                "volume": "10",
                "quoteVolume": "1000",
                "openTime": 1762000000000,
                "closeTime": 1762086400000,
            },
        )

    client = BinanceClient(
        "https://spot.example", "https://fapi.example", transport=httpx.MockTransport(handler)
    )
    ticker = asyncio.run(client.get_ticker_24hr("BTCUSDT"))
    assert ticker["price"] == 100.0
    assert calls["n"] == 3


# News --------------------------------------------------------------------


def test_news_classification():
    assert classify_news("Binance Will List Foo (FOO)", "SPOT_LISTING") == "LISTINGS"
    assert classify_news("Binance to Delist Bar (BAR)", "DELISTING") == "DELISTINGS"
    assert classify_news("Bitcoin ETF sees record inflows", None) == "ETF"
    assert classify_news("Exchange hacked, funds stolen", None) == "HACKS"
    assert classify_news("Something entirely unrelated", None) == "OTHER"


def test_related_symbols_and_listing_token():
    assert "BTC" in extract_related_symbols("Binance Will List Foo (FOO) with BTCUSDT pair")
    name, symbol = extract_listing_token(
        "Binance Will List Predict (PREDICT) with Seed Tag Applied"
    )
    assert (name, symbol) == ("Predict", "PREDICT")
    assert extract_listing_token("No symbol here") == (None, None)


def test_news_processing_and_duplicate_prevention():
    db = _db()
    _announcement(db, "Binance Will List Foo (FOO)", "SPOT_LISTING", code="l1", external="e1")
    _announcement(db, "Binance to Delist Bar (BAR)", "DELISTING", code="d1", external="e2")
    first = process_news(db)
    assert first == {"found": 2, "created": 2, "skipped": 0}
    second = process_news(db)
    assert second["created"] == 0 and second["skipped"] == 2
    rows = db.query(CryptoNews).order_by(CryptoNews.id.asc()).all()
    assert rows[0].category == "LISTINGS"
    assert rows[0].summary is None
    assert rows[1].category == "DELISTINGS"
    assert "FOO" in rows[0].related_symbols


def test_news_fingerprint_stable():
    assert news_fingerprint("Hello  World", "https://x.example/a") == news_fingerprint(
        "hello world", "https://x.example/a"
    )
    assert news_fingerprint("Hello", "https://x.example/a") != news_fingerprint(
        "Hello", "https://x.example/b"
    )


def test_rss_parsing_and_collection():
    xml = """<rss version="2.0"><channel><item>
    <title>Bitcoin rallies</title><link>https://example.com/btc</link>
    <pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate>
    <description>Short summary</description></item>
    <item><title>No link here</title></item></channel></rss>"""
    items = parse_rss(xml)
    assert len(items) == 1
    assert items[0]["title"] == "Bitcoin rallies"
    db = _db()
    source = NewsSource(
        name="Example News", source_type="rss", feed_url="https://example.com/rss", enabled=True
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    result = collect_rss_items(db, source, items)
    assert result["created"] == 1
    again = collect_rss_items(db, source, items)
    assert again["created"] == 0 and again["skipped"] == 1
    row = db.query(CryptoNews).first()
    assert row.publisher == "Example News"
    assert row.summary == "Short summary"


def test_rss_malformed_returns_empty():
    assert parse_rss("not xml at all") == []


# API ---------------------------------------------------------------------


def test_market_api_overview_gainers_watchlist_alerts():
    db = _db()
    _snapshot(db, "BTCUSDT", "100", "5", "5000000")
    _snapshot(db, "ETHUSDT", "50", "-3", "4000000")
    db.add(MarketWatchlist(symbol="BTCUSDT", note="watch"))
    db.commit()
    client, old = _client_with_db(db)
    try:
        overview = client.get("/market/overview")
        assert overview.status_code == 200
        assert overview.json()["total"] == 2
        gainers = client.get("/market/gainers")
        assert gainers.json()["gainers"][0]["symbol"] == "BTCUSDT"
        assert isinstance(gainers.json()["gainers"][0]["price"], str)
        losers = client.get("/market/losers")
        assert losers.json()["losers"][0]["symbol"] == "ETHUSDT"
        one = client.get("/market/BTCUSDT")
        assert one.status_code == 200
        missing = client.get("/market/SOLUSDT")
        assert missing.status_code == 404
        bad = client.get("/market/bad symbol!")
        assert bad.status_code == 400
        watch = client.get("/market/watchlist")
        assert watch.json()["total"] == 1
        assert Decimal(watch.json()["items"][0]["price"]) == Decimal("100")
        history = client.get("/market/history?symbol=BTCUSDT")
        assert history.json()["total"] == 1
    finally:
        _restore(old)


def test_watchlist_crud_and_duplicate():
    db = _db()
    client, old = _client_with_db(db)
    try:
        created = client.post("/market/watchlist", json={"symbol": "btcusdt", "note": "main"})
        assert created.status_code == 200
        assert created.json()["symbol"] == "BTCUSDT"
        duplicate = client.post("/market/watchlist", json={"symbol": "BTCUSDT"})
        assert duplicate.json()["already_exists"] is True
        bad = client.post("/market/watchlist", json={"symbol": "bad!"})
        assert bad.status_code == 400
        watch_id = created.json()["id"]
        deleted = client.delete(f"/market/watchlist/{watch_id}")
        assert deleted.status_code == 200
        missing = client.delete("/market/watchlist/9999")
        assert missing.status_code == 404
    finally:
        _restore(old)


def test_news_api_filters_and_summary_marker():
    db = _db()
    _announcement(db, "Binance Will List Foo (FOO)", "SPOT_LISTING", code="l1", external="e1")
    _announcement(db, "Binance to Delist Bar (BAR)", "DELISTING", code="d1", external="e2")
    process_news(db)
    client, old = _client_with_db(db)
    try:
        listings = client.get("/news/listings")
        assert listings.json()["total"] == 1
        delistings = client.get("/news/delistings")
        assert delistings.json()["total"] == 1
        assert delistings.json()["items"][0]["summary"] == "Summary unavailable"
        assert delistings.json()["items"][0]["summary_available"] is False
        categories = client.get("/news/categories")
        assert categories.json()["counts"]["LISTINGS"] == 1
        bad = client.get("/news?category=BOGUS")
        assert bad.status_code == 400
        missing = client.get("/news/9999")
        assert missing.status_code == 404
        searched = client.get("/news?search=Foo")
        assert searched.json()["total"] == 1
    finally:
        _restore(old)


def test_market_collect_and_futures_collect_endpoints():
    db = _db()
    client, old = _client_with_db(db)
    try:
        # Live Binance is not required: with no network
        # mock, collection against the real client is
        # not asserted here; the endpoint contract is
        # covered by service tests and the DB-failure
        # test below. This test only checks routing
        # does not crash on a missing symbol list.
        response = client.post("/market/collect", json={"symbols": ["bad!"]})
        assert response.status_code == 400
    finally:
        _restore(old)


def test_db_failure_503():
    class _FailingQuery:
        def __init__(self, *a, **k):
            pass

        def count(self):
            raise OperationalError("select", {}, Exception("connection failed"))

        def order_by(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection failed"))

        def filter(self, *a, **k):
            return self

        def filter_by(self, *a, **k):
            return self

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
        assert client.get("/market/overview").status_code == 503
        assert client.get("/news").status_code == 503
    finally:
        if old is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old
        reset_rate_limits()


# Scheduler / Telegram / notifications ------------------------------------


def test_scheduler_idempotent_and_new_jobs():
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    for expected in (
        JOB_MARKET_SNAPSHOT,
        JOB_FUNDING,
        JOB_OPEN_INTEREST,
        JOB_NEWS,
        JOB_LISTINGS,
        JOB_MOVEMENT,
    ):
        assert expected in ids
    count_before = len(scheduler.get_jobs())
    register_jobs()
    assert len(scheduler.get_jobs()) == count_before
    for job in scheduler.get_jobs():
        if job.id in (
            JOB_MARKET_SNAPSHOT,
            JOB_FUNDING,
            JOB_OPEN_INTEREST,
            JOB_NEWS,
            JOB_LISTINGS,
            JOB_MOVEMENT,
        ):
            assert job.max_instances == 1


def test_telegram_formatting_and_disabled_notifications():
    from app.intelligence.notifications import record_notification

    db = _db()
    alert = MarketAlert(
        symbol="BTCUSDT",
        alert_type="price_up",
        threshold_percent=Decimal("5"),
        baseline_price=Decimal("100"),
        current_price=Decimal("107"),
        change_percent=Decimal("7"),
        triggered_at=NOW,
        status="triggered",
        source="binance_spot",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    text = format_market_alert_message(alert)
    assert "BTCUSDT" in text and "107" in text and "opportunity" not in text.lower()
    assert record_notification(db, "market_alert", alert.id, "market_alert") is True
    assert record_notification(db, "market_alert", alert.id, "market_alert") is False


def test_bot_commands():
    db = _db()
    _snapshot(db, "BTCUSDT", "100", "5", "5000000")
    _announcement(db, "Binance Will List Foo (FOO)", "SPOT_LISTING", code="l1", external="e1")
    process_news(db)

    class _FakeMessage:
        def __init__(self, text):
            self.text = text
            self.answers = []

        async def answer(self, text):
            self.answers.append(text)

    old_db_fn = bot_module._db
    bot_module._db = lambda: db
    try:
        market = _FakeMessage("/market")
        asyncio.run(market_handler(market))
        assert "BTCUSDT" in market.answers[0]
        price = _FakeMessage("/price BTC")
        asyncio.run(price_handler(price))
        assert "BTCUSDT" in price.answers[0]
        bad = _FakeMessage("/price bad!")
        asyncio.run(price_handler(bad))
        assert "Invalid symbol" in bad.answers[0]
        news = _FakeMessage("/news")
        asyncio.run(news_handler(news))
        assert "Foo" in news.answers[0]
    finally:
        bot_module._db = old_db_fn
