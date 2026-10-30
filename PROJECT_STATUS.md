# Project Status

- **Current phase:** Phase 4 — Binance Alpha, Airdrop & Prime Sale Intelligence
- **Current branch:** `phase-04-alpha-airdrop-prime`, created from `phase-03-announcement-monitor` at `94c9f96fa51a8d495ffc7ef79163e0146a59cdc5` (verified remotely before creation)
- **Latest commit:** See the Phase 4 report for the verified branch head and each Phase 4 commit hash. This file follows the established pattern: a status file cannot contain its own commit hash, so the head commit is reported alongside this file, not inside it.
- **Merged into main:** No. Merging requires explicit approval.

## Completed features (Phase 4)

- Binance Alpha intelligence: Alpha tokens from ALPHA
  announcements, with token name/symbol, contract
  address, network, trading status/pairs,
  announcement URL/timestamp, metadata, data source,
  verification status, and Decimal market data from
  the Phase 2 Spot client when a SYMBOLUSDT ticker
  exists; otherwise price fields are null and market
  data status is "unavailable". Token updates record
  creation and price changes. Multi-token removal
  announcements are recorded as removal
  announcements, never as a single fake token.
- Binance Airdrop intelligence: campaigns from
  AIRDROP announcements with conservative statuses
  (UPCOMING/ACTIVE/ENDED/CLAIMING/
  DISTRIBUTION_COMPLETED/CANCELLED/UNKNOWN, UNKNOWN
  when no listed phrase matches), eligibility records
  only for recognisable title hints (all with
  unconfirmed details), and the API note "Eligibility
  details not officially confirmed." when a campaign
  has no eligibility records.
- Binance Prime Sale intelligence: sales from
  PRIME_SALE announcements with conservative statuses
  and null detail fields when titles do not contain
  them, one "unknown" allocation rule per sale, and a
  Decimal-only proportional allocation estimator
  labelled as an estimate, never a guarantee, that
  rejects missing or zero totals.
- Database models and migration `0005`:
  `alpha_tokens`, `alpha_token_updates`,
  `airdrop_campaigns`, `airdrop_eligibility`,
  `prime_sales`, `prime_sale_allocation_rules`, and
  `campaign_notifications`, with unique constraints,
  indexes, UTC timestamps, and Decimal fields.
- FastAPI endpoints: Alpha tokens, token detail,
  token updates, airdrop list/active/detail, Prime
  Sale list/active/detail, manual collection for
  each module (collect via Phase 3, then process),
  and allocation estimation. Pagination, filtering,
  sorting, Decimal-as-string serialisation, 404/502/
  503 handling. Manual collect endpoints are not
  admin-gated until Phase 8 and must sit behind
  deployment access controls.
- Scheduler: three new idempotent jobs on the
  existing APScheduler instance, each every 10
  minutes, max_instances=1: `alpha_processing`,
  `airdrop_processing`, `prime_sale_processing`.
  APScheduler remains single-instance only
  (documented).
- Telegram: commands `/alpha [token]`, `/airdrop`,
  `/airdrops active`, `/prime`, `/prime active`,
  `/prime estimate <yours> <total> <allocation>`,
  concise replies with source links where available
  and "None recorded yet" when empty, plus
  notification formatters with duplicate prevention
  via `campaign_notifications`. Live delivery was
  NOT tested (no token); mock formatting tests
  cover the messages.
- Frontend: a small real-data section on the
  existing home page (latest Alpha tokens, active
  airdrops, active Prime Sales, or "None recorded
  yet") — not a dashboard (Phase 8).
- Live smoke test: Alpha collect created 5, airdrop
  collect created 21, Prime Sale collect created 0
  (no Prime Sale announcements in the live first
  page). Live Prime Sale processing, live PostgreSQL
  migration `0005`, Docker Compose, and live Telegram
  delivery remain unverified and are documented, not
  faked.

## Completed features (Phase 3)

- Binance announcement collection from the official Binance
  website CMS feed (GET
  `/bapi/composite/v1/public/cms/article/list/query`,
  type=1), with catalogs for listings, news, activities,
  delistings, maintenance, API updates, and airdrops.
  The endpoint is undocumented (not a documented public
  API); that limitation is documented in
  `docs/ANNOUNCEMENT_MONITOR.md`, not hidden.
- Reusable collection engine: scheduled + manual collection,
  source-specific client, parsing and normalization to UTC,
  category classification with confidence, duplicate
  detection by (source, external id) and canonical URL,
  database persistence, collection-run tracking, retries,
  error logging, and restart recovery via re-registration
  and next-poll recovery.
- Database models and migration `0004`:
  `announcement_sources`, `announcements`,
  `collection_runs`, with uniqueness constraints and
  indexes, UTC timestamps, and Numeric-free text/JSON
  fields as documented in `docs/DATABASE.md`.
- Category classification for GENERAL, ALPHA, AIRDROP,
  PRIME_SALE, TRADING_COMPETITION, SPOT_LISTING,
  FUTURES_LISTING, DELISTING, DEPOSIT_WITHDRAWAL,
  NETWORK_MAINTENANCE, TOKEN_MIGRATION, and OTHER, with
  high/medium/low confidence. Uncertain announcements are
  OTHER/low, never a confirmed category they do not match.
- FastAPI announcement endpoints: list with pagination,
  category/source/date/search/sort filters, single
  announcement, categories with counts, sources,
  collection runs, manual collection (all or one source),
  and source configuration (PATCH). Database failures
  return 503.
- Scheduler: one job, `announcement_collection`, every 5
  minutes, max_instances=1, idempotent registration,
  collecting due enabled sources and then notifying.
  APScheduler remains single-instance only (documented).
- Telegram notification foundation: HTML messages with
  title, category, published time, source, and canonical
  link; only pending announcements are sent, successful
  sends are marked sent with a timestamp, failures are
  recorded and retried up to 3 attempts, categories can
  be enabled/disabled via
  `ANNOUNCEMENT_NOTIFICATION_CATEGORIES`. Live delivery
  was NOT tested (no token); mock sender tests cover
  formatting, duplicate prevention, and failure handling.
- Frontend: a small "Latest announcements" section on the
  existing home page, showing real collected data or
  "No announcements collected yet" — not a dashboard
  (Phase 8).

## Completed features (Phase 2, plus fixes)

- Binance Spot and Futures market data, retry handling,
  Decimal snapshot storage (migration `0003`), concurrent
  status checks, caching and rate limiting, and the
  `/binance/*` API routes. See the previous status for
  full details; all Phase 2 functionality is preserved
  in Phase 3.

## Completed features (Phase 1, plus fixes)

- FastAPI backend, health/readiness, Telegram bot structure,
  APScheduler registry, Next.js frontend, Docker Compose,
  and documentation. See the previous status for full
  details; all Phase 1 functionality is preserved.

## Pending features

- Phase 4 — Alpha / Airdrop / Prime Sale, and all later
  phases (5–10). No work from those phases has been started,
  and Phase 4 is NOT approved in this phase.

## Known issues and limitations (still open, not faked)

- The Binance CMS announcement endpoint is undocumented
  and may change or be blocked; failures are recorded as
  failed runs, never as fabricated data.
- Article body/detail is not fetched in Phase 3 (detail
  endpoint returned an error in investigation); summary
  and original_content are null.
- Classification is heuristic (see ANNOUNCEMENT_MONITOR.md).
- Live PostgreSQL migration `0004`, live Docker Compose
  run, live Telegram delivery, and a production-environment
  collection run are still unverified (SQLite migration,
  mock Telegram, and live CMS collection from this
  environment were verified — see below).
- Admin authentication for manual collection and source
  configuration is a Phase 8 feature; in Phase 3 those
  endpoints are not admin-gated and must only be exposed
  behind the deployment's own access controls.
- GitHub Actions workflow file `.github/workflows/ci.yml`
  remains local-only (GitHub App 403 for workflow files,
  documented in the fix pass); local checks run via
  `scripts/check.sh`.

## Latest test results

- Backend tests: `pytest` from `backend/` — 31 passed
  (22 Phase 1+2 tests, plus 9 Phase 3 tests covering
  source parsing, normalization, classification, duplicate
  detection, persistence, uniqueness, scheduler
  registration, retries, failure handling, manual
  collection endpoint, pagination/filtering, Telegram
  formatting, duplicate notification prevention,
  delivery failure handling, and database-failure 503).
- Lint/format: `ruff check`, `ruff format --check`, and
  `black --check` all pass.
- Alembic: `alembic upgrade head` against SQLite
  succeeded, `alembic current` reports `0004` (head),
  all 10 tables present.
- Live CMS collection via the running API (SQLite DB):
  first collect found 140 announcements (7 catalogs x
  20) and created 140; second collect created 0 and
  skipped 140 duplicates. Categories, sources, and
  collection runs endpoints all returned real data.
- Frontend: `npm run build` succeeded with the new
  announcements section.
- Full details are in `docs/DEVELOPMENT_LOG.md`.

## Next phase awaiting approval

Phase 4 — Alpha / Airdrop / Prime Sale. Do not start it
without explicit approval, for example: "Approved. Start
Phase 4."
