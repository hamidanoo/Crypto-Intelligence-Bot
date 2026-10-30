import asyncio
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.binance import get_binance_client
from app.binance.client import BinanceAPIError, BinanceClient
from app.binance.service import collect_market_snapshots
from app.cache import cache_get, cache_set, clear_memory_cache
from app.config import Settings
from app.database import Base
from app.main import app
from app.models import MarketSnapshot
from app.rate_limit import check_rate_limit, reset_rate_limits
from app.scheduler import scheduler, shutdown_scheduler, start_scheduler


def test_production_secret_validation():
    with pytest.raises(ValueError):
        Settings(environment="production", secret_key="change-me-in-production")
    # Phase 8: production also requires a credential
    # encryption key. The test key below is a dummy
    # 32-byte value used only for this validation test.
    import base64

    test_key = base64.b64encode(b"\x00" * 32).decode("ascii")
    settings = Settings(
        environment="production",
        secret_key="a-real-secret-value",
        credential_encryption_key=test_key,
    )
    assert settings.secret_key == "a-real-secret-value"
    with pytest.raises(ValueError):
        Settings(environment="production", secret_key="a-real-secret-value")


def test_scheduler_lifecycle():
    async def run():
        start_scheduler()
        assert scheduler.running
        shutdown_scheduler()
        await asyncio.sleep(0.1)
        assert not scheduler.running
        shutdown_scheduler()

    asyncio.run(run())


def test_scheduler_starts_and_stops_with_api_lifespan():
    reset_rate_limits()
    with TestClient(app) as client:
        assert scheduler.running
        response = client.get("/health")
        assert response.status_code == 200
    assert not scheduler.running


def test_funding_rate_picks_latest_by_time():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": 1700000000000},
                {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingTime": 1700028800000},
            ],
        )

    async def run():
        client = BinanceClient(
            "https://example.invalid",
            "https://example.invalid",
            transport=httpx.MockTransport(handler),
        )
        return await client.get_funding_rate("BTCUSDT")

    result = asyncio.run(run())
    assert result["funding_rate"] == 0.0002


def test_retry_after_non_numeric_and_final_429_error():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            429,
            json={"code": -1003, "msg": "Too many requests"},
            headers={"Retry-After": "not-a-number"},
        )

    async def run():
        client = BinanceClient(
            "https://example.invalid",
            "https://example.invalid",
            transport=httpx.MockTransport(handler),
            max_retries=2,
        )
        with pytest.raises(BinanceAPIError) as exc_info:
            await client.get_price("BTCUSDT")
        assert exc_info.value.status == 429
        assert "Too many requests" in str(exc_info.value)

    asyncio.run(run())
    assert calls["count"] == 2


def test_retry_succeeds_after_429():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"code": -1003, "msg": "Too many requests"})
        return httpx.Response(200, json={"symbol": "BTCUSDT", "price": "100.0"})

    async def run():
        client = BinanceClient(
            "https://example.invalid",
            "https://example.invalid",
            transport=httpx.MockTransport(handler),
        )
        return await client.get_price("BTCUSDT")

    result = asyncio.run(run())
    assert result["price"] == 100.0
    assert calls["count"] == 2


def test_decimal_snapshot_storage():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    class FakeClient:
        async def get_ticker_24hr(self, symbol):
            return {
                "symbol": symbol,
                "price": 0.123456789,
                "price_change_24h": 0.01,
                "price_change_percent_24h": 1.0,
                "high_24h": 0.2,
                "low_24h": 0.1,
                "volume_24h": 123.456,
                "quote_volume_24h": 1234.5,
                "source": "binance_spot",
            }

    snapshots = asyncio.run(collect_market_snapshots(db, FakeClient(), ["BTCUSDT"]))
    assert isinstance(snapshots[0].price, Decimal)
    assert db.query(MarketSnapshot).first().price == Decimal("0.12345679")


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


def test_cache_fallback_when_redis_unavailable():
    clear_memory_cache()
    asyncio.run(cache_set("test:key", {"price": 1.5}, ttl_seconds=60))
    value = asyncio.run(cache_get("test:key"))
    assert value == {"price": 1.5}
    clear_memory_cache()


def test_rate_limit_blocks_after_limit():
    reset_rate_limits()

    class FakeRequest:
        class client:
            host = "rate-test-client"

    request = FakeRequest()
    check_rate_limit(request, limit=2)
    check_rate_limit(request, limit=2)
    with pytest.raises(Exception) as exc_info:
        check_rate_limit(request, limit=2)
    assert exc_info.value.status_code == 429
    reset_rate_limits()


def test_collect_endpoint_accepts_json_body_and_rejects_too_many_symbols():
    from app.binance.service import collect_market_snapshots as _collect
    from app.database import get_db

    class FakeClient:
        async def get_ticker_24hr(self, symbol):
            return {
                "symbol": symbol,
                "price": 100.0,
                "price_change_24h": 1.0,
                "price_change_percent_24h": 1.0,
                "high_24h": 101.0,
                "low_24h": 99.0,
                "volume_24h": 10.0,
                "quote_volume_24h": 1000.0,
                "source": "binance_spot",
            }

    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    with pytest.raises(ValueError):
        asyncio.run(_collect(db, FakeClient(), [f"SYM{i}" for i in range(21)]))

    def _override_db():
        yield db

    old_client = app.dependency_overrides.get(get_binance_client)
    old_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_binance_client] = lambda: FakeClient()
    app.dependency_overrides[get_db] = _override_db
    try:
        reset_rate_limits()
        client = TestClient(app, raise_server_exceptions=False)
        headers = _auth(client, db)
        response = client.post(
            "/binance/collect/market", json={"symbols": ["BTCUSDT"]}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["collected"] == 1
    finally:
        if old_client is None:
            app.dependency_overrides.pop(get_binance_client, None)
        else:
            app.dependency_overrides[get_binance_client] = old_client
        if old_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_db
        reset_rate_limits()
