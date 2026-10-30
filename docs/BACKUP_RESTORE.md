# Backup and Restore

Phase 1 defines the backup targets; automated backup jobs and
dashboard status arrive in later phases.

Back up:

- PostgreSQL database (for example, `pg_dump` of the
  `crypto_intelligence` database), on a regular schedule.
- The `.env` file, stored securely outside the repository and
  never committed.
- Any uploaded configuration that lives outside the database.

Restore:

1. Restore the database from the latest verified dump.
2. Restore `.env` from secure storage.
3. Run `alembic upgrade head` to confirm the schema matches.
4. Start the stack and verify `/health/ready` reports all
   components as ready.

Test restores periodically. An untested backup is not a backup.

## Phase 9 status

No live backup or restore run was performed during the
Phase 9 audit (no PostgreSQL server in that environment),
so backup/restore remain NOT VERIFIED. Drill them against
a staging database before production use, using the
`pg_dump`/`pg_restore` procedure above, and record the
result in the Phase 10 report.

## Phase 10 status (Stage A)

Automated scripts now exist and are syntax-validated
(`bash -n`): `scripts/backup.sh` (pg_dump custom
format, timestamped filenames, `pg_restore --list`
integrity check, 30-day retention, 0700 directory /
0600 files, logging, non-zero exit on failure) and
`scripts/restore.sh` (integrity check first, default
target a separate test database, production overwrite
refused unless `--force-production` is passed AND the
operator types exactly `OVERWRITE PRODUCTION`).
A real backup/restore drill still requires a real
PostgreSQL server and is a Stage B task: in Stage A
only the scripts' argument, refusal, and syntax
behaviour was tested (no PostgreSQL was available),
and backups must never be stored under a web root.
The credential-encryption key is backed up
SEPARATELY from database backups: losing it makes
encrypted credentials unrecoverable even from a
perfect database backup.
