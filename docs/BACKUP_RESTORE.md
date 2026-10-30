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
