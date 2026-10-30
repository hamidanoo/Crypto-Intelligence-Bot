#!/bin/bash
# Crypto Intelligence — production deployment (Phase 10, Stage A).
#
# Usage:  ./scripts/deploy.sh
#
# What this script does:
#   1. Validates the deployment environment (presence of
#      required variables, no placeholder secrets).
#   2. Validates the Compose file (docker compose config).
#   3. Pulls pinned images and rebuilds app images.
#   4. Starts the stack. The backend entrypoint runs
#      `alembic upgrade head` BEFORE the API starts; if
#      migrations fail, the backend exits and the deploy
#      fails here — the API is never exposed stale.
#   5. Runs scripts/health-check.sh.
#
# What it NEVER does (by design):
#   - It never deletes volumes (no `down -v`).
#   - It never downgrades migrations.
#   - It never prints secret values (only variable names).
#   - It never issues TLS certificates (see
#     scripts/setup-https.sh, Stage B).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: 'docker compose' is required for deployment and was not found." >&2
    exit 1
fi
if [ ! -f .env ]; then
    echo "ERROR: .env not found in $ROOT. Copy .env.example to .env and fill in real values (never commit .env)." >&2
    exit 1
fi

# Validate required variables WITHOUT printing values.
check_present() {
    local name="$1"
    if ! grep -q "^${name}=" .env; then
        echo "ERROR: $name is missing from .env" >&2
        exit 1
    fi
    local value
    value="$(grep "^${name}=" .env | head -n 1 | cut -d= -f2-)"
    if [ -z "$value" ]; then
        echo "ERROR: $name is empty in .env" >&2
        exit 1
    fi
}
check_not_placeholder() {
    local name="$1" bad="$2"
    local value
    value="$(grep "^${name}=" .env | head -n 1 | cut -d= -f2-)"
    if [ "$value" = "$bad" ]; then
        echo "ERROR: $name still has its placeholder/default value in .env" >&2
        exit 1
    fi
}

for var in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB SECRET_KEY CREDENTIAL_ENCRYPTION_KEY; do
    check_present "$var"
done
check_not_placeholder SECRET_KEY "change-me-in-production"
check_not_placeholder POSTGRES_PASSWORD "crypto"
if ! grep -q "^ENVIRONMENT=production" .env; then
    echo "ERROR: ENVIRONMENT is not 'production' in .env; refusing to run a production deploy with development settings." >&2
    exit 1
fi

echo "OK environment validation passed"
docker compose config -q
echo "OK compose configuration valid"

docker compose pull postgres redis nginx
docker compose up -d --build
echo "OK stack started; backend entrypoint runs migrations before the API serves traffic"

./scripts/health-check.sh
echo "OK deployment healthy"
