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
