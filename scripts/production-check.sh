#!/bin/bash
# Crypto Intelligence — pre-deployment production checks (Phase 10, Stage A).
#
# Usage:  ./scripts/production-check.sh
# Every check prints PASS, WARN, or FAIL and the script
# exits non-zero if any FAIL exists. This is a gate for
# Stage B: it must pass on the real VPS before traffic is
# served. It never prints secret values (only names).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FAILURES=0
WARNINGS=0

pass() { echo "PASS $1"; }
warn() { echo "WARN $1"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo "FAIL $1"; FAILURES=$((FAILURES + 1)); }

[ -f .env ] && pass ".env exists" || fail ".env missing (copy .env.example and fill in real values)"

env_value() { grep "^$1=" .env 2>/dev/null | head -n 1 | cut -d= -f2-; }

if [ -f .env ]; then
    for var in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB SECRET_KEY CREDENTIAL_ENCRYPTION_KEY; do
        [ -n "$(env_value "$var")" ] && pass "$var present" || fail "$var missing or empty"
    done
    [ "$(env_value SECRET_KEY)" != "change-me-in-production" ] && [ -n "$(env_value SECRET_KEY)" ] \
        && pass "SECRET_KEY is not the placeholder" || fail "SECRET_KEY is still the placeholder"
    [ "$(env_value POSTGRES_PASSWORD)" != "crypto" ] && [ -n "$(env_value POSTGRES_PASSWORD)" ] \
        && pass "POSTGRES_PASSWORD is not the default" || fail "POSTGRES_PASSWORD is still the default"
    [ "$(env_value ENVIRONMENT)" = "production" ] && pass "ENVIRONMENT=production" \
        || fail "ENVIRONMENT is not production"
    DOMAIN="$(env_value DOMAIN)"
    if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "YOUR_DOMAIN" ] || [ "$DOMAIN" = "admin.example.com" ]; then
        fail "DOMAIN is missing or still a placeholder (set the real domain for HTTPS)"
    elif printf '%s' "$DOMAIN" | grep -Eq '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'; then
        pass "DOMAIN looks like a real domain ($DOMAIN)"
    else
        fail "DOMAIN does not look like a valid domain"
    fi
    TRUSTED="$(env_value TRUSTED_PROXIES)"
    if [ -n "$TRUSTED" ]; then
        warn "TRUSTED_PROXIES is set; confirm it lists only proxies you operate"
    else
        pass "TRUSTED_PROXIES empty (no forwarded headers trusted)"
    fi
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    pass "docker compose available"
    docker compose config -q >/dev/null 2>&1 && pass "compose configuration valid" || fail "compose configuration invalid"
else
    fail "docker compose not available"
fi

# Disk: at least 2 GB free on the deployment filesystem.
FREE_KB="$(df -k "$ROOT" | awk 'NR==2 {print $4}')"
if [ "$FREE_KB" -ge 2097152 ]; then
    pass "disk free >= 2 GB"
else
    fail "disk free < 2 GB"
fi

# TLS readiness (informational gate, not a hard pass):
# production Nginx requires certificates; setup-https.sh
# creates them. This check only reports their presence.
if [ "${NGINX_CONFIG_FILE:-./nginx/nginx.conf}" = "./nginx/production.conf" ]; then
    if command -v docker >/dev/null 2>&1 && docker compose ps -q nginx >/dev/null 2>&1; then
        warn "production Nginx config selected; verify certificates with scripts/setup-https.sh before serving traffic"
    else
        warn "production Nginx config selected but nginx is not running; run setup-https.sh first"
    fi
else
    warn "HTTP-only Nginx config selected; do NOT serve production traffic until setup-https.sh has run"
fi

echo "---"
echo "FAILURES: $FAILURES  WARNINGS: $WARNINGS"
[ "$FAILURES" -eq 0 ]
