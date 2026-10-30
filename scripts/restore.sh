#!/bin/bash
# Crypto Intelligence — PostgreSQL restore (Phase 10, Stage A).
#
# Usage:
#   ./scripts/restore.sh <backup-file> [--target-db NAME] [--force-production]
#
# SAFETY (read this before running):
# - Default target is a SEPARATE test database
#   (<production-db>_restore), never production.
# - If --target-db names the production database, the
#   script REFUSES unless BOTH --force-production is
#   passed AND the operator types exactly
#   "OVERWRITE PRODUCTION" at the prompt. There is no
#   quiet way to overwrite production.
# - The backup is integrity-checked with
#   `pg_restore --list` BEFORE anything is restored.
# - This script never deletes volumes, never downgrades
#   migrations, and never prints secrets.
# - Restoring a database backup does NOT restore the
#   credential-encryption key: if that key is lost,
#   encrypted credentials stay unrecoverable (see
#   docs/BACKUP_RESTORE.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_USER="${POSTGRES_USER:-crypto}"
PROD_DB="${POSTGRES_DB:-crypto_intelligence}"
TARGET_DB="${PROD_DB}_restore"
FORCE_PRODUCTION=0
BACKUP_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --target-db) TARGET_DB="$2"; shift 2 ;;
        --force-production) FORCE_PRODUCTION=1; shift ;;
        -h|--help)
            echo "Usage: $0 <backup-file> [--target-db NAME] [--force-production]"
            exit 0 ;;
        *) if [ -z "$BACKUP_FILE" ]; then BACKUP_FILE="$1"; shift; else echo "ERROR: unexpected argument: $1" >&2; exit 1; fi ;;
    esac
done

if [ -z "$BACKUP_FILE" ]; then
    echo "ERROR: a backup file is required." >&2
    echo "Usage: $0 <backup-file> [--target-db NAME] [--force-production]" >&2
    exit 1
fi

# --- Refusal gate: runs BEFORE any docker/tool check, so
# an accidental production overwrite cannot slip through
# because a tool happened to be missing.
if [ "$TARGET_DB" = "$PROD_DB" ] && [ "$FORCE_PRODUCTION" -ne 1 ]; then
    echo "ERROR: refusing to restore into the production database '$PROD_DB'." >&2
    echo "Restores default to a separate test database (use --target-db <name>)." >&2
    echo "To overwrite production deliberately, pass --force-production and type OVERWRITE PRODUCTION at the prompt." >&2
    exit 1
fi
if [ "$TARGET_DB" = "$PROD_DB" ] && [ "$FORCE_PRODUCTION" -eq 1 ]; then
    echo "WARNING: you are about to OVERWRITE the production database '$PROD_DB'."
    printf 'Type OVERWRITE PRODUCTION to confirm: '
    read -r CONFIRM || { echo "ERROR: confirmation not given; aborting." >&2; exit 1; }
    if [ "$CONFIRM" != "OVERWRITE PRODUCTION" ]; then
        echo "ERROR: confirmation did not match; aborting." >&2
        exit 1
    fi
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    MODE="docker"
elif command -v pg_restore >/dev/null 2>&1 && command -v psql >/dev/null 2>&1; then
    MODE="host"
else
    echo "ERROR: neither 'docker compose' nor pg_restore/psql is available; cannot restore." >&2
    exit 1
fi

# --- Integrity check before any restore.
if [ "$MODE" = "docker" ]; then
    docker compose -f "$ROOT/docker-compose.yml" exec -T postgres pg_restore --list < "$BACKUP_FILE" >/dev/null
else
    pg_restore --list "$BACKUP_FILE" >/dev/null
fi
echo "OK backup integrity verified: $BACKUP_FILE"

# --- Create the target database if it does not exist.
if [ "$MODE" = "docker" ]; then
    docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
        psql -U "$POSTGRES_USER" -tc "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'" | grep -q 1 \
        || docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
            createdb -U "$POSTGRES_USER" "$TARGET_DB"
    docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
        pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$TARGET_DB" < "$BACKUP_FILE"
else
    psql -h "${PGHOST:-localhost}" -U "$POSTGRES_USER" -tc "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'" | grep -q 1 \
        || createdb -h "${PGHOST:-localhost}" -U "$POSTGRES_USER" "$TARGET_DB"
    pg_restore --clean --if-exists --no-owner -h "${PGHOST:-localhost}" -U "$POSTGRES_USER" -d "$TARGET_DB" "$BACKUP_FILE"
fi

echo "OK restored $BACKUP_FILE into database '$TARGET_DB'"
echo "Next: run migrations check (alembic current) and the health-check script before pointing any service at this database."
