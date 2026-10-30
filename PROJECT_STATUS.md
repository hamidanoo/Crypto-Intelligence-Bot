# Project Status

- **Current phase:** Phase 7 — Market, Futures & News Intelligence
- **Current branch:** `phase-07-market-futures-news`, created from `phase-06-volume-tracker` at `6d2a49798831057e6d230801d180693c32870dd9` (verified remotely before creation)
- **Latest commit:** See the Phase 7 report for the verified branch head and each Phase 7 commit hash. This file follows the established pattern: a status file cannot contain its own commit hash, so the head commit is reported alongside this file, not inside it.
- **Merged into main:** No. Merging requires explicit approval.

## Completed features (Phase 7)

- Market intelligence: overview from latest
  `MarketSnapshot` rows with stale flags, top 10
  gainers/losers with a minimum quote-volume
  filter (low-liquidity symbols excluded, counted,
  never presented as opportunities), watchlist
  CRUD, and price/volume movement detection with
  cooldown dedup (one alert per symbol + type per
  60 minutes). Prices are never described as
  trading opportunities.
- Futures intelligence: funding rates and open
  interest reuse `FuturesSnapshot`; long/short
  ratios are new (`futures_market_ratios`) with
  account, position, and taker datasets labelled
  separately, never merged. Degraded mode is
  mandatory: fapi HTTP 451 is recorded as
  degraded/unavailable and never breaks Spot
  collection or the app.
- News intelligence: `CryptoNews` built from
  Phase 3 announcements (no duplicates, unique
  announcement id / URL / fingerprint), keyword
  + category classification, listing/delisting
  extraction from titles, summaries null when
  article bodies are unavailable (never invented),
  and a generic RSS collector driven by
  `NewsSource` rows with no third-party feed
  enabled by default.
- Database migration `0008`: `market_watchlists`,
  `market_alerts`, `news_sources`, `crypto_news`,
  `news_collection_runs`, `market_collection_runs`,
  `futures_market_ratios`. No old migration was
  modified.
- Six new scheduler jobs on the existing
  scheduler (market snapshot, funding, open
  interest, news, listing processing, movement
  detection), each `max_instances=1`.
- APIs `/market`, `/futures`, `/news` (no
  `/api/v1` prefix, matching existing routers),
  Telegram commands, and home-page Market,
  Futures, and News sections with real data only.
- Live smoke test: Spot collection via the
  vision endpoint collected 5 symbols, news
  processing created 140 items from 140
  announcements, and Futures collection returned
  502/unavailable (HTTP 451), with the summary
  reporting unavailable — Spot unaffected.
- External verification still required: live
  PostgreSQL migration 0008, Docker run, live
  Telegram delivery, production scheduler run,
  and live Futures from an allowed location.

## Completed features (Phase 6)

- Competition volume tracker: 30-minute UTC
  intervals for Phase 5 competitions, from Binance
  Spot aggTrades (trade-level data, so competition
  start/end boundaries are exact). Klines are never
  substituted and rolling-24h-ticker subtraction is
  never used. Full methodology, including the
  public vs estimated vs official distinction, is in
  `docs/VOLUME_TRACKER.md`.
- Accuracy rules enforced in code, API, Telegram,
  and frontend: public market volume from public
  trade data; estimated eligible volume only with a
  verified multiplier configuration, otherwise null;
  official eligible volume always null in Phase 6
  (displayed "Unavailable", never zero); official
  leaderboard data not implemented, never claimed.
- Database models and migration `0007`:
  `competition_volume_intervals`,
  `competition_volume_checkpoints`,
  `competition_volume_collection_runs`,
  `competition_volume_reports`, and
  `competition_pair_configurations`, with unique
  constraints, indexes, UTC timestamps, and Decimal
  fields. No old migration was modified.
- Interval engine: 30-minute UTC boundaries,
  completed-intervals-only processing, boundary
  intervals marked partial with only in-window
  trades counted, Decimal bucketing with trade-id
  dedup, and cumulative volume computed only by
  summing stored intervals (reproducible, verified
  against a DB-side SUM in tests).
- Collection/backfill: per-pair checkpoints, last
  24h lookback when no start date exists, 48
  intervals per pair per run cap, 50-page
  aggTrades page guard, idempotent upserts with
  late-trade recalculation (no duplicates, no
  re-sent reports), incomplete intervals with null
  volumes on fetch failure vs Decimal 0 with
  complete status on a genuinely empty window, and
  per-pair failure isolation with errors on the run.
  Two live aggTrades behaviours were found and
  handled: no quote-quantity field (quote volume
  derived as price x qty in Decimal) and the
  forbidden fromId+time-window combination (first
  page windowed, later pages fromId-only).
- Scheduler: one new idempotent job on the existing
  APScheduler instance,
  `competition_volume_tracking`, every 30 minutes,
  max_instances=1, coalesce=True, collecting
  completed intervals then running the reporting
  pass. APScheduler remains single-instance only
  (documented).
- Telegram: interval reports with competition name,
  UTC + PKT reporting period, pair, public volume,
  estimated eligible volume (value + method, or
  "Unavailable"), official eligible volume
  ("Unavailable"), data status, last updated UTC,
  cumulative public volume, and calculation method
  "Binance public trade data (aggTrades)".
  Incomplete intervals get no report; sent reports
  are never re-sent (unique constraint + status
  check); failed reports are recorded and may be
  retried in place. Gated by
  `VOLUME_NOTIFICATIONS_ENABLED` plus token/group
  configuration. Live delivery was NOT tested (no
  token); mock-format tests cover the messages.
- FastAPI endpoints (no `/api/v1` prefix, matching
  existing routers; the frontend proxy maps
  `/api/competition-volume` to these routes — the
  divergence is documented in `docs/API.md` and
  `docs/VOLUME_TRACKER.md`): interval list
  (competition, pair, date range, data status,
  pagination, sorting), per-competition intervals,
  pairs, history, summary (per-pair latest interval
  + cumulative volumes + last collection), collection
  runs, and manual collect (global and per
  competition) with 502 on upstream failure and 503
  on database errors. Decimals as strings. Manual
  collect is not admin-gated until Phase 8 and must
  sit behind deployment access controls.
- Frontend: a Competition Volume section on the
  existing home page (competition and pair
  selectors, latest completed volume, cumulative
  public volume, estimated eligible volume when
  available, official eligible volume as
  Unavailable, interval history table, Recharts bar
  chart of public quote volume — Recharts was
  already a dependency, no new dependency added,
  data-completeness indicators, last collection
  timestamp, UTC and PKT labels), using only real
  backend data. This is not the full Phase 8
  dashboard.
- New settings (all implemented, in `.env.example`):
  `VOLUME_TRACKING_INTERVAL_MINUTES=30`,
  `VOLUME_BACKFILL_MAX_INTERVALS_PER_PAIR=48`,
  `VOLUME_MAX_PAGES_PER_INTERVAL=50`,
  `VOLUME_NOTIFICATIONS_ENABLED=true`.

## Completed features (Phase 5)

- Binance trading competition intelligence: competitions
  discovered from TRADING_COMPETITION announcements,
  plus ALPHA announcements whose title contains
  "competition" (the Phase 3 classifier marks "Binance
  Alpha Trading Competition" titles ALPHA, so without
  this rule they would be missed; the classifier order
  itself was not changed). No volume work: no
  30-minute aggregation, no cumulative or
  multiplier-adjusted volume reports — that is Phase 6.
- Conservative title-only extraction: competition
  type (TEAM/FUTURES/SPOT/VOLUME/GENERAL, in that
  order), trading pairs and base assets, reward pool
  only for an explicit amount plus currency in a
  reward/prize/pool title (Decimal), dates only for
  an explicit ISO date range (UTC). Everything else
  is null, empty, or UNKNOWN. Unreliable names are
  still created with verification status
  "needs_review", never dropped silently or given
  invented details.
- Article-detail endpoint re-checked 2026-10-30
  against a live article (id 288627, via id,
  articleId, and code parameters): still HTTP 400,
  CMS code `000002 "illegal parameter"`. Article
  bodies remain unavailable, so detail fields stay
  unconfirmed.
- Lifecycle: UNKNOWN by default; title signals for
  CANCELLED/POSTPONED/ENDED only; date-based
  recomputation (UPCOMING/ACTIVE/ENDED) only when
  both dates exist, with CANCELLED/POSTPONED
  terminal. Later announcements with the same
  normalised name (lifecycle suffixes stripped for
  matching, prefix matching only for lifecycle
  announcements) update the existing competition
  and record a CompetitionUpdate per changed field,
  instead of silently overwriting or duplicating.
- Database models and migration `0006`:
  `competitions`, `competition_trading_pairs`,
  `competition_rewards`, `competition_rules`,
  `competition_updates`, and
  `competition_collection_runs`, with unique
  constraints, indexes, UTC timestamps, and Decimal
  fields. Telegram duplicate prevention reuses
  `campaign_notifications` with entity_type
  "competition".
- FastAPI endpoints: competition list (type, status,
  pair, date range, name search, sorting), active,
  upcoming, completed, detail (with
  `duration_seconds`), updates timeline, pairs/
  rewards/rules, and manual collection (collect via
  Phase 3, then process). Pagination, Decimal-as-
  string serialisation, 404/502/503 handling.
  Manual collect is not admin-gated until Phase 8
  and must sit behind deployment access controls.
- Scheduler: one new idempotent job on the existing
  APScheduler instance, `competition_processing`,
  every 10 minutes, max_instances=1, processing
  stored announcements and recording a collection
  run; it does not re-fetch the CMS feed.
  APScheduler remains single-instance only
  (documented).
- Telegram: commands `/competition`,
  `/competition active`, `/competition upcoming`,
  `/competition completed`,
  `/competition search <name>`, with Asia/Karachi
  (PKT) display times when dates exist, reward pools
  and pairs only when confirmed, and "None recorded
  yet" when empty; plus notification formatters for
  new, starting, ending soon, postponed, cancelled,
  and rule/reward changes. Live delivery was NOT
  tested (no token); mock formatting tests cover
  the messages.
- Frontend: a small real-data section on the
  existing home page (active and upcoming
  competitions, or "None recorded yet") — not a
  dashboard (Phase 8).
- Live smoke test: first `/competitions/collect`
  found 2 and created 2 (Alpha trading competitions
  for Axis Robotics and Orochi Network; no
  TRADING_COMPETITION announcements in the live
  first page, which held 140 announcements), second
  collect skipped 2 duplicates. Reward pools stayed
  null for "$200K Worth of Rewards" (no currency
  code, K suffix — not parsed under the
  conservative rule). Live PostgreSQL migration
  `0006`, Docker Compose, live Telegram delivery,
  and a production-environment scheduler run remain
  unverified and are documented, not faked.

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

- Phase 7 and all later phases (7–10). No work
  from those phases has been started, and Phase 7
  is NOT approved in this phase. The full Phase 8
  dashboard is not built; Phase 6 adds only a
  Competition Volume section to the home page.

## Known issues and limitations (still open, not faked)

- The Binance CMS announcement endpoint is undocumented
  and may change or be blocked; failures are recorded as
  failed runs, never as fabricated data.
- Article body/detail is not fetched in Phase 3 (detail
  endpoint returned an error in investigation); summary
  and original_content are null.
- Classification is heuristic (see ANNOUNCEMENT_MONITOR.md).
- Live PostgreSQL migrations `0004`–`0007`, live
  Docker Compose run, live Telegram delivery, and
  a production-environment collection run are still
  unverified (SQLite migration to `0007`, mock
  Telegram, live CMS collection, and live aggTrades
  via `data-api.binance.vision` from this
  environment were verified — see below).
- Admin authentication for manual collection and
  source configuration is a Phase 8 feature; in
  Phases 3–6 those endpoints are not admin-gated
  and must only be exposed behind the deployment's
  own access controls.
- No official eligible volume source and no
  leaderboard source is implemented in Phase 6;
  both stay "Unavailable"/unclaimed until a
  verified source exists.
- GitHub Actions workflow file `.github/workflows/ci.yml`
  remains local-only (GitHub App 403 for workflow files,
  documented in the fix pass); local checks run via
  `scripts/check.sh`.

## Latest test results

- Backend tests: `pytest` from `backend/` — 103
  passed (74 Phase 1–5 tests, plus 29 Phase 6
  tests covering interval boundaries, UTC handling,
  competition-window filtering, Decimal precision,
  multiple pairs/competitions, trade dedup,
  duplicate interval prevention, cumulative
  calculations, late-trade recalculation, checkpoint
  backfill and incomplete recovery, partial API
  failures, 429 retry, fromId paging and the
  forbidden fromId+time-window combination, verified
  vs unverified multipliers, quote-asset handling,
  missing rules, incomplete vs empty windows,
  scheduler overlap prevention, duplicate Telegram
  report prevention, API filters/pagination, and
  database-failure 503).
- Lint/format: `ruff check`, `ruff format --check`, and
  `black --check` all pass.
- Alembic: `alembic upgrade head` against SQLite
  succeeded, `alembic current` reports `0007` (head),
  all 29 tables present (including the 5 Phase 6
  tables).
- Live aggTrades smoke test via
  `data-api.binance.vision` (2026-10-30): BTCUSDT
  10:00–10:30 UTC fetched 26,000 trades across 26
  pages, bucketed to 24,208 in-interval trades:
  base 426.84376 BTC, quote 33,070,381.6869031 USDT.
  Same call via `api.binance.com`: HTTP 451, code 0
  (restricted location). No competition interval
  was written from this smoke test.
- Frontend: `npm run build` succeeded with the new
  Competition Volume section.
- Full details are in `docs/DEVELOPMENT_LOG.md`.

## Next phase awaiting approval

Phase 7. Do not start it without explicit approval.
