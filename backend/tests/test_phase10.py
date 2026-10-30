"""Phase 10 Stage A tests: trusted proxies, SSRF hardening for
integration test-connections, and deployment-file structure.

Mock tests only: no live Binance, Telegram, PostgreSQL, Redis,
or Docker is required. Deployment files are checked by
structure (ports, volumes, TLS directives), not by running
a container engine.
"""

import ipaddress
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.client_ip import resolve_client_ip
from app.auth.passwords import hash_password
from app.auth.permissions import PERMISSIONS, ROLE_PERMISSIONS
from app.auth import ssrf as ssrf_module
from app.auth.ssrf import SSRFBlockedError, fetch_feed, validate_url
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminUser,
    AdminUserRole,
    ApiIntegration,
)
from app.rate_limit import reset_rate_limits
from app.auth.dependencies import reset_login_rate_limits


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


def _setup():
    engine = _engine()
    db = sessionmaker(bind=engine)()
    _create_user(db, "admin1", "super_admin")
    client, old = _client_with_db(db)
    return db, client, old


def _login(client, username="admin1", password="Password123"):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.cookies.get("admin_csrf")}


def _fake_request(host, xff=None):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


# ---------------------------------------------------------------- trusted proxy

TRUSTED_LOCAL = [ipaddress.ip_network("127.0.0.0/8")]


def test_untrusted_client_cannot_spoof_ip_via_forwarded_header():
    req = _fake_request("203.0.113.9", "198.51.100.7")
    assert resolve_client_ip(req, []) == "203.0.113.9"
    assert resolve_client_ip(req, TRUSTED_LOCAL) == "203.0.113.9"


def test_trusted_proxy_forwarded_ip_is_used():
    req = _fake_request("127.0.0.1", "198.51.100.7, 203.0.113.9")
    assert resolve_client_ip(req, TRUSTED_LOCAL) == "198.51.100.7"


def test_trusted_proxy_malformed_or_missing_forwarded_falls_back():
    assert resolve_client_ip(_fake_request("127.0.0.1", "not-an-ip"), TRUSTED_LOCAL) == "127.0.0.1"
    assert resolve_client_ip(_fake_request("127.0.0.1"), TRUSTED_LOCAL) == "127.0.0.1"
    assert (
        resolve_client_ip(_fake_request("testclient", "198.51.100.7"), TRUSTED_LOCAL)
        == "testclient"
    )


def test_trusted_proxies_default_to_none():
    assert settings.trusted_proxies == ""
    assert settings.trusted_proxy_networks == []


# ---------------------------------------------------------------- SSRF


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://127.0.0.1:9/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "ftp://8.8.8.8/",
    ],
)
def test_ssrf_validation_blocks_private_and_non_http(url):
    with pytest.raises(SSRFBlockedError):
        validate_url(url)


def test_ssrf_validation_allows_literal_public_ip():
    assert validate_url("http://8.8.8.8/") == "http://8.8.8.8/"


def test_fetch_feed_validates_before_connecting(monkeypatch):
    def _private_addrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.9", 0))]

    monkeypatch.setattr(ssrf_module.socket, "getaddrinfo", _private_addrinfo)

    class _MustNotConnect:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HTTP client must not be constructed for a blocked URL")

    monkeypatch.setattr(ssrf_module.httpx, "Client", _MustNotConnect)
    with pytest.raises(SSRFBlockedError):
        fetch_feed("http://example.invalid/feed.xml")


def test_integration_test_connection_blocks_private_base_url(monkeypatch):
    db, client, old = _setup()
    try:
        headers = _login(client)

        class _MustNotPing:
            def __init__(self, *args, **kwargs):
                raise AssertionError("Spot ping must not run for a blocked URL")

            async def spot_ping(self):
                raise AssertionError("Spot ping must not run for a blocked URL")

        monkeypatch.setattr("app.binance.client.BinanceClient", _MustNotPing)
        for i, base_url in enumerate(
            ("http://127.0.0.1:9/", "http://169.254.169.254/", "http://10.0.0.5/")
        ):
            row = ApiIntegration(provider=f"binance_test_{i}", base_url=base_url, enabled=True)
            db.add(row)
            db.commit()
            response = client.post(f"/admin/integrations/{row.id}/test-connection", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "blocked"
            db.refresh(row)
            assert row.last_error is not None and "SSRF" in row.last_error
    finally:
        _restore(old)


# ---------------------------------------------------------------- deployment files

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_compose_exposes_only_nginx_and_persists_data():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "postgres_data:" in text and "redis_data:" in text
    assert "127.0.0.1:5432:5432" in text, "PostgreSQL must not be publicly exposed"
    assert "127.0.0.1:6379:6379" in text, "Redis must not be publicly exposed"
    assert '"5432:5432"' not in text and '"6379:6379"' not in text
    assert "restart: unless-stopped" in text
    assert "condition: service_healthy" in text
    assert "networks:" in text


def test_production_nginx_config():
    text = (REPO_ROOT / "nginx" / "production.conf").read_text()
    assert "listen 443 ssl" in text
    assert "ssl_protocols TLSv1.2 TLSv1.3" in text
    assert "return 301 https://" in text
    assert "proxy_set_header X-Forwarded-Proto" in text
    assert "client_max_body_size" in text
    # HSTS must NOT be enabled unconditionally: it is a
    # commented block, enabled only after HTTPS is verified.
    for line in text.splitlines():
        stripped = line.strip()
        if "Strict-Transport-Security" in stripped:
            assert stripped.startswith("#"), "HSTS must be commented out until HTTPS is confirmed"
    assert "YOUR_DOMAIN" in text or "example.com" in text


def test_deployment_scripts_are_valid_bash():
    for name in (
        "deploy.sh",
        "backup.sh",
        "restore.sh",
        "health-check.sh",
        "production-check.sh",
        "setup-https.sh",
    ):
        path = REPO_ROOT / "scripts" / name
        assert path.exists(), f"missing script {name}"
        # health-check.sh deliberately uses `set -uo pipefail`
        # (no -e) so it can report every failing service
        # instead of exiting on the first failure.
        assert "pipefail" in path.read_text(), f"{name} must fail safely"
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    # Restore must refuse a production overwrite by default.
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "restore.sh"),
            "backup.dump",
            "--target-db",
            "crypto_intelligence",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "production" in result.stdout.lower() or "production" in result.stderr.lower()
