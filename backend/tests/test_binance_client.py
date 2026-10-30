import os

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("BINANCE_SPOT_BASE_URL", "https://data-api.binance.vision")
os.environ.setdefault("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com")

from app.binance.client import BinanceAPIError, BinanceClient, validate_symbol  # noqa: E402
from app.binance.service import collect_market_snapshots  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import MarketSnapshot  # noqa: E402


def test_validate_symbol():
    assert validate_symbol("btcusdt") == "BTCUSDT"
    with pytest.raises(ValueError):
        validate_symbol("BTC USDT")


def test_kline_parsing_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        return httpx.Response(
            200,
            json=[
                [1793347200000, "78186.0", "78241.3", "77911.0", "77939.95", "1077.88",
                 1793350799999, "84117826.88", 124783, "447.9", "34958282.18", "0"]
            ],
        )

    async def run():
        client = BinanceClient(
            "https://data-api.binance.vision", "https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        return await client.get_klines("BTCUSDT", interval="1h", limit=1)

    import asyncio

    rows = asyncio.run(run())
    assert len(rows) == 1
    assert rows[0]["close"] == 77939.95
    assert rows[0]["volume"] == 1077.88
    assert rows[0]["trade_count"] == 124783


def test_restricted_location_error_is_surfaced():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            451,
            json={"code": 0, "msg": "Service unavailable from a restricted location"},
        )

    async def run():
        client = BinanceClient(
            "https://api.binance.com", "https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(BinanceAPIError) as exc_info:
            await client.get_price("BTCUSDT")
        assert exc_info.value.code == 0
        assert "restricted location" in str(exc_info.value)

    import asyncio

    asyncio.run(run())


def test_binance_error_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    async def run():
        client = BinanceClient(
            "https://data-api.binance.vision", "https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(BinanceAPIError) as exc_info:
            await client.get_price("INVALID")
        assert exc_info.value.code == -1121

    import asyncio

    asyncio.run(run())


def test_collect_market_snapshots_persists_to_sqlite():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[MarketSnapshot.__table__])
    Session = sessionmaker(bind=engine)
    db = Session()

    class FakeClient:
        async def get_ticker_24hr(self, symbol):
            return {
                "symbol": symbol, "price": 100.0, "price_change_24h": 1.0,
                "price_change_percent_24h": 1.0, "high_24h": 101.0, "low_24h": 99.0,
                "volume_24h": 123.0, "quote_volume_24h": 12300.0, "source": "binance_spot",
            }

    import asyncio

    snapshots = asyncio.run(collect_market_snapshots(db, FakeClient(), ["BTCUSDT"]))
    assert len(snapshots) == 1
    assert db.query(MarketSnapshot).count() == 1
    assert db.query(MarketSnapshot).first().price == 100.0
