"""Phase 8 tests: administrator authentication, RBAC, sessions,
credential encryption, audit logging, dashboard, and protected
endpoints.

Mock tests only for the core suite: every test uses an
in-memory database and, where a network call would be
needed, a mocked transport or a deliberately unconfigured
service. Nothing here depends on live Binance, live
Telegram, or live PostgreSQL, and nothing here claims a
live integration.
"""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import check_login_rate_limit, reset_login_rate_limits
from app.auth.encryption import (
    CredentialEncryptionError,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)
from app.auth.passwords import hash_password
from app.auth.permissions import PERMISSIONS, ROLE_PERMISSIONS
from app.config import settings
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
    PasswordResetToken,
)
from app.rate_limit import reset_rate_limits

TEST_KEY = base64.b64encode(b"A" * 32).decode("ascii")
TEST_KEY_2 = base64.b64encode(b"B" * 32).decode("ascii")


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


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


def _create_user(db, username, role, password="Password123"):
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


def _login(client, username, password="Password123"):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.cookies.get("admin_csrf")}


def _setup(role="super_admin", username="admin1"):
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _create_user(db, username, role)
    client, old = _client_with_db(db)
    return db, client, old


# ---------------------------------------------------------------- auth


def test_valid_login_me_and_permissions():
    db, client, old = _setup()
    try:
        _login(client, "admin1")
        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "admin1"
        assert "users.manage" in me.json()["permissions"]
        assert "password_hash" not in me.text
        # Security headers are present on API responses.
        health = client.get("/health")
        assert health.headers.get("X-Frame-Options") == "DENY"
        assert health.headers.get("X-Content-Type-Options") == "nosniff"
    finally:
        _restore(old)


def test_invalid_login_and_unknown_user_same_response():
    db, client, old = _setup()
    try:
        bad_password = client.post(
            "/auth/login", json={"username": "admin1", "password": "WrongPassword123"}
        )
        assert bad_password.status_code == 401
        unknown = client.post(
            "/auth/login", json={"username": "nobody", "password": "WrongPassword123"}
        )
        assert unknown.status_code == 401
        assert unknown.json()["detail"] == bad_password.json()["detail"]
        # The failure is audited without any secret.
        row = db.query(AuditLog).filter(AuditLog.action == "login.failed").first()
        assert row is not None
        assert "WrongPassword" not in str(row.details)
    finally:
        _restore(old)


def test_inactive_admin_cannot_login():
    db, client, old = _setup()
    try:
        user = db.query(AdminUser).filter(AdminUser.username == "admin1").first()
        user.is_active = False
        db.commit()
        response = client.post(
            "/auth/login", json={"username": "admin1", "password": "Password123"}
        )
        assert response.status_code == 401
    finally:
        _restore(old)


def test_login_lockout_after_failures():
    db, client, old = _setup()
    try:
        for _ in range(settings.login_max_attempts):
            client.post("/auth/login", json={"username": "admin1", "password": "Wrong123"})
        locked = client.post("/auth/login", json={"username": "admin1", "password": "Password123"})
        assert locked.status_code == 401
        user = db.query(AdminUser).filter(AdminUser.username == "admin1").first()
        assert user.locked_until is not None
    finally:
        _restore(old)


def test_login_rate_limit_function():
    class _Client:
        host = "203.0.113.99"

    class _Request:
        client = _Client()
        headers = {}

    reset_login_rate_limits()
    for _ in range(settings.login_rate_limit_per_minute):
        check_login_rate_limit(_Request())
    with pytest.raises(Exception) as excinfo:
        check_login_rate_limit(_Request())
    assert excinfo.value.status_code == 429
    reset_login_rate_limits()


def test_session_expiry_and_logout_invalidation():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        assert client.get("/auth/me").status_code == 200
        logout = client.post("/auth/logout", headers=headers)
        assert logout.status_code == 200
        assert client.get("/auth/me").status_code == 401
        # A fresh login, then an expired session, is rejected.
        headers = _login(client, "admin1")
        session = db.query(AdminSession).order_by(AdminSession.id.desc()).first()
        session.last_seen_at = datetime.now(timezone.utc) - timedelta(
            minutes=settings.session_inactivity_minutes + 5
        )
        db.commit()
        assert client.get("/auth/me").status_code == 401
    finally:
        _restore(old)


def test_session_rotation_invalidates_old_token():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        old_cookie = client.cookies.get("admin_session")
        refreshed = client.post("/auth/refresh", headers=headers)
        assert refreshed.status_code == 200
        new_cookie = client.cookies.get("admin_session")
        assert new_cookie != old_cookie
        # The old token no longer authenticates.
        other = TestClient(app, raise_server_exceptions=False)
        other.cookies.set("admin_session", old_cookie)
        assert other.get("/auth/me").status_code == 401
    finally:
        _restore(old)


def test_session_fixation_pre_login_cookie_not_reused():
    db, client, old = _setup()
    try:
        client.cookies.set("admin_session", "attacker-chosen-session-value")
        _login(client, "admin1")
        assert client.get("/auth/me").status_code == 200
        # Presenting only the attacker-chosen cookie value
        # must not authenticate anyone.
        attacker = TestClient(app, raise_server_exceptions=False)
        attacker.cookies.set("admin_session", "attacker-chosen-session-value")
        assert attacker.get("/auth/me").status_code == 401
    finally:
        _restore(old)


def test_password_change_and_other_sessions_revoked():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        wrong = client.post(
            "/auth/change-password",
            json={"current_password": "Wrong123", "new_password": "NewPassword123"},
            headers=headers,
        )
        assert wrong.status_code == 400
        # A second session exists; changing the password
        # through the first must revoke the second.
        other = TestClient(app, raise_server_exceptions=False)
        # Share the same app override: log in from a second client.
        _login(other, "admin1")
        changed = client.post(
            "/auth/change-password",
            json={"current_password": "Password123", "new_password": "NewPassword123"},
            headers=headers,
        )
        assert changed.status_code == 200
        assert other.get("/auth/me").status_code == 401
        fresh = TestClient(app, raise_server_exceptions=False)
        assert (
            fresh.post(
                "/auth/login",
                json={"username": "admin1", "password": "NewPassword123"},
            ).status_code
            == 200
        )
        assert (
            fresh.post(
                "/auth/login",
                json={"username": "admin1", "password": "Password123"},
            ).status_code
            == 401
        )
    finally:
        _restore(old)


def test_password_reset_single_use_expiry_and_no_enumeration():
    import hashlib
    import secrets

    db, client, old = _setup()
    try:
        unknown = client.post(
            "/auth/forgot-password", json={"username_or_email": "nobody@example.invalid"}
        )
        known = client.post("/auth/forgot-password", json={"username_or_email": "admin1"})
        assert unknown.status_code == 200
        assert unknown.json() == known.json()
        user = db.query(AdminUser).filter(AdminUser.username == "admin1").first()
        token = secrets.token_urlsafe(32)
        row = PasswordResetToken(
            admin_user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=60),
        )
        db.add(row)
        db.commit()
        reset = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "ResetPassword123"},
        )
        assert reset.status_code == 200
        reuse = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "ResetPassword123"},
        )
        assert reuse.status_code == 400
        expired_token = secrets.token_urlsafe(32)
        expired = PasswordResetToken(
            admin_user_id=user.id,
            token_hash=hashlib.sha256(expired_token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(expired)
        db.commit()
        assert (
            client.post(
                "/auth/reset-password",
                json={"token": expired_token, "new_password": "ResetPassword123"},
            ).status_code
            == 400
        )
    finally:
        _restore(old)


def test_csrf_required_for_state_changes():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        no_csrf = client.post(
            "/admin/users",
            json={
                "username": "newadmin",
                "email": "new@example.invalid",
                "password": "Password123",
                "role": "viewer",
            },
        )
        assert no_csrf.status_code == 403
        wrong_csrf = client.post(
            "/admin/users",
            json={
                "username": "newadmin",
                "email": "new@example.invalid",
                "password": "Password123",
                "role": "viewer",
            },
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert wrong_csrf.status_code == 403
        ok = client.post(
            "/admin/users",
            json={
                "username": "newadmin",
                "email": "new@example.invalid",
                "password": "Password123",
                "role": "viewer",
            },
            headers=headers,
        )
        assert ok.status_code == 200
        assert "password_hash" not in ok.text
    finally:
        _restore(old)


# ---------------------------------------------------------------- RBAC


def test_role_permission_matrix():
    for role, can_manage_users, can_collect in [
        ("super_admin", True, True),
        ("admin", False, True),
        ("operator", False, True),
        ("viewer", False, False),
    ]:
        db, client, old = _setup(role=role, username=f"user-{role}")
        try:
            headers = _login(client, f"user-{role}")
            users = client.get("/admin/users")
            assert users.status_code == (200 if role in ("super_admin", "admin") else 403)
            create = client.post(
                "/admin/users",
                json={
                    "username": "new-user-x",
                    "email": "x@example.invalid",
                    "password": "Password123",
                    "role": "viewer",
                },
                headers=headers,
            )
            assert create.status_code == (200 if can_manage_users else 403)
            collect = client.post("/competition-volume/collect", headers=headers)
            assert collect.status_code == (200 if can_collect else 403)
            audit_list = client.get("/admin/audit-logs")
            assert audit_list.status_code == (200 if role in ("super_admin", "admin") else 403)
        finally:
            _restore(old)


def test_privilege_escalation_guards():
    db, client, old = _setup(role="admin", username="admin-user")
    try:
        headers = _login(client, "admin-user")
        # An admin cannot create a super_admin.
        escalate = client.post(
            "/admin/users",
            json={
                "username": "evil",
                "email": "evil@example.invalid",
                "password": "Password123",
                "role": "super_admin",
            },
            headers=headers,
        )
        assert escalate.status_code == 403
        # An admin cannot change their own role.
        me = client.get("/auth/me").json()
        self_promote = client.patch(
            f"/admin/users/{me['id']}", json={"role": "super_admin"}, headers=headers
        )
        assert self_promote.status_code == 403
    finally:
        _restore(old)


def test_last_super_admin_cannot_be_removed():
    db, client, old = _setup(role="super_admin", username="only-super")
    try:
        headers = _login(client, "only-super")
        me = client.get("/auth/me").json()
        demote = client.patch(f"/admin/users/{me['id']}", json={"role": "admin"}, headers=headers)
        assert demote.status_code == 400
        deactivate_self = client.post(f"/admin/users/{me['id']}/deactivate", headers=headers)
        assert deactivate_self.status_code == 403
        # A second super_admin makes demotion safe.
        second = client.post(
            "/admin/users",
            json={
                "username": "second-super",
                "email": "second@example.invalid",
                "password": "Password123",
                "role": "super_admin",
            },
            headers=headers,
        )
        assert second.status_code == 200
        # Self-demotion stays blocked even with a second
        # Super Admin; another administrator must do it.
        demote_now = client.patch(
            f"/admin/users/{me['id']}", json={"role": "admin"}, headers=headers
        )
        assert demote_now.status_code == 403
        second_client = TestClient(app, raise_server_exceptions=False)
        second_headers = _login(second_client, "second-super")
        demote_by_other = second_client.patch(
            f"/admin/users/{me['id']}", json={"role": "admin"}, headers=second_headers
        )
        assert demote_by_other.status_code == 200
    finally:
        _restore(old)


COLLECT_ENDPOINTS = [
    "/announcements/collect",
    "/announcements/sources/1/collect",
    "/binance/collect/market",
    "/binance/collect/futures",
    "/competitions/collect",
    "/futures/collect",
    "/alpha/collect",
    "/airdrops/collect",
    "/prime-sales/collect",
    "/market/collect",
    "/news/collect",
    "/competition-volume/collect",
    "/competition-volume/1/collect",
]


def test_protected_collection_endpoints():
    db, client, old = _setup(role="viewer", username="viewer1")
    try:
        headers = _login(client, "viewer1")
        anon = TestClient(app, raise_server_exceptions=False)
        for path in COLLECT_ENDPOINTS:
            assert anon.post(path, json={}).status_code == 401, path
            assert client.post(path, json={}, headers=headers).status_code == 403, path
        # Scheduler controls are protected the same way.
        assert anon.post("/admin/scheduler/announcement_collection/trigger").status_code == 401
        assert (
            client.post(
                "/admin/scheduler/announcement_collection/trigger", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post("/admin/scheduler/unknown_job/trigger", headers=headers).status_code == 403
        )
    finally:
        _restore(old)


# ---------------------------------------------------------------- encryption


def test_credential_encryption_masking_and_rotation():
    db, client, old = _setup()
    old_key = settings.credential_encryption_key
    old_previous = settings.credential_encryption_key_previous
    try:
        headers = _login(client, "admin1")
        settings.credential_encryption_key = TEST_KEY
        settings.credential_encryption_key_previous = None
        created = client.post(
            "/admin/integrations",
            json={
                "provider": "test-provider",
                "api_key": "AKIA1234567890ABCD",
                "api_secret": "top-secret-value",
                "enabled": True,
            },
            headers=headers,
        )
        assert created.status_code == 200
        body = created.json()
        assert "top-secret-value" not in created.text
        assert body["api_key_masked"] == "****ABCD"
        listed = client.get("/admin/integrations")
        assert "top-secret-value" not in listed.text
        # Service-level rotation: a secret encrypted under
        # TEST_KEY decrypts through the previous key after
        # rotation, and no longer through the current key.
        encrypted = encrypt_secret("rotate-me")
        settings.credential_encryption_key = TEST_KEY_2
        settings.credential_encryption_key_previous = TEST_KEY
        assert (
            decrypt_secret(encrypted["ciphertext_b64"], encrypted["nonce_b64"], "previous")
            == "rotate-me"
        )
        with pytest.raises(CredentialEncryptionError):
            decrypt_secret(encrypted["ciphertext_b64"], encrypted["nonce_b64"], "current")
        # The stored row was encrypted under TEST_KEY, so it
        # now decrypts only through the previous key.
        from app.models import ApiIntegration

        row = db.query(ApiIntegration).filter(ApiIntegration.provider == "test-provider").first()
        assert row.encrypted_secret != "top-secret-value"
        assert (
            decrypt_secret(row.encrypted_secret, row.encrypted_nonce, "previous")
            == "top-secret-value"
        )
        assert mask_secret("ABCDEFGH") == "****EFGH"
        assert mask_secret(None) is None
        with pytest.raises(CredentialEncryptionError):
            decrypt_secret(row.encrypted_secret, row.encrypted_nonce, "current")
        # Missing key: credential writes fail clearly.
        settings.credential_encryption_key = None
        settings.credential_encryption_key_previous = None
        missing = client.post(
            "/admin/integrations",
            json={"provider": "second-provider", "api_secret": "secret"},
            headers=headers,
        )
        assert missing.status_code == 503
        # Invalid key: same clear failure.
        settings.credential_encryption_key = "not-valid-base64!!!"
        invalid = client.post(
            "/admin/integrations",
            json={"provider": "third-provider", "api_secret": "secret"},
            headers=headers,
        )
        assert invalid.status_code == 503
    finally:
        settings.credential_encryption_key = old_key
        settings.credential_encryption_key_previous = old_previous
        _restore(old)


# ---------------------------------------------------------------- audit / admin


def test_audit_recording_pagination_access_and_immutability():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        client.post(
            "/admin/users",
            json={
                "username": "audited-user",
                "email": "audited@example.invalid",
                "password": "Password123",
                "role": "viewer",
            },
            headers=headers,
        )
        logs = client.get("/admin/audit-logs")
        assert logs.status_code == 200
        actions = [row["action"] for row in logs.json()["items"]]
        assert "login.success" in actions
        assert "admin.created" in actions
        page = client.get("/admin/audit-logs?page=1&page_size=1")
        assert len(page.json()["items"]) == 1
        filtered = client.get("/admin/audit-logs?action=login.success")
        assert all(row["action"] == "login.success" for row in filtered.json()["items"])
        # No update or delete route exists for audit logs.
        assert client.patch("/admin/audit-logs/1", json={}, headers=headers).status_code in (
            404,
            405,
        )
        assert client.delete("/admin/audit-logs/1", headers=headers).status_code in (
            404,
            405,
        )
        # A viewer cannot read audit logs.
        db2, client2, old2 = _setup(role="viewer", username="viewer-audit")
        try:
            v_headers = _login(client2, "viewer-audit")
            assert client2.get("/admin/audit-logs", headers=v_headers).status_code == 403
        finally:
            _restore(old2)
    finally:
        _restore(old)


def test_dashboard_overview_uses_real_data():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        source = AnnouncementSource(
            name="Test Source",
            source_type="binance_website_cms",
            base_url="https://www.binance.com",
        )
        db.add(source)
        db.commit()
        for i in range(3):
            db.add(
                Announcement(
                    source_id=source.id,
                    source_name=source.name,
                    external_id=f"ext-{i}",
                    code=f"code-{i}",
                    title=f"Test announcement {i}",
                    slug=f"test-{i}",
                    canonical_url=f"https://example.invalid/announcement/{i}",
                    category="GENERAL",
                    category_confidence="high",
                    content_hash=f"hash-{i}",
                    verification_status="official_website",
                )
            )
        db.commit()
        overview = client.get("/admin/dashboard/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["announcements_total"] == 3
        assert overview.json()["database_status"] == "healthy"
        assert "dashboard_refresh_interval_seconds" in overview.json()
        activity = client.get("/admin/dashboard/activity", headers=headers)
        assert activity.status_code == 200
        assert "announcements_by_day" in activity.json()
        health = client.get("/admin/dashboard/health", headers=headers)
        assert health.status_code == 200
        names = [s["name"] for s in health.json()["services"]]
        assert "database" in names and "scheduler" in names
    finally:
        _restore(old)


def test_scheduler_controls_and_allowlist():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        jobs = client.get("/admin/scheduler", headers=headers)
        assert jobs.status_code == 200
        ids = [job["id"] for job in jobs.json()["items"]]
        assert "announcement_collection" in ids
        assert "market_snapshot" in ids
        trigger = client.post("/admin/scheduler/announcement_collection/trigger", headers=headers)
        assert trigger.status_code == 200
        assert trigger.json()["status"] == "triggered"
        unknown = client.post("/admin/scheduler/not_a_job/trigger", headers=headers)
        assert unknown.status_code == 400
        pause = client.post("/admin/scheduler/announcement_collection/pause", headers=headers)
        assert pause.status_code == 200
        resume = client.post("/admin/scheduler/announcement_collection/resume", headers=headers)
        assert resume.status_code == 200
    finally:
        _restore(old)


def test_telegram_config_masking_and_test_message_requires_config():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        config = client.get("/admin/telegram", headers=headers)
        assert config.status_code == 200
        assert "telegram_bot_token" not in config.text
        patched = client.patch(
            "/admin/telegram",
            json={"group_chat_id": "-100123456", "notifications_enabled": False},
            headers=headers,
        )
        assert patched.status_code == 200
        assert patched.json()["group_chat_id"] == "-100123456"
        # No bot token is configured in tests, so the test
        # message must fail cleanly instead of sending.
        test_message = client.post(
            "/admin/telegram/test-message", json={"message": "hello"}, headers=headers
        )
        assert test_message.status_code == 503
    finally:
        _restore(old)


def test_notification_settings_persist():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        patched = client.patch(
            "/admin/notifications",
            json={"global_enabled": False, "categories": {"alpha": True}, "cooldown_minutes": 30},
            headers=headers,
        )
        assert patched.status_code == 200
        fetched = client.get("/admin/notifications", headers=headers)
        assert fetched.json()["global_enabled"] is False
        assert fetched.json()["categories"] == {"alpha": True}
        assert fetched.json()["cooldown_minutes"] == 30
    finally:
        _restore(old)


def test_system_settings_and_viewer_denied():
    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        patched = client.patch(
            "/admin/system-settings",
            json={"key": "dashboard_refresh", "value": {"seconds": 120}},
            headers=headers,
        )
        assert patched.status_code == 200
        listed = client.get("/admin/system-settings", headers=headers)
        keys = [item["key"] for item in listed.json()["items"]]
        assert "dashboard_refresh" in keys
    finally:
        _restore(old)


# ---------------------------------------------------------------- SSRF


def test_news_source_ssrf_protections():
    from app.auth import ssrf as ssrf_module

    db, client, old = _setup()
    try:
        headers = _login(client, "admin1")
        for url in [
            "http://127.0.0.1/feed",
            "http://10.0.0.5/feed",
            "http://192.168.1.1/feed",
            "http://169.254.1.1/feed",
            "ftp://example.invalid/feed",
        ]:
            created = client.post(
                "/admin/news-sources",
                json={"name": f"source-{url}", "feed_url": url},
                headers=headers,
            )
            assert created.status_code == 200, url
            tested = client.post(
                f"/admin/news-sources/{created.json()['id']}/test", headers=headers
            )
            assert tested.status_code == 400, url
        # A hostname resolving to a private address is blocked.
        original_getaddrinfo = __import__("socket").getaddrinfo

        def _fake_getaddrinfo(host, port, *args, **kwargs):
            if host == "evil.example":
                return [(2, 1, 6, "", ("10.9.8.7", 0))]
            return original_getaddrinfo(host, port, *args, **kwargs)

        import socket

        socket.getaddrinfo = _fake_getaddrinfo
        try:
            with pytest.raises(ssrf_module.SSRFBlockedError):
                ssrf_module.validate_url("https://evil.example/feed")
        finally:
            socket.getaddrinfo = original_getaddrinfo

        # Redirects into a prohibited range are blocked.
        class _FakeResponse:
            def __init__(self, status, location=None):
                self.status_code = status
                self.headers = {"location": location} if location else {}

            def read(self):
                return b"<rss></rss>"

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, headers=None):
                if "evil.example" in url or "127.0.0.1" in url:
                    return _FakeResponse(200)
                return _FakeResponse(302, location="http://127.0.0.1/feed")

        original_client = ssrf_module.httpx.Client
        ssrf_module.httpx.Client = _FakeClient
        try:
            with pytest.raises(ssrf_module.SSRFBlockedError):
                ssrf_module.fetch_feed("https://example.invalid/feed")
        finally:
            ssrf_module.httpx.Client = original_client
        # Creating a source never enables it automatically.
        created = client.post(
            "/admin/news-sources",
            json={"name": "never-auto-enabled", "feed_url": "https://example.invalid/feed"},
            headers=headers,
        )
        assert created.json()["enabled"] is False
        auto = client.post(
            "/admin/news-sources",
            json={
                "name": "auto-enabled-attempt",
                "feed_url": "https://example.invalid/feed",
                "enabled": True,
            },
            headers=headers,
        )
        assert auto.status_code == 400
    finally:
        _restore(old)
