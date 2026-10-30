from fastapi.testclient import TestClient

from app.api.binance import get_binance_client
from app.binance.client import validate_symbol
from app.main import app


class FakeClient:
    async def spot_ping(self):
        return {}, 12.3, None

    async def futures_ping(self):
        return None, 10.1, "Service unavailable from a restricted location"

    async def get_price(self, symbol):
        symbol = validate_symbol(symbol)
        return {"symbol": symbol, "price": 77939.95, "source": "binance_spot"}

    async def get_ticker_24hr(self, symbol):
        from datetime import datetime, timezone

        return {
            "symbol": symbol, "price": 77939.95, "price_change_24h": -2033.0,
            "price_change_percent_24h": -2.542, "high_24h": 81971.0, "low_24h": 76500.0,
            "volume_24h": 30000.0, "quote_volume_24h": 2300000000.0,
            "open_time": datetime.now(timezone.utc), "close_time": datetime.now(timezone.utc),
            "source": "binance_spot",
        }

    async def get_klines(self, symbol, interval="1h", limit=100):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return [{"symbol": symbol, "interval": interval, "open_time": now, "open": 78000.0,
                 "high": 78200.0, "low": 77900.0, "close": 77939.95, "volume": 100.0,
                 "close_time": now, "quote_volume": 7800000.0, "trade_count": 100,
                 "source": "binance_spot"}]


app.dependency_overrides[get_binance_client] = lambda: FakeClient()
client = TestClient(app, raise_server_exceptions=False)


def test_status_endpoint_reports_each_integration():
    response = client.get("/binance/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["binance_spot"]["status"] == "ok"
    assert body["components"]["binance_futures"]["status"] == "unavailable"


def test_price_endpoint():
    response = client.get("/binance/price/BTCUSDT")
    assert response.status_code == 200
    assert response.json()["price"] == 77939.95


def test_ticker_endpoint():
    response = client.get("/binance/ticker/BTCUSDT")
    assert response.status_code == 200
    assert response.json()["symbol"] == "BTCUSDT"


def test_klines_endpoint():
    response = client.get("/binance/klines/BTCUSDT?interval=1h&limit=1")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["volume"] == 100.0


def test_invalid_symbol_returns_400():
    response = client.get("/binance/price/BAD%20SYMBOL")
    assert response.status_code == 400
