#!/bin/bash
# Crypto Intelligence — service health checks (Phase 10, Stage A).
#
# Usage:  ./scripts/health-check.sh
# Prints one PASS/FAIL line per service and exits non-zero
# if any check fails. No secrets are printed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILURES=0

check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "PASS $name"
    else
        echo "FAIL $name"
        FAILURES=$((FAILURES + 1))
    fi
}

HAVE_DOCKER=0
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    HAVE_DOCKER=1
fi

check "backend /health" curl -fsS --max-time 5 http://127.0.0.1:8000/health
check "frontend /" curl -fsS --max-time 5 http://127.0.0.1:3000/
if [ "$HAVE_DOCKER" = "1" ]; then
    check "postgres pg_isready" docker compose -f "$ROOT/docker-compose.yml" exec -T postgres pg_isready -U "${POSTGRES_USER:-crypto}"
    check "redis ping" docker compose -f "$ROOT/docker-compose.yml" exec -T redis redis-cli ping
else
    check "postgres pg_isready" pg_isready -h localhost
    check "redis ping" redis-cli ping
fi

if [ "$FAILURES" -ne 0 ]; then
    echo "HEALTH CHECK FAILED ($FAILURES failure(s))"
    exit 1
fi
echo "HEALTH CHECK OK"
