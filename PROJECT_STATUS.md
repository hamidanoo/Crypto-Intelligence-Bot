# Project Status

- **Current phase:** Phase 3 — Announcement Monitor
- **Current branch:** `phase-03-announcement-monitor`, created from `fix-phase1-phase2-issues` at `b77f6f74323f8a941e18998261963c1f633ab656` (verified remotely before creation)
- **Latest commit:** `4e7882a1d3e208ab9d72d07b33a21cf683da926e` — "Add announcement API endpoints and status view", on `phase-03-announcement-monitor`, verified by reading the branch back after the push. A following status-update commit will head the branch after this file is pushed (see the Phase 3 report in chat). Earlier Phase 3 commits: `92378523f9ca2aa7b3a45779e5a7cee146c2ba56` (models), `dfd8eb39c999b90ca7392320eb5bf0111a849f6c` (collector).
- **Merged into main:** No. Merging requires explicit approval.

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
