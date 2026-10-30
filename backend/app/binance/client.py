"""Binance public market-data clients (Spot and Futures).

Only public, read-only endpoints are used, so no API key or secret is
required. Both clients share retry and error handling: transient
failures (network errors, HTTP 429, and HTTP 5xx) are retried with
exponential backoff, while other client errors are reported
immediately. A restricted-location response from Binance (code 0)
is surfaced as a BinanceAPIError, never hidden or replaced with
estimated data.
"""

import asyncio
import logging
import os
import re
import ssl
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,20}$")


def validate_symbol(symbol: str) -> str:
    """Normalise and validate a trading symbol, for example BTCUSDT."""
    normalised = symbol.strip().upper()
    if not _SYMBOL_RE.match(normalised):
        raise ValueError(f"Invalid trading symbol: {symbol!r}")
    return normalised


def _utc_from_ms(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000, tz=timezone.utc)


class BinanceAPIError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class BinanceClient:
    def __init__(
        self,
        spot_base_url: str,
        futures_base_url: str,
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ):
        self.spot_base_url = spot_base_url.rstrip("/")
        self.futures_base_url = futures_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)
        self._transport = transport
        # Use an explicit proxy URL only, never ambient proxy parsing:
        # httpx's trust_env parsing of NO_PROXY entries such as
        # "[::1]" fails in some environments, while the proxy URL
        # itself works. When no proxy is configured, connect directly.
        self.proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
        # With trust_env disabled, httpx would also ignore the
        # environment CA bundle, which egress proxies rely on, so
        # load it explicitly when it is present.
        ca_bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        if ca_bundle and os.path.exists(ca_bundle):
            context = ssl.create_default_context(cafile=ca_bundle)
        else:
            context = ssl.create_default_context()
        self._ssl_context = context

    async def _request(self, base_url: str, path: str, params: dict | None = None):
        """GET with retries for transient failures only."""
        last_error: Exception | None = None
        last_status: int | None = None
        last_message: str | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # A test transport replaces the network entirely, so
                # proxy and TLS settings must not override it.
                client_kwargs: dict = {
                    "base_url": base_url,
                    "timeout": self.timeout_seconds,
                    "transport": self._transport,
                }
                if self._transport is None:
                    client_kwargs.update(
                        {"proxy": self.proxy, "trust_env": False, "verify": self._ssl_context}
                    )
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.get(path, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    last_status = response.status_code
                    try:
                        body = response.json()
                        last_message = body.get("msg") if isinstance(body, dict) else None
                    except ValueError:
                        last_message = None
                    logger.warning(
                        "Binance %s returned %s, retry %s/%s",
                        path,
                        response.status_code,
                        attempt,
                        self.max_retries,
                    )
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = (
                                float(retry_after) if retry_after else 0.5 * (2 ** (attempt - 1))
                            )
                        except (TypeError, ValueError):
                            delay = 0.5 * (2 ** (attempt - 1))
                        await asyncio.sleep(delay)
                    continue
                if response.status_code >= 400:
                    body = {}
                    try:
                        parsed = response.json()
                        body = parsed if isinstance(parsed, dict) else {}
                    except ValueError:
                        pass
                    raise BinanceAPIError(
                        body.get(
                            "msg", f"Binance request failed with status {response.status_code}"
                        ),
                        status=response.status_code,
                        code=body.get("code"),
                    )
                return response.json()
            except BinanceAPIError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Binance %s transport error, retry %s/%s: %s",
                        path,
                        attempt,
                        self.max_retries,
                        exc,
                    )
                    await asyncio.sleep(delay)
        if last_status is not None:
            message = last_message or (
                f"Binance request failed with status {last_status} "
                f"after {self.max_retries} attempts"
            )
            raise BinanceAPIError(message, status=last_status)
        raise BinanceAPIError(
            f"Binance request failed after {self.max_retries} attempts: {last_error}"
        )

    async def _timed(self, base_url: str, path: str, params: dict | None = None):
        started = time.monotonic()
        try:
            data = await self._request(base_url, path, params)
            return data, round((time.monotonic() - started) * 1000, 1), None
        except BinanceAPIError as exc:
            return None, round((time.monotonic() - started) * 1000, 1), str(exc)

    # Spot ---------------------------------------------------------------

    async def spot_ping(self):
        return await self._timed(self.spot_base_url, "/api/v3/ping")

    async def get_price(self, symbol: str) -> dict:
        symbol = validate_symbol(symbol)
        data = await self._request(self.spot_base_url, "/api/v3/ticker/price", {"symbol": symbol})
        return {"symbol": data["symbol"], "price": float(data["price"]), "source": "binance_spot"}

    async def get_ticker_24hr(self, symbol: str) -> dict:
        symbol = validate_symbol(symbol)
        data = await self._request(self.spot_base_url, "/api/v3/ticker/24hr", {"symbol": symbol})
        return {
            "symbol": data["symbol"],
            "price": float(data["lastPrice"]),
            "price_change_24h": float(data["priceChange"]),
            "price_change_percent_24h": float(data["priceChangePercent"]),
            "high_24h": float(data["highPrice"]),
            "low_24h": float(data["lowPrice"]),
            "volume_24h": float(data["volume"]),
            "quote_volume_24h": float(data["quoteVolume"]),
            "open_time": _utc_from_ms(int(data["openTime"])),
            "close_time": _utc_from_ms(int(data["closeTime"])),
            "source": "binance_spot",
        }

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
        symbol = validate_symbol(symbol)
        if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"):
            raise ValueError(f"Unsupported kline interval: {interval!r}")
        limit = max(1, min(limit, 1000))
        rows = await self._request(
            self.spot_base_url,
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )
        klines = []
        for row in rows:
            klines.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "open_time": _utc_from_ms(int(row[0])),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": _utc_from_ms(int(row[6])),
                    "quote_volume": float(row[7]),
                    "trade_count": int(row[8]),
                    "source": "binance_spot",
                }
            )
        return klines

    # Futures ------------------------------------------------------------

    async def futures_ping(self):
        return await self._timed(self.futures_base_url, "/fapi/v1/ping")

    async def get_funding_rate(self, symbol: str, limit: int = 1) -> dict:
        symbol = validate_symbol(symbol)
        rows = await self._request(
            self.futures_base_url,
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": max(1, min(limit, 100))},
        )
        if not rows:
            raise BinanceAPIError(f"No funding rate data returned for {symbol}")
        # Do not assume the response order: pick the row with the
        # latest funding time, so the result is correct regardless
        # of whether the endpoint returns newest-first or oldest-first.
        latest = max(rows, key=lambda row: int(row["fundingTime"]))
        return {
            "symbol": latest["symbol"],
            "funding_rate": float(latest["fundingRate"]),
            "funding_time": _utc_from_ms(int(latest["fundingTime"])),
            "source": "binance_futures",
        }

    async def get_premium_index(self, symbol: str) -> dict:
        symbol = validate_symbol(symbol)
        data = await self._request(
            self.futures_base_url, "/fapi/v1/premiumIndex", {"symbol": symbol}
        )
        return {
            "symbol": data["symbol"],
            "mark_price": float(data["markPrice"]),
            "funding_rate": float(data["lastFundingRate"]),
            "next_funding_time": _utc_from_ms(int(data["nextFundingTime"])),
            "source": "binance_futures",
        }

    async def get_open_interest(self, symbol: str) -> dict:
        symbol = validate_symbol(symbol)
        data = await self._request(
            self.futures_base_url, "/fapi/v1/openInterest", {"symbol": symbol}
        )
        return {
            "symbol": data["symbol"],
            "open_interest": float(data["openInterest"]),
            "time": _utc_from_ms(int(data["time"])),
            "source": "binance_futures",
        }
