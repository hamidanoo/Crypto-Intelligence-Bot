"""Phase 9 tests: audit fixes, cross-module integration,
scheduler reliability, security re-audit, and Telegram
command coverage.

Mock tests only for the core suite: every test uses an
in-memory database and mocked external clients. Nothing
here depends on live Binance, live Telegram, live
PostgreSQL, or Docker, and nothing here claims a live
integration. Live smoke results are reported separately
in docs/PHASE_09_AUDIT_REPORT.md.
"""

import asyncio
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import reset_login_rate_limits
from app.auth.encryption import (
    CredentialEncryptionError,
    decrypt_secret,
    encrypt_secret,
)
from app.auth.passwords import hash_password
from app.auth.permissions import PERMISSIONS, ROLE_PERMISSIONS
from app.auth.ssrf import SSRFBlockedError, fetch_feed
from app.config import Settings, settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminSession,
    AdminUser,
    AdminUserRole,
    Announcement,
    AnnouncementSource,
    AuditLog,
    Competition,
    CompetitionTradingPair,
    CompetitionVolumeInterval,
    CryptoNews,
    MarketSnapshot,
    NewsSource,
    PasswordResetToken,
    SystemSetting,
)
from app.rate_limit import reset_rate_limits

TEST_KEY = base64.b64encode(b"A" * 32).decode("ascii")
TEST_KEY_2 = base64.b64encode(b"B" * 32).decode("ascii")
UTC = timezone.utc


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _session(engine):
    return sessionmaker(bind=engine)()


def _seed_roles(db):
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
    return roles


def _create_user(db, username, role, password="Secret123!"):
    roles = _seed_roles(db)
    user = AdminUser(
        username=username,
        email=f"{username}@example.invalid",
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        is_superuser=(role == "super_admin"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(AdminUserRole(admin_user_id=user.id, role_id=roles[role]))
    db.commit()
    return user


def _client_with_db(db):
    def _override_db():
        yield db

    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    reset_rate_limits()
    reset_login_rate_limits()
    return TestClient(app, raise_server_exceptions=False), old


def _restore(old):
    if old is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = old
    reset_rate_limits()
    reset_login_rate_limits()


def _login(client, username, password="Secret123!"):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.cookies.get("admin_csrf")}


def _setup(role="super_admin", username="admin9"):
    engine = _engine()
    db = _session(engine)
    _create_user(db, username, role)
    client, old = _client_with_db(db)
    return db, client, old


def _announcement(db, title, category, code, external, source=None):
    from app.announcements.service import ensure_default_source

    if source is None:
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
        published_at=datetime(2026, 10, 30, tzinfo=UTC),
        collected_at=datetime(2026, 10, 30, tzinfo=UTC),
        content_hash=f"hash-{code}",
        verification_status="official_website",
        metadata_json={},
        notification_status="disabled",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------- CORS / security headers


def test_cors_allows_csrf_header():
    db, client, old = _setup()
    try:
        response = client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Token",
            },
        )
        allowed = response.headers.get("access-control-allow-headers", "")
        assert "x-csrf-token" in allowed.lower()
        # Security headers ride on real responses; a CORS
        # preflight response does not carry them.
        health = client.get("/health")
        assert health.headers.get("x-content-type-options") == "nosniff"
        assert health.headers.get("x-frame-options") == "DENY"
    finally:
        _restore(old)


# ------------------------------------------------------- announcement scheduler (naive datetime)


def test_announcement_job_handles_naive_last_success():
    import app.announcements.scheduler_job as job_module

    engine = _engine()
    db = _session(engine)
    source = AnnouncementSource(
        name="Binance Announcements",
        source_type="binance_website_cms",
        base_url="https://www.binance.com",
        enabled=True,
        polling_interval_seconds=3600,
        configuration={},
        # SQLite returns naive datetimes; this is exactly
        # the value a reloaded source carried before the
        # Phase 9 fix, which raised TypeError here.
        last_success_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(source)
    db.commit()
    old_session_local = job_module.SessionLocal
    job_module.SessionLocal = lambda: _session(engine)
    try:
        summary = asyncio.run(job_module.collect_all_announcements())
    finally:
        job_module.SessionLocal = old_session_local
    assert summary["failed"] == 0
    assert summary["runs"] == 0  # source not due yet: skipped, not failed


# ------------------------------------------------------- scheduler paused restore + idempotence


def test_scheduler_register_twice_and_paused_restore():
    import app.database as database_module
    from app.scheduler import register_jobs, scheduler

    engine = _engine()
    db = _session(engine)
    db.add(
        SystemSetting(
            key="scheduler_jobs",
            value={"market_snapshot": {"enabled": False}},
            description="test",
        )
    )
    db.commit()
    old_session_local = database_module.SessionLocal
    database_module.SessionLocal = lambda: _session(engine)
    try:
        register_jobs()
        before = {job.id for job in scheduler.get_jobs()}
        assert "market_snapshot" in before
        assert scheduler.get_job("market_snapshot").next_run_time is None
        register_jobs()
        after = {job.id for job in scheduler.get_jobs()}
        assert before == after
    finally:
        database_module.SessionLocal = old_session_local
        try:
            scheduler.resume_job("market_snapshot")
        except Exception:
            pass


# ---------------------------------------------------------------- password reset hardening


def test_password_reset_revokes_sessions_and_sibling_tokens():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin9")
        user = db.query(AdminUser).filter(AdminUser.username == "admin9").first()
        assert db.query(AdminSession).filter(AdminSession.revoked_at.is_(None)).count() == 1
        now = datetime.now(timezone.utc)
        good = PasswordResetToken(
            admin_user_id=user.id,
            token_hash=hashlib.sha256(b"good-token").hexdigest(),
            expires_at=now + timedelta(minutes=60),
        )
        sibling = PasswordResetToken(
            admin_user_id=user.id,
            token_hash=hashlib.sha256(b"sibling-token").hexdigest(),
            expires_at=now + timedelta(minutes=60),
        )
        db.add_all([good, sibling])
        db.commit()
        response = client.post(
            "/auth/reset-password",
            json={"token": "good-token", "new_password": "NewSecret123!"},
        )
        assert response.status_code == 200, response.text
        assert db.query(AdminSession).filter(AdminSession.revoked_at.is_(None)).count() == 0
        sibling_after = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == hashlib.sha256(b"sibling-token").hexdigest())
            .first()
        )
        assert sibling_after.used_at is not None
        # The old session cookie no longer authenticates.
        me = client.get("/auth/me")
        assert me.status_code == 401
        # New password works.
        _login(client, "admin9", password="NewSecret123!")
        assert headers  # login helper exercised; session is fresh
    finally:
        _restore(old)


def test_forgot_password_invalidates_siblings_and_audits():
    db, client, old = _setup()
    try:
        user = db.query(AdminUser).filter(AdminUser.username == "admin9").first()
        now = datetime.now(timezone.utc)
        stale = PasswordResetToken(
            admin_user_id=user.id,
            token_hash=hashlib.sha256(b"stale-token").hexdigest(),
            expires_at=now + timedelta(minutes=60),
        )
        db.add(stale)
        db.commit()
        response = client.post("/auth/forgot-password", json={"username_or_email": "admin9"})
        assert response.status_code == 200
        stale_after = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == hashlib.sha256(b"stale-token").hexdigest())
            .first()
        )
        assert stale_after.used_at is not None
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "password.reset.requested")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.admin_user_id == user.id
    finally:
        _restore(old)


def test_locked_account_gets_generic_message():
    db, client, old = _setup()
    try:
        user = db.query(AdminUser).filter(AdminUser.username == "admin9").first()
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.commit()
        response = client.post("/auth/login", json={"username": "admin9", "password": "Secret123!"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"
    finally:
        _restore(old)


# ---------------------------------------------------------------- encryption key versioning


def test_encryption_rotation_with_stable_key_ids():
    old_key = settings.credential_encryption_key
    old_previous = settings.credential_encryption_key_previous
    old_id = settings.credential_encryption_key_id
    old_previous_id = settings.credential_encryption_key_previous_id
    try:
        settings.credential_encryption_key = TEST_KEY
        settings.credential_encryption_key_previous = None
        settings.credential_encryption_key_id = "v1"
        settings.credential_encryption_key_previous_id = None
        blob = encrypt_secret("top-secret-value")
        assert blob["key_id"] == "v1"
        # Rotate: new key becomes current (v2), old key
        # becomes previous under its stable id (v1).
        settings.credential_encryption_key = TEST_KEY_2
        settings.credential_encryption_key_previous = TEST_KEY
        settings.credential_encryption_key_id = "v2"
        settings.credential_encryption_key_previous_id = "v1"
        assert decrypt_secret(blob["ciphertext_b64"], blob["nonce_b64"], blob["key_id"]) == (
            "top-secret-value"
        )
        # Legacy rows written as "current" still decrypt
        # against the current key.
        legacy = encrypt_secret("legacy-value")
        assert (
            decrypt_secret(legacy["ciphertext_b64"], legacy["nonce_b64"], "current")
            == "legacy-value"
        )
        # Unknown key ids must error, never silently
        # fall back to the current key.
        with pytest.raises(CredentialEncryptionError):
            decrypt_secret(blob["ciphertext_b64"], blob["nonce_b64"], "no-such-key")
    finally:
        settings.credential_encryption_key = old_key
        settings.credential_encryption_key_previous = old_previous
        settings.credential_encryption_key_id = old_id
        settings.credential_encryption_key_previous_id = old_previous_id


def test_config_rejects_malformed_encryption_key():
    with pytest.raises(Exception):
        Settings(credential_encryption_key="not-valid-base64!!!")


# ---------------------------------------------------------------- binance status side-effect free


def test_binance_status_writes_nothing():
    from app.api.binance import get_binance_client
    from app.models import ApiIntegration

    class _FakeClient:
        async def spot_ping(self):
            return ({}, 1, None)

        async def futures_ping(self):
            return ({}, 2, None)

    db, client, old = _setup()
    try:
        app.dependency_overrides[get_binance_client] = lambda: _FakeClient()
        response = client.get("/binance/status")
        assert response.status_code == 200, response.text
        assert response.json()["components"]["binance_spot"]["status"] == "ok"
        assert db.query(ApiIntegration).count() == 0
    finally:
        app.dependency_overrides.pop(get_binance_client, None)
        _restore(old)


# ------------------------------------------------------- admin PATCH uniqueness + custom roles


def test_patch_user_duplicate_email_is_400_not_500():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin9")
        _create_user(db, "second9", "viewer")
        second = db.query(AdminUser).filter(AdminUser.username == "second9").first()
        response = client.patch(
            f"/admin/users/{second.id}",
            json={"email": "admin9@example.invalid"},
            headers=headers,
        )
        assert response.status_code == 400, response.text
        assert "already exists" in response.json()["detail"]
    finally:
        _restore(old)


def test_custom_role_can_be_assigned():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin9")
        created = client.post(
            "/admin/roles",
            json={"name": "auditor9", "permissions": ["dashboard.view", "audit.view"]},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        _create_user(db, "auditee9", "viewer")
        target = db.query(AdminUser).filter(AdminUser.username == "auditee9").first()
        patched = client.patch(
            f"/admin/users/{target.id}", json={"role": "auditor9"}, headers=headers
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["role"] == "auditor9"
        assert "audit.view" in patched.json()["permissions"]
    finally:
        _restore(old)


# ---------------------------------------------------------------- SSRF


def test_ssrf_blocks_loopback_and_caps_body():
    import app.auth.ssrf as ssrf_module

    with pytest.raises(SSRFBlockedError):
        fetch_feed("http://127.0.0.1/feed.xml")

    class _FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_bytes(self, chunk_size):
            yield b"x" * (ssrf_module.MAX_BODY_BYTES + 1)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url, headers=None):
            return _FakeResponse()

    old_client = ssrf_module.httpx.Client
    ssrf_module.httpx.Client = _FakeClient
    try:
        with pytest.raises(SSRFBlockedError):
            fetch_feed("https://example.com/feed.xml")
    finally:
        ssrf_module.httpx.Client = old_client


def test_scheduler_rss_uses_ssrf_fetcher():
    import app.marketintel.scheduler_jobs as jobs_module
    from app.marketintel.service import collect_rss_items, parse_rss  # noqa: F401

    engine = _engine()
    db = _session(engine)
    source = NewsSource(
        name="Loopback Feed",
        source_type="rss",
        feed_url="http://127.0.0.1/feed.xml",
        enabled=True,
        reliability_note="test",
    )
    db.add(source)
    db.commit()
    calls = []

    def _fake_fetch(url):
        calls.append(url)
        return {
            "status": 200,
            "text": (
                '<?xml version="1.0"?><rss version="2.0"><channel>'
                "<item><title>Test story</title>"
                "<link>https://example.com/story-1</link>"
                "<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>"
                "</item></channel></rss>"
            ),
            "final_url": url,
        }

    old_fetch = jobs_module.fetch_feed
    jobs_module.fetch_feed = _fake_fetch
    old_session_local = jobs_module.SessionLocal
    jobs_module.SessionLocal = lambda: _session(engine)
    try:
        result = asyncio.run(jobs_module.process_news_job())
    finally:
        jobs_module.fetch_feed = old_fetch
        jobs_module.SessionLocal = old_session_local
    assert calls == ["http://127.0.0.1/feed.xml"]
    assert result.get("rss_created", 0) >= 1


# ---------------------------------------------------------------- cross-module integration


def test_cross_module_pipeline_and_duplicates():
    import asyncio as _asyncio

    from app.competitions.processing import process_competitions
    from app.intelligence.processing import (
        process_airdrops,
        process_alpha,
        process_prime_sales,
    )
    from app.marketintel.service import process_news

    class _FakeMarket:
        async def get_price(self, symbol):
            return {"price": "100"}

        async def get_ticker_24hr(self, symbol):
            return {
                "price": "100",
                "price_change_24h": "1",
                "price_change_percent_24h": "1",
                "high_24h": "101",
                "low_24h": "99",
                "volume_24h": "1000",
                "quote_volume_24h": "100000",
                "source": "binance_spot",
            }

    engine = _engine()
    db = _session(engine)
    _announcement(db, "Binance Alpha Adds TestCoin (TEST)", "ALPHA", "a1", "ext-a1")
    _announcement(
        db, "Binance Airdrop: TestCoin for Alpha points holders", "AIRDROP", "a2", "ext-a2"
    )
    _announcement(
        db, "Binance Prime Sale: TestCoin subscription is now open", "PRIME_SALE", "a3", "ext-a3"
    )
    _announcement(db, "Binance Alpha Trading Competition: Axis Robotics", "ALPHA", "a4", "ext-a4")
    _announcement(db, "Binance Will List Foo (FOO)", "SPOT_LISTING", "a5", "ext-a5")

    _asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    airdrops = process_airdrops(db)
    primes = process_prime_sales(db)
    competitions = process_competitions(db)
    news = process_news(db)

    from app.models import (
        AlphaToken,
        AirdropCampaign,
        PrimeSale,
    )

    assert db.query(AlphaToken).count() == 2  # token + competition-titled alpha record
    assert airdrops["created"] == 1
    assert primes["created"] == 1
    assert competitions["created"] >= 1
    assert news["created"] == 5
    # Source references are preserved on every record.
    for row in db.query(AlphaToken).all():
        assert row.announcement_id is not None
    assert db.query(AirdropCampaign).first().announcement_id is not None
    assert db.query(PrimeSale).first().announcement_id is not None
    assert db.query(Competition).first().announcement_id is not None
    # Second run: everything is a duplicate, nothing new.
    _asyncio.run(process_alpha(db, market_client=_FakeMarket()))
    assert process_airdrops(db)["created"] == 0
    assert process_prime_sales(db)["created"] == 0
    assert process_competitions(db)["created"] == 0
    assert process_news(db)["created"] == 0
    assert db.query(CryptoNews).count() == 5


def test_intelligence_processing_commits_once_per_entity():
    from app.intelligence.processing import process_prime_sales

    engine = _engine()
    db = _session(engine)
    _announcement(
        db, "Binance Prime Sale: One subscription is now open", "PRIME_SALE", "p1", "ext-p1"
    )
    _announcement(
        db, "Binance Prime Sale: Two subscription is now open", "PRIME_SALE", "p2", "ext-p2"
    )
    commits = []
    event.listen(db, "after_commit", lambda session: commits.append(1))
    process_prime_sales(db)
    # One commit per sale (parent + allocation rule
    # together), not two commits per sale as before.
    assert len(commits) == 2


def test_latest_snapshots_do_not_load_every_row():
    from app.marketintel.service import latest_snapshots_by_symbol

    engine = _engine()
    db = _session(engine)
    for i in range(5):
        db.add(
            MarketSnapshot(
                symbol="BTCUSDT",
                source="binance_spot",
                price=100 + i,
                collected_at=datetime(2026, 10, 30, 10, i, tzinfo=UTC),
            )
        )
    for i in range(3):
        db.add(
            MarketSnapshot(
                symbol="ETHUSDT",
                source="binance_spot",
                price=10 + i,
                collected_at=datetime(2026, 10, 30, 10, i, tzinfo=UTC),
            )
        )
    db.commit()
    latest = latest_snapshots_by_symbol(db)
    assert set(latest) == {"BTCUSDT", "ETHUSDT"}
    assert latest["BTCUSDT"].price == 104
    assert latest["ETHUSDT"].price == 12


def test_volume_pair_failure_does_not_stop_other_pairs():
    import asyncio as _asyncio

    import app.volume.collection as collection_module
    from app.volume.collection import collect_one_competition

    engine = _engine()
    db = _session(engine)
    source_announcement = _announcement(
        db, "Binance Alpha Trading Competition: Vol Test", "ALPHA", "v1", "ext-v1"
    )
    competition = Competition(
        announcement_id=source_announcement.id,
        competition_name="Vol Test",
        competition_type="SPOT",
        official_url="https://example.com/vol",
        status="ACTIVE",
        start_time=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        source="binance_website_cms",
        verification_status="official_website",
    )
    db.add(competition)
    db.commit()
    db.refresh(competition)
    for pair in ("BTCUSDT", "ETHUSDT"):
        db.add(
            CompetitionTradingPair(
                competition_id=competition.id, pair=pair, base_asset=pair[:-4], quote_asset="USDT"
            )
        )
    db.commit()

    async def _fake_collect(db, client, comp, pair_row, start, end, max_pages=50):
        if pair_row.pair == "ETHUSDT":
            raise RuntimeError("simulated pair failure")
        return "created", 123

    old_collect = collection_module.collect_interval
    collection_module.collect_interval = _fake_collect
    try:
        result = _asyncio.run(
            collect_one_competition(
                db,
                object(),
                competition,
                datetime(2026, 10, 30, 10, 31, tzinfo=UTC),
            )
        )
    finally:
        collection_module.collect_interval = old_collect
    assert result["errors"], "failing pair must be recorded"
    assert result["found"] > 0
    # The session is still usable after the failure
    # (rollback in the per-pair handler): querying works.
    assert db.query(CompetitionVolumeInterval).count() >= 0


def test_news_categories_aggregate_in_sql():
    db, client, old = _setup()
    try:
        _announcement(db, "Binance Will List Foo (FOO)", "SPOT_LISTING", "n1", "ext-n1")
        from app.marketintel.service import process_news

        process_news(db)
        response = client.get("/news/categories")
        assert response.status_code == 200, response.text
        assert response.json()["counts"].get("LISTINGS", 0) >= 1
    finally:
        _restore(old)


def test_scheduler_trigger_rejects_paused_job():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin9")
        from app.api.admin_common import set_setting

        set_setting(db, "scheduler_jobs", {"market_snapshot": {"enabled": False}}, "test")
        response = client.post("/admin/scheduler/market_snapshot/trigger", headers=headers)
        assert response.status_code == 400, response.text
        assert "paused" in response.json()["detail"]
    finally:
        _restore(old)


# ---------------------------------------------------------------- Telegram commands (all)


def test_all_bot_commands_answer():
    import app.bot as bot_module
    from app.bot import (
        airdrop_handler,
        airdrops_handler,
        alerts_handler,
        alpha_handler,
        competition_handler,
        delistings_handler,
        funding_handler,
        gainers_handler,
        help_handler,
        listings_handler,
        longshort_handler,
        losers_handler,
        market_handler,
        marketalerts_handler,
        news_handler,
        open_interest_handler,
        price_handler,
        prime_handler,
        start_handler,
        status_handler,
        watchlist_handler,
    )

    engine = _engine()
    db = _session(engine)
    _announcement(db, "Binance Will List Foo (FOO)", "SPOT_LISTING", "b1", "ext-b1")
    db.add(
        MarketSnapshot(
            symbol="BTCUSDT",
            source="binance_spot",
            price=100,
            price_change_percent_24h=5,
            collected_at=datetime(2026, 10, 30, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    class _FakeMessage:
        def __init__(self, text):
            self.text = text
            self.answers = []

        async def answer(self, text):
            self.answers.append(text)

    cases = [
        (start_handler, "/start"),
        (help_handler, "/help"),
        (status_handler, "/status"),
        (competition_handler, "/competition"),
        (competition_handler, "/competition active"),
        (alpha_handler, "/alpha"),
        (alpha_handler, "/alpha FOO"),
        (airdrop_handler, "/airdrop"),
        (airdrops_handler, "/airdrops active"),
        (prime_handler, "/prime"),
        (prime_handler, "/prime active"),
        (prime_handler, "/prime estimate 100 400 1000"),
        (prime_handler, "/prime estimate bad"),
        (market_handler, "/market"),
        (price_handler, "/price BTC"),
        (price_handler, "/price bad!"),
        (gainers_handler, "/gainers"),
        (losers_handler, "/losers"),
        (watchlist_handler, "/watchlist"),
        (funding_handler, "/funding"),
        (funding_handler, "/funding BTCUSDT"),
        (open_interest_handler, "/openinterest"),
        (longshort_handler, "/longshort"),
        (news_handler, "/news"),
        (news_handler, "/news market"),
        (listings_handler, "/listings"),
        (delistings_handler, "/delistings"),
        (alerts_handler, "/alerts"),
        (marketalerts_handler, "/marketalerts"),
    ]
    old_db_fn = bot_module._db
    bot_module._db = lambda: _session(engine)
    try:
        for handler, text in cases:
            message = _FakeMessage(text)
            asyncio.run(handler(message))
            assert message.answers, f"{text} produced no answer"
            assert all(isinstance(a, str) and a for a in message.answers), text
        bad = _FakeMessage("/price bad!")
        asyncio.run(price_handler(bad))
        assert "Invalid symbol" in bad.answers[0]
        # Empty-database handlers say so instead of crashing.
        empty = _FakeMessage("/alpha")
        asyncio.run(alpha_handler(empty))
        assert empty.answers[0] == "None recorded yet."
    finally:
        bot_module._db = old_db_fn
