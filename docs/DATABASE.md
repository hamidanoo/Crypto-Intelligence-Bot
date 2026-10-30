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
- Phase 4 tables (migration `0005`):
  - `alpha_tokens` — one record per ALPHA announcement
    (unique announcement_id): token name/symbol,
    contract address, network, trading status/pairs,
    announcement URL and timestamp, JSON metadata,
    data source, verification status, Decimal price,
    24h change and volume, market data source, updated
    time, and market data status. Indexed on
    announcement, symbol, contract, and network.
  - `alpha_token_updates` — creation and price-change
    records per token, with a JSON changes object.
  - `airdrop_campaigns` — one record per AIRDROP
    announcement (unique announcement_id): campaign
    name, token name/symbol, description, eligibility
    summary, start/end/claim dates, distribution
    schedule, reward info, supported networks (JSON),
    official URL, and status (UPCOMING/ACTIVE/ENDED/
    CLAIMING/DISTRIBUTION_COMPLETED/CANCELLED/UNKNOWN).
    Indexed on announcement, symbol, and status.
  - `airdrop_eligibility` — one row per recognisable
    eligibility hint, with requirement type,
    description, source text, and
    `is_confirmed_details` (False for title hints).
  - `prime_sales` — one record per PRIME_SALE
    announcement (unique announcement_id): token
    name/symbol, description, subscription start/end,
    distribution time, trading availability, Decimal
    subscription price and min/max commitment,
    eligible assets (JSON), allocation methodology,
    reward info, official URL, and status.
  - `prime_sale_allocation_rules` — one rule per sale
    (unique sale_id): formula type (unknown unless
    officially confirmed), description, Decimal total
    token allocation and sale price.
  - `campaign_notifications` — duplicate prevention:
    unique on (entity_type, entity_id,
    notification_type), with status, sent time, and
    error message.
- Phase 5 (migration `0006`) adds:
  - `competitions` — one record per TRADING_COMPETITION
    announcement (unique announcement_id): name,
    description (the full title), type
    (TEAM/FUTURES/SPOT/VOLUME/GENERAL), official URL,
    Decimal reward pool and currency, start/end/
    registration times (UTC, nullable), status
    (UPCOMING/ACTIVE/ENDED/CANCELLED/POSTPONED/
    UNKNOWN), eligible pairs and assets (JSON),
    rules/eligibility/multiplier lists (JSON, empty
    in Phase 5), source, verification status
    (official_website or needs_review), and a
    `metadata` JSON column with the normalised name
    used for change detection. Indexed on
    announcement, name, type, status, and dates.
  - `competition_trading_pairs` — normalised pairs,
    unique on (competition, pair), with base and
    quote assets.
  - `competition_rewards` — reward rows per
    competition (one row in Phase 5, only when the
    title states a pool).
  - `competition_rules` — rule rows per competition
    (empty in Phase 5; structure ready for later
    phases).
  - `competition_updates` — change history: creation,
    status, reward, and pairs changes, with old and
    new values.
  - `competition_collection_runs` — one row per
    scheduled processing run, with found/created/
    updated/skipped counts, status, and error message.
  - Telegram duplicate prevention for competitions
    reuses `campaign_notifications` with
    entity_type "competition" (unique on entity,
    entity id, and notification type); no separate
    notification table was created.
- Phase 6 volume tracker (migration `0007`):
  - `competition_volume_intervals` — one row per
    competition+pair+30-minute interval (unique on
    that triple), with public base/quote volumes,
    estimated eligible volume (only with a verified
    multiplier, else null), official eligible volume
    (always null in Phase 6), calculation method,
    data status (complete/partial/incomplete),
    recalculated flag, and collected time.
  - `competition_volume_checkpoints` — per-pair
    resume point (last interval end, last trade id),
    unique on competition+pair.
  - `competition_volume_collection_runs` — one row
    per competition per collection, with
    found/created/updated/skipped counts, status,
    and error message.
  - `competition_volume_reports` — one Telegram
    report attempt per competition+pair+interval
    (unique on that triple), with status
    (sent/failed/pending), sent time, and error
    message; a sent report is never re-sent.
  - `competition_pair_configurations` — per-pair
    multiplier (applied only when verified),
    tracking toggle, calculation method, and note,
    unique on competition+pair.
  All volume timestamps are UTC and all volume
  columns are Numeric (Decimal); see
  `docs/VOLUME_TRACKER.md`.
- Later phases add the market, futures, news,
  notification, template, and job tables, each with
  its own migration and the same UTC and uniqueness
  rules.
- Backups and restore procedures are documented in
  `docs/BACKUP_RESTORE.md`.

- Phase 7 tables (migration `0008`):
  - `market_watchlists` — symbol (unique), note.
  - `market_alerts` — symbol, alert_type, threshold,
    baseline/current price, change percent,
    triggered_at, cooldown_until, status, source;
    indexed by symbol, type, triggered time.
  - `news_sources` — name (unique), source_type,
    feed_url, enabled, reliability note.
  - `crypto_news` — source id, announcement id
    (unique where present), headline, summary
    (null when bodies unavailable), original URL
    (unique), publisher, category, related symbols
    (JSON), published at, fingerprint (unique),
    processing status.
  - `news_collection_runs` — source, started/
    completed, status, found/created/skipped,
    error message.
  - `market_collection_runs` — job name, started/
    completed, status, symbols requested/collected,
    error message.
  - `futures_market_ratios` — symbol, ratio_type
    (global_account, top_account, top_position,
    taker_buy_sell_volume), long/short values,
    long/short ratio, period, source, collected at.
  - Reused, not duplicated: `market_snapshots`
    for prices and `futures_snapshots` for funding,
    next funding time, mark price, and open
    interest.
