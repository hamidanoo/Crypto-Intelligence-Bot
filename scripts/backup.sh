#!/bin/bash
# Crypto Intelligence — PostgreSQL backup (Phase 10, Stage A).
#
# Usage:  BACKUP_DIR=/var/backups/crypto-intelligence ./scripts/backup.sh
#         (defaults: BACKUP_DIR=<repo>/backups, retention 30 days)
#
# - Full database backup with pg_dump custom format (-Fc).
# - Timestamped filename, gzip is NOT applied on top of -Fc
#   (custom format is already compressed); integrity is
#   verified with `pg_restore --list` before the file is
#   kept. A failed integrity check deletes the file and
#   exits non-zero.
# - Retention: files older than BACKUP_RETENTION_DAYS are
#   deleted. Backup directory permissions 0700, files 0600.
# - Backups are NEVER written under a web root, and this
#   script NEVER prints secrets: only filenames, sizes,
#   and counts are logged.
# - The credential-encryption key is NOT in this backup.
#   Back it up separately (see docs/BACKUP_RESTORE.md);
#   losing it means encrypted credentials cannot be
#   recovered even from a perfect database backup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
POSTGRES_USER="${POSTGRES_USER:-crypto}"
POSTGRES_DB="${POSTGRES_DB:-crypto_intelligence}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILENAME="crypto_intelligence_${TIMESTAMP}.dump"
LOG_FILE="$BACKUP_DIR/backup.log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"
: > "$LOG_FILE" 2>/dev/null || true

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    MODE="docker"
elif command -v pg_dump >/dev/null 2>&1; then
    MODE="host"
else
    echo "ERROR: neither 'docker compose' nor pg_dump is available; cannot back up." >&2
    exit 1
fi

TMP_FILE="$BACKUP_DIR/.${FILENAME}.tmp"
cleanup() { rm -f "$TMP_FILE"; }
trap cleanup EXIT

if [ "$MODE" = "docker" ]; then
    # Dump streams from the container to a host file; no
    # database volume is ever touched, and nothing is
    # written under a web root.
    docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
        pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$TMP_FILE"
    # Integrity check on the host copy (pg_restore --list
    # only reads the header; it never restores anything).
    if command -v pg_restore >/dev/null 2>&1; then
        pg_restore --list "$TMP_FILE" >/dev/null
    else
        log "WARNING: pg_restore not on host; integrity check deferred to restore time"
    fi
else
    pg_dump -h "${PGHOST:-localhost}" -U "$POSTGRES_USER" -Fc -f "$TMP_FILE" "$POSTGRES_DB"
    pg_restore --list "$TMP_FILE" >/dev/null
fi

chmod 0600 "$TMP_FILE"
mv "$TMP_FILE" "$BACKUP_DIR/$FILENAME"
trap - EXIT
SIZE="$(du -h "$BACKUP_DIR/$FILENAME" | cut -f1)"
log "OK backup created: $FILENAME ($SIZE)"

# Retention: delete dumps older than RETENTION_DAYS.
DELETED="$(find "$BACKUP_DIR" -maxdepth 1 -name 'crypto_intelligence_*.dump' -type f -mtime "+$RETENTION_DAYS" -print -delete | wc -l)"
log "OK retention: $DELETED file(s) older than $RETENTION_DAYS days removed"
echo "Backup: $BACKUP_DIR/$FILENAME"
