# Database

- Engine: PostgreSQL, accessed through SQLAlchemy 2.x.
- Migrations: Alembic, one migration per schema change, never
  edited after it has been pushed.
- Timestamps: all timestamps stored in UTC (`DateTime(timezone=True)`).
- Phase 1 tables (migration `0001`):
  - `admin_users` — dashboard administrators, password hashes only,
    unique username and email.
  - `telegram_groups` — groups by unique `chat_id`, with JSON
    enabled-modules and notification preferences.
  - `system_settings` — named JSON settings, unique key.
  - `api_integrations` — provider configuration, unique provider,
    masked key only, secret reference only.
  - `audit_logs` — append-only administrative actions, with an
    optional link to the acting admin user.
- Indexes: unique indexes on usernames, emails, chat ids, setting
  keys, and providers; an index on audit log actions.
- Phase 2 tables (migration `0002`):
  - `market_snapshots` — Spot snapshot per symbol: price, 24h
    change, high, low, volume, quote volume, source, and UTC
    `collected_at`, indexed by symbol and collected_at.
    Financial values are stored as Numeric (Decimal):
    prices and volumes `Numeric(28, 8)`, funding rate
    `Numeric(20, 10)` (migration `0003`).
  - `futures_snapshots` — Futures snapshot per symbol: funding
    rate, next funding time, mark price, open interest, source,
    and UTC `collected_at`, indexed by symbol and collected_at.
- Phase 3 tables (migration `0004`):
  - `announcement_sources` — name (unique), source_type,
    base_url, enabled, polling_interval_seconds, JSON
    configuration, last success/error times and message.
  - `announcements` — source, external id, code, title, slug,
    canonical URL (unique), category + confidence, summary,
    original content, published/collected at (UTC), content
    hash, verification status, JSON metadata, notification
    status, notified at, notification attempts and error.
    Unique on `(source_id, external_id)` and on canonical
    URL; indexed on source, category, published/collected
    time, content hash, and notification status.
  - `collection_runs` — source, started/completed at (UTC),
    status, found/created/skipped counts, error message.
    Indexed on source, started time, and status.
- Later phases add the Alpha, airdrop, Prime Sale, competition,
  volume snapshot, market, futures, news, notification,
  template, and job tables, each with its own migration and
  the same UTC and uniqueness rules.
- Backups and restore procedures are documented in
  `docs/BACKUP_RESTORE.md`.
