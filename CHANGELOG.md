# Changelog

## Phase 10 — Production Deployment Preparation (Stage A only)

- Harden Docker production configuration: non-root
  backend/frontend users, private named network,
  only Nginx on public 80/443, localhost-bound
  internal services, persistent volumes, healthchecks,
  restart policies, resource limits, capped logging,
  and a single-scheduler guarantee.
- Add Nginx production config (TLS 1.2/1.3, secure
  ciphers, security headers, HTTP→HTTPS redirect)
  with HSTS commented out until HTTPS is verified,
  plus scripts/setup-https.sh (Let's Encrypt webroot
  issuance, HTTPS verification, then HSTS, renewal).
- Add scripts/deploy.sh, backup.sh, restore.sh,
  health-check.sh, and production-check.sh (all
  `bash -n` validated; restore refuses production
  overwrite by default).
- Add trusted-proxy handling (TRUSTED_PROXIES,
  empty by default) and SSRF validation for
  integration test-connections; document the
  residual RSS DNS-rebinding window and the
  account-lockout trade-off honestly.
- Correct the CI workflow (backend, frontend,
  migration validation, safe config checks) — it
  remains local-only until manually installed, and
  no GitHub Actions run is claimed.
- Add docs/PRODUCTION_DEPLOYMENT_GUIDE.md and
  docs/PRODUCTION_CHECKLIST.md. Stage B (live VPS,
  domain, HTTPS, Docker/PostgreSQL/Redis
  verification, restore drill, live Telegram/
  Binance checks) is NOT started and is pending
  real infrastructure details.

## Phase 9 — Complete System Audit, Integration Testing & Security Hardening

- Audit the full system (backend, frontend, database,
  migrations 0001–0009, auth/RBAC, scheduler, Telegram,
  Binance clients, all processing modules, configuration,
  Docker, Compose, Nginx, docs, tests); full findings in
  `docs/PHASE_09_AUDIT_REPORT.md`.
- Fix a broken scheduler import that silently prevented
  paused-job restoration on restart; fix market overview
  returning 500 instead of 503 on database failure; narrow
  the scheduler trigger refusal to paused jobs only.
- Harden authentication and encryption: CORS `X-CSRF-Token`,
  production HSTS and docs lockdown, stable encryption
  key-version ids with legacy compatibility, settings key
  validation, generic lockout messages with dummy Argon2
  verify, password-reset session revocation and sibling
  token invalidation, and audited forgot-password.
- Fix reliability: naive-datetime normalisation, SSRF body
  cap with scheduler RSS through the SSRF fetcher,
  per-pair volume rollback, one-commit-per-entity
  intelligence processing, distinct-symbol snapshot and
  SQL `GROUP BY` news queries, PATCH duplicate 400s,
  custom-role assignment, and side-effect-free Binance
  status.
- Add migration 0010 with composite performance indexes
  (market alerts, market snapshots, futures snapshots,
  audit logs); historical migrations untouched.
- Add 20 cross-module integration tests
  (`backend/tests/test_phase9.py`); full suite 176 passed.
- Verify frontend HTTP integration on localhost (real
  backend + production frontend server): login, cookies,
  overview with real data, every admin section API,
  logout invalidation, unauthenticated denial. Browser
  automation was unavailable; this is HTTP-level
  integration, not browser end-to-end testing.
- Document honestly what is NOT VERIFIED: PostgreSQL,
  Redis, Docker, Nginx, HTTPS (HTTP-only, Phase 10 work),
  live Telegram delivery, live Futures data, and
  backup/restore runs, with exact verification commands.

## Phase 8 — Professional Admin Dashboard & Security

- Add administrator authentication and sessions:
  server-side sessions (HttpOnly cookie + CSRF token),
  Argon2id passwords, login lockout and rate limiting,
  session rotation/revocation, password change and
  single-use reset, and scripts/create_admin.py
  bootstrap with no default password.
- Add granular RBAC: admin_roles, admin_permissions,
  admin_role_permissions, admin_user_roles, seeded with
  4 roles and 32 permissions, enforced at the API layer
  with privilege-escalation and last-Super-Admin guards.
- Protect every manual collection endpoint (Phases 3-7)
  with collections.run plus CSRF; adapt earlier tests
  to authenticate without weakening assertions.
- Add AES-GCM credential encryption at rest for API
  integrations, masked responses, and key rotation.
- Add admin dashboard API (overview, activity, health,
  users, roles, Telegram, integrations, notifications,
  scheduler, audit logs, system settings, news sources)
  and a full Next.js admin frontend (login, reset,
  18 permission-filtered sections, real data only).
- Add migration 0009 (admin sessions, roles,
  permissions, reset tokens, login throttling fields,
  encrypted credential columns, audit extensions)
  with a verified SQLite upgrade/downgrade chain.
- Add RSS SSRF protection for news-source testing
  (scheme, resolved-IP, redirect revalidation, size
  and timeout limits) and security response headers.

## Phase 7 — Market, Futures & News Intelligence

- Add market, futures, and news models and
  migration 0008: `market_watchlists`,
  `market_alerts`, `news_sources`, `crypto_news`,
  `news_collection_runs`, `market_collection_runs`,
  `futures_market_ratios`. Market prices reuse
  `MarketSnapshot` and funding/open interest
  reuse `FuturesSnapshot`; no duplicate snapshot
  tables were created.
- Add `BinanceClient.get_all_tickers_24hr`
  (string values, Decimal-safe) and
  `get_futures_long_short` (global account, top
  account, top position, taker buy/sell volume,
  each labelled separately).
- Add market overview, gainers/losers with a
  minimum quote-volume filter, watchlist CRUD,
  movement detection with cooldown dedup, and
  stale-data flags.
- Add futures funding/open-interest collection
  with mandatory degraded mode on HTTP 451,
  funding alerts, open-interest change
  calculation, and labelled long/short ratios.
- Add news processing from Phase 3 announcements
  (no duplicates, classification, listing/
  delisting extraction, summaries null when
  bodies are unavailable) and a generic RSS
  collector with no third-party feed enabled by
  default.
- Add six scheduler jobs on the existing
  scheduler, `/market`, `/futures`, and `/news`
  API routers, Telegram market/futures/news
  commands, and home-page Market, Futures, and
  News sections with real data only.
- Live smoke test: Spot via the vision endpoint
  collected 5 symbols, news processing created
  140 items, Futures returned 502/unavailable
  (HTTP 451) with Spot unaffected.

## Phase 6 — Competition Volume Tracker

- Add volume models and migration 0007:
  `competition_volume_intervals`,
  `competition_volume_checkpoints`,
  `competition_volume_collection_runs`,
  `competition_volume_reports`, and
  `competition_pair_configurations`, with unique
  constraints, indexes, UTC timestamps, and Decimal
  volume fields. No old migration was modified.
- Add `BinanceClient.get_agg_trades` (Spot
  aggTrades, same retry/proxy/SSL patterns as the
  existing client), including two behaviours found
  live: the response carries no quote-quantity
  field, so quote volume is derived per trade as
  price x qty in Decimal, and fromId must not be
  combined with startTime/endTime.
- Add the 30-minute UTC interval engine, Decimal
  trade bucketing with trade-id dedup and
  competition-window filtering, partial-boundary
  handling, and cumulative volume computed only
  from stored intervals.
- Add collection/backfill with per-pair
  checkpoints, 24h lookback without a start date,
  a 48-interval per-pair per-run cap, a 50-page
  guard, idempotent upserts with late-trade
  recalculation, incomplete-vs-empty distinction,
  and per-pair failure isolation.
- Add one scheduler job on the existing
  APScheduler instance
  (`competition_volume_tracking`, every 30
  minutes, max_instances=1) that collects completed
  intervals and then runs Telegram reporting.
- Add Telegram volume reports (public, estimated
  with method, official "Unavailable", data status,
  cumulative volume, UTC + PKT periods) with
  sent-report duplicate prevention and failed
  report retry in place; incomplete intervals get
  no report. Live delivery not tested (no token).
- Add volume API endpoints (no `/api/v1` prefix,
  matching existing routers; the divergence is
  documented): interval list, per-competition
  intervals, pairs, history, summary, collection
  runs, and manual collect, with pagination,
  Decimal-as-string serialisation, and 404/502/503
  handling. Manual collect is not admin-gated
  until Phase 8.
- Add a Competition Volume section to the existing
  home page (selectors, latest and cumulative
  volumes, history table, Recharts chart — no new
  dependency), using only real backend data. The
  full Phase 8 dashboard is not built.
- Add settings `VOLUME_TRACKING_INTERVAL_MINUTES`,
  `VOLUME_BACKFILL_MAX_INTERVALS_PER_PAIR`,
  `VOLUME_MAX_PAGES_PER_INTERVAL`, and
  `VOLUME_NOTIFICATIONS_ENABLED`, and document
  the methodology in `docs/VOLUME_TRACKER.md`.

## Phase 5 — Binance Trading Competition Intelligence

- Add competition models and migration 0006:
  `competitions`, `competition_trading_pairs`,
  `competition_rewards`, `competition_rules`,
  `competition_updates`, and
  `competition_collection_runs`, with unique
  constraints, indexes, UTC timestamps, and Decimal
  financial fields. No volume tables: volume work is
  Phase 6.
- Add conservative title-only competition parsing:
  type classification (TEAM/FUTURES/SPOT/VOLUME/
  GENERAL), trading-pair and asset extraction, reward
  pools only for explicit amount-plus-currency in a
  reward title, dates only for explicit ISO date
  ranges, and UNKNOWN-by-default status with
  CANCELLED/POSTPONED/ENDED title signals only.
- Re-check the CMS article-detail endpoint
  (2026-10-30, live article, id/articleId/code
  parameters): still HTTP 400, code `000002
  "illegal parameter"`, so article bodies remain
  unavailable and detail fields stay unconfirmed.
- Add announcement-to-competition processing
  reusing the Phase 3 collector, with deduplication
  by announcement_id, discovery of ALPHA-category
  competition titles, lifecycle change detection by
  normalised name with a recorded update history,
  and date-based status recomputation that never
  overwrites CANCELLED/POSTPONED and never invents
  a transition from missing dates.
- Add Phase 5 API endpoints for competition list
  (type, status, pair, date range, name search,
  sorting), active, upcoming, completed, detail,
  updates, pairs, and manual collection, with
  pagination, Decimal-as-string serialisation, and
  404/502/503 handling. Manual collect is not
  admin-gated until Phase 8 and must sit behind
  deployment access controls.
- Add one idempotent scheduler job on the existing
  APScheduler instance (`competition_processing`,
  every 10 minutes, max_instances=1) that processes
  stored announcements and records a collection run.
- Add Telegram commands `/competition`,
  `/competition active`, `/competition upcoming`,
  `/competition completed`, and
  `/competition search <name>`, with Asia/Karachi
  (PKT) display times, confirmed-only reward pools
  and pairs, and notification formatters with
  duplicate prevention reusing
  `campaign_notifications` (entity_type
  "competition").
- Add a small real-data competition overview to the
  existing home page (active and upcoming
  competitions, or "None recorded yet").

## Phase 4 — Binance Alpha, Airdrop & Prime Sale Intelligence

- Add Alpha, airdrop, and Prime Sale models and
  migration 0005: `alpha_tokens`, `alpha_token_updates`,
  `airdrop_campaigns`, `airdrop_eligibility`,
  `prime_sales`, `prime_sale_allocation_rules`, and
  `campaign_notifications`, with unique constraints,
  indexes, UTC timestamps, and Decimal financial fields.
- Add title parsing for token name/symbol, contract
  addresses, and networks, with conservative status
  rules for airdrops and Prime Sales (anything not
  matching a listed phrase is UNKNOWN) and eligibility
  hints only for recognisable requirements. Removal
  announcements listing many tokens are recorded as
  multi-token removal announcements, never as a single
  fake token (found and fixed during live testing).
- Add announcement-to-module processing reusing the
  Phase 3 collector, with deduplication by
  announcement_id and Alpha market data from the
  Phase 2 Spot client; unavailable market data stays
  null with status "unavailable", never zero.
- Add a Decimal-only proportional allocation estimator
  for Prime Sales, labelled as an estimate, never a
  guarantee, rejecting missing or zero totals.
- Add Phase 4 API endpoints for Alpha tokens and
  updates, airdrops (including active), Prime Sales
  (including active), manual collection, and
  allocation estimation, with pagination, filtering,
  sorting, Decimal-as-string serialisation, 404/502/
  503 handling. Manual collect endpoints are not
  admin-gated until Phase 8 and must sit behind
  deployment access controls.
- Add three idempotent scheduler jobs on the existing
  APScheduler instance (Alpha, airdrop, Prime Sale
  processing, every 10 minutes, max_instances=1).
- Add Telegram commands `/alpha [token]`, `/airdrop`,
  `/airdrops active`, `/prime`, `/prime active`, and
  `/prime estimate <yours> <total> <allocation>`, plus
  notification formatters with duplicate prevention
  via `campaign_notifications`. Live Telegram delivery
  remains unverified (no token); mock formatting tests
  cover the messages.
- Add a small real-data frontend section (latest Alpha
  tokens, active airdrops, active Prime Sales, or
  "None recorded yet") — no dashboard, no fake data.
- Add `docs/ALPHA_INTELLIGENCE.md`,
  `docs/AIRDROP_INTELLIGENCE.md`, and
  `docs/PRIME_SALE_INTELLIGENCE.md`, and update API,
  Architecture, Database, Status, and Development Log
  documentation.
- No Phase 5 work (trading competitions or volume
  tracking) was implemented in this phase.

## Phase 3 — Announcement Monitor

- Add Binance website CMS announcement collector (GET
  article list, catalogs for listings, news, activities,
  delistings, maintenance, API updates, and airdrops),
  with the undocumented-endpoint limitation documented,
  not hidden.
- Add announcement models and migration 0004:
  announcement sources, announcements, and collection runs.
- Add category classification with high/medium/low
  confidence for 12 categories, extensible for later phases.
- Add duplicate detection by (source, external id) and
  canonical URL, with in-place updates on changed titles.
- Add scheduled collection (APScheduler, every 5 minutes,
  max_instances=1, idempotent registration) and manual
  collection API endpoints.
- Add announcement API endpoints with pagination, category,
  source, date, search, and sort filters, plus source
  configuration (PATCH) and collection-run listing.
- Add Telegram notification foundation: HTML messages,
  send-once marking, failure recording with up to 3
  attempts, and category enable/disable configuration.
  Live delivery remains unverified (no token); mock tests
  cover formatting, duplicates, and failures.
- Add a small "Latest announcements" section to the
  existing frontend home page, using real collected data.
- Add `docs/ANNOUNCEMENT_MONITOR.md` and update API,
  Architecture, Database, Status, and Development Log
  documentation.
- No Alpha, Airdrop, Prime Sale, or Competition modules
  were implemented in this phase; they reuse this
  foundation in later phases.

## Phase 1 + Phase 2 Bug-Fix Pass

- Start and stop the APScheduler scheduler from the API
  lifespan, including recovery from a previously closed event
  loop, and add lifespan tests.
- Run database migrations automatically on backend container
  start via `backend/entrypoint.sh` (`alembic upgrade head`
  before the API starts).
- Route the frontend through the `/api` proxy by default
  (Next.js rewrites, Nginx `/api/` proxy in production).
- Fail fast in production when `SECRET_KEY` is still the
  default placeholder, and tighten CORS methods and headers.
- Pick the Binance funding rate by latest funding time,
  not by last row position.
- Fix retry handling: non-numeric Retry-After no longer
  crashes, no sleep on the final attempt, and final 429/5xx
  errors report their real status and message.
- Store snapshot financial values as Numeric (Decimal) via
  migration `0003`, converting via string form on collection.
- Ping Spot and Futures concurrently in `/binance/status`.
- Add a JSON body contract to collect endpoints, a
  20-symbol limit, and a 503 for database failures.
- Add Redis-backed caching with an in-memory fallback for
  price, ticker, and klines, and a 120/minute per-IP rate
  limit on Binance routes.
- Add ruff and black configuration, a local check script,
  and 10 new tests for the fixes. (A GitHub Actions
  workflow file was prepared locally but could not be
  pushed via the GitHub integration; see PROJECT_STATUS.)
- Document issue classification in
  `docs/ISSUE_FIX_PLAN.md` and external verification steps
  in `docs/EXTERNAL_VERIFICATION.md`. Docker, live
  PostgreSQL, live Redis, live Telegram, and live Futures
  testing remain unverified and are documented, not faked.

## Phase 2 — Binance Market Integration

- Add Binance Spot API client with price, 24-hour ticker, and
  klines endpoints.
- Add Binance Futures API client with funding rate, premium
  index, and open interest endpoints.
- Add retry handling for transient Binance failures and
  honest error reporting for upstream failures.
- Add market and futures snapshot models and migration 0002.
- Add Binance API routes and collection endpoints.
- Add Binance connection monitoring via the status endpoint.
- Document the data-api.binance.vision alternative for
  restricted locations.

## Phase 1 — Project Foundation

- Set up backend project structure with FastAPI, configuration,
  logging, and database setup.
- Add database models and initial Alembic migration.
- Add backend health and readiness endpoints.
- Add Telegram bot connection structure with basic commands.
- Add APScheduler job registry.
- Create basic Next.js admin frontend with live backend health check.
- Configure Docker, Docker Compose, PostgreSQL, Redis, and Nginx.
- Add environment template and Phase 1 project documentation.
