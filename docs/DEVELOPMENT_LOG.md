# Development Log

## Phase 1 — Project Foundation

### Repository inspection

The repository contained only `README.md` ("# Crypto-Intelligence-Bot")
and a Python `.gitignore`, on the default branch, with one initial
commit (`0949d74e74004ae8e06c6893341d31b3e49e7d9d`). No code,
branches, or other files existed. Phase 1 therefore started from a
clean foundation, and no existing work was overwritten except the
placeholder README, which was replaced with full project
documentation as specified for Phase 1.

### Implementation decisions

- Modular monolith, not microservices: one backend service owns the
  API, bot handlers, and scheduled jobs, with the frontend as a
  separate Next.js service behind Nginx. This keeps deployment and
  debugging simple at the current scale.
- APScheduler in-process for scheduled jobs, with Redis reserved for
  caching and deduplication keys in later phases. A distributed
  queue (for example Celery) was not introduced in Phase 1 because
  it would add a broker, worker, and failure modes with no Phase 1
  jobs to run. The scheduler registry is the single place where
  that decision would be revisited, with the change logged here.
- Timestamps are stored in UTC throughout. Display conversion to
  Asia/Karachi happens in the presentation layer in later phases.
- The `/health` endpoint does not depend on the database or Redis,
  so liveness stays available during a dependency outage.
  `/health/ready` reports each dependency separately and honestly
  returns "degraded" when one is unavailable.
- Secrets are not stored in plain text by design: the
  `ApiIntegration` model keeps only a masked key suffix and a
  secret reference. Credential encryption and dashboard masking are
  implemented in Phase 8, not faked in Phase 1.
- The bot does not start polling without a token, so the bot
  service does not enter a crash loop before configuration.

### Technical issues

- Docker was not available in the Phase 1 test environment
  (`docker: command not found`), so Docker services could not be
  started here. The Compose file was validated as YAML instead,
  and the Dockerfiles were reviewed for correct build contexts.
  A full Compose run on a Docker host remains an open verification
  item, recorded in `PROJECT_STATUS.md`.
- No PostgreSQL or Redis instance was available in the test
  environment, so readiness correctly reported both as
  unavailable. This is expected behaviour for the readiness
  endpoint, not a failure of the health endpoint.
- Initial dependency resolution failed: aiogram 3.15 requires
  pydantic below 2.10, which conflicted with the original
  pydantic 2.10.4 pin. The pin was changed to pydantic 2.9.2,
  with the reason recorded in `requirements.txt`, and
  installation then succeeded.
- The first Next.js version used (14.2.18) triggered an npm
  security-vulnerability warning. It was upgraded to 14.2.35
  before the final build, and the build passed on the upgraded
  version.
- The original FastAPI startup handler used the deprecated
  `on_event` API. It was replaced with a lifespan handler, and
  the deprecation warning is gone.

### Testing performed

- Backend automated tests: `pytest` from `backend/` — 2 passed.
- Backend startup: `uvicorn app.main:app` started and
  `GET /health` returned status `ok`.
- Backend readiness: `GET /health/ready` returned status
  `degraded` with database and Redis reported as unavailable,
  which is correct in an environment without those services.
- Alembic: `alembic history` shows migration `0001` as head.
  Migration execution against live PostgreSQL was not possible
  here (no PostgreSQL instance) and remains an open item.
- Frontend: dependencies installed with `npm install`,
  `npm run build` compiled successfully on Next.js 14.2.35,
  and `npm start` served the home page.
- Compose file: parsed and validated as YAML; services found
  were backend, bot, frontend, nginx, postgres, and redis.
- GitHub: branch and pushed commit verified by reading the branch
  back after the push (see the completion report).

### Important architectural changes

None in Phase 1 beyond the foundation described above.

## Phase 2 — Binance Market Integration

### Repository inspection

Phase 2 branched from `phase-01-foundation` at
`fcc147372f1a16b54fbfe11173e12958bd364c91`, so all Phase 1
work is inherited. No Phase 1 file was removed, and no later
phase work was started.

### Implementation decisions

- One shared `BinanceClient` for Spot and Futures, with
  separate base URLs, so the Spot endpoint can be pointed at
  data-api.binance.vision without changing client code.
- Public endpoints only, no API key. Collection endpoints
  persist one snapshot per symbol and commit once per batch.
- API routes use dependency injection for the client, so
  route tests can use a fake client while client tests use
  mock transports and live Spot data separately.
- Tracked symbols default to BTCUSDT, ETHUSDT, BNBUSDT,
  SOLUSDT, and XRPUSDT, configurable via `TRACKED_SYMBOLS`.

### Technical issues

- Binance main endpoints are restricted from this test
  environment: api.binance.com and fapi.binance.com return
  HTTP 451 with "Service unavailable from a restricted
  location". Spot data works via data-api.binance.vision.
  Futures live testing is therefore deferred to a VPS in an
  allowed location, and the status endpoint reports Futures
  as unavailable here rather than fabricating data.
- httpx proxy handling in this environment: ambient proxy
  variables include NO_PROXY entries such as "[::1]" that
  httpx fails to parse, and disabling trust_env also
  disabled the egress CA bundle. The client now passes an
  explicit proxy URL and an explicit SSL context loaded
  from the environment CA bundle when present, with
  trust_env disabled. Test transports bypass proxy and TLS
  entirely, so mock tests are unaffected.
- A test failure for an invalid symbol was caused by the
  fake client not validating symbols. The fake now validates
  like the real client, and the test passes.

### Testing performed

- Backend tests: `pytest` from `backend/` — 12 passed,
  covering health, client kline parsing, Binance error
  handling (including the 451 restricted-location case),
  SQLite persistence, and API routes with a fake client.
- Live Spot test via data-api.binance.vision: BTCUSDT price,
  ETHUSDT ticker, and BTCUSDT 1-hour klines returned real
  data through both the client and the running API.
- Live Futures test: funding rate, open interest, and
  premium index all returned the restricted-location error,
  which the API reports as HTTP 502 and the status endpoint
  reports as degraded with Spot ok and Futures unavailable.
- Alembic: `alembic history` shows migration `0002` as head.
  Live PostgreSQL execution remains an open item, as in
  Phase 1, because no PostgreSQL instance is available here.

## Phase 1 + Phase 2 Bug-Fix Pass

### Branch and classification

Branch `fix-phase1-phase2-issues` was created from
`phase-02-binance-integration` at
`6fa162a1e99c1d860d0f004f8eecf0e0ca19f8f3`, preserving all
Phase 1 and Phase 2 work. No Phase 3 work was started.
Issues were classified in `docs/ISSUE_FIX_PLAN.md` as
fixable here, requiring external infrastructure or
credentials, or not currently necessary for a later phase.
No scope was expanded: no dashboard pages, auth, or
Phase 3+ features were added.

### Fixes implemented

- Scheduler: `main.py` lifespan now calls
  `start_scheduler()` on startup and `shutdown_scheduler()`
  plus a loop tick on shutdown. APScheduler's asyncio
  shutdown is scheduled on the loop, not immediate, which
  was found by a failing test and is now handled in the
  lifespan and in the tests. A closed previous event loop
  is cleared before restarting, so a scheduler restart in
  the same process does not try to use a closed loop.
- Migrations: `backend/entrypoint.sh` runs
  `alembic upgrade head` before the API (or bot) starts in
  Docker, failing fast if the database is unavailable.
  The entrypoint script syntax was checked with `sh -n`.
- Frontend proxy: `frontend/next.config.js` rewrites
  `/api/:path*` to the backend, `NEXT_PUBLIC_API_URL`
  defaults to `/api`, and Compose sets
  `BACKEND_INTERNAL_URL=http://backend:8000` for the
  frontend service. A stale frontend server must be
  restarted after a config change; a fresh server was
  verified to proxy `GET /api/health` with HTTP 200.
- Production secret and CORS: a Pydantic model validator
  rejects `ENVIRONMENT=production` with the default secret,
  and CORS now allows an explicit method and header list.
- Funding rate: `get_funding_rate` now uses
  `max(rows, key=fundingTime)`.
- Retry: Retry-After parsing falls back to exponential
  backoff on a non-numeric value, the final attempt does
  not sleep, and final 429/5xx errors carry the real
  status and message instead of "None".
- Decimal precision: snapshot models now use
  `Numeric(28, 8)` (funding rate `Numeric(20, 10)`), with
  migration `0003` using batch alter so it also works on
  SQLite. The service converts floats via `str(value)` to
  Decimal before storage, so binary float error is not
  introduced on write. API display values remain JSON
  numbers (Decimal serialised as float in responses).
- Concurrent status: `/binance/status` uses
  `asyncio.gather` for Spot and Futures pings.
- API validation: collect endpoints now accept a JSON
  body (`CollectRequest`, max 20 symbols), fall back to
  tracked symbols when omitted, and return 503 on a
  database error instead of a raw 500. The service also
  enforces the 20-symbol limit.
- Cache and rate limiting: `app/cache.py` tries Redis
  first (1-second connect timeout) and falls back to an
  in-memory TTL cache, never failing a request on a cache
  error. `app/rate_limit.py` limits Binance routes to 120
  requests per minute per client IP, single-instance only;
  distributed limiting is documented for later.
- CI and formatting: `backend/pyproject.toml` (ruff line
  length 100, black) and `scripts/check.sh`. All backend
  code and tests were formatted with ruff format and black,
  and pass `ruff check`, `ruff format --check`, and
  `black --check`. A GitHub Actions workflow file was
  prepared locally (`.github/workflows/ci.yml`) with the
  same steps, but pushing it alone failed with GitHub 403
  "Resource not accessible by integration", while the rest
  of the fix push succeeded. The workflow file is therefore
  local-only until it is added manually or the GitHub App
  gains workflow write access; this is a permission limit,
  not a code failure.

### Testing performed in this fix pass

- Backend tests: `pytest` from `backend/` — 22 passed.
  Two initial failures were fixed, not hidden: the
  scheduler test needed an async context and a loop tick
  after shutdown, and the collect endpoint test needed a
  shared SQLite connection (StaticPool) because FastAPI
  runs endpoints in a different thread from the test.
- Alembic against SQLite: `alembic upgrade head`
  succeeded through `0003`, `alembic current` reports
  `0003` (head), and all 7 tables exist.
- Live Spot via data-api.binance.vision: BTCUSDT price
  77799.9, first call `"cached": false`, second call
  `"cached": true`; `/binance/status` Spot ok, Futures
  unavailable with the restricted-location message.
- Frontend: `npm run build` succeeded; a fresh
  `npm start` server on port 3001 proxied
  `GET /api/health` to the backend with HTTP 200.
- Not tested here, and documented in
  `docs/EXTERNAL_VERIFICATION.md` with exact commands:
  Docker Compose run, live PostgreSQL migrations,
  Redis-backed cache, live Telegram polling, and live
  Binance Futures.

## Phase 3 — Announcement Monitor

### Starting point verification

Branch `phase-03-announcement-monitor` was created from
`fix-phase1-phase2-issues` at
`b77f6f74323f8a941e18998261963c1f633ab656`, verified
remotely (list_commits head matched the expected hash)
before creation. It was not created from main, and no
previous branch was merged or deleted.

### Source investigation

- Binance support HTML page returned HTTP 202
  (challenge page) and carries no structured data.
- CMS POST to the same path timed out in this
  environment; CMS GET succeeded with HTTP 200.
- CMS GET
  `/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=5`
  returned code `000000` with 7 catalogs (48, 49, 93,
  161, 157, 51, 128), 5 articles each, each with id,
  code, title, and releaseDate in milliseconds, and no
  duplicates across catalogs.
- Catalog-specific endpoint
  `/article/catalog/list/query` returned articles without
  releaseDate, so the list endpoint is used as primary.
- Article detail endpoint tried returned code `000002`
  "illegal parameter", so Phase 3 does not fetch article
  bodies; summary and original_content remain null.
- Canonical URL pattern (slug + code) was verified live
  for one article (HTTP 202 with the correct URL).
- api.binance.com / fapi.binance.com have no
  announcement endpoint; they are market data only.

### Implementation decisions

- One scheduler job, not one job per source, with
  per-source due checking, so polling intervals are
  configurable without multiplying jobs or risking
  overlaps (max_instances=1).
- Deduplication by (source, external id) and canonical
  URL, with in-place updates on title/category changes.
- Category confidence is separate from source
  verification: "official_website" means the record came
  from binance.com, not that the category is confirmed.
- Telegram messages use HTML with escaped titles, to
  avoid Markdown escaping failures on special characters.
- Admin authentication is NOT faked in Phase 3: manual
  collection and source configuration endpoints are
  documented as ungated until Phase 8, and must be
  exposed only behind deployment access controls.
- Frontend scope is limited to a latest-announcements
  section on the home page; no dashboard was built.

### Technical issues

- Read endpoints initially returned 500 on database
  failure, because the failure occurred inside the query,
  not in the endpoint wrapper for some paths. All
  announcement read endpoints now catch SQLAlchemyError
  and return 503, with a test using a failing query
  object (a dependency that raises before yielding
  would bypass the endpoint handler entirely, which is
  why the test uses a failing session instead).
- APScheduler shutdown timing (from the fix pass) and
  the closed-loop restart handling were reused unchanged;
  scheduler registration tests confirm idempotence.
- A stale frontend server must be restarted after a
  config change (observed in the fix pass); the Phase 3
  frontend build was verified with a fresh build.

### Testing performed

- Backend tests: `pytest` from `backend/` — 31 passed
  (22 Phase 1+2, 9 Phase 3).
- Alembic against SQLite: upgrade to `0004` succeeded,
  current reports `0004` (head), 10 tables present.
- Live CMS collection via the running API with a SQLite
  database: first collect found 140, created 140;
  second collect created 0, skipped 140 duplicates;
  categories, sources, and collection runs endpoints
  returned real data.
- Frontend: `npm run build` succeeded.
- Not tested live: PostgreSQL migration `0004`, Docker
  Compose run, Telegram delivery (mock only), and a
  production-environment collection run. See
  `docs/ANNOUNCEMENT_MONITOR.md`.

## Phase 4 — Binance Alpha, Airdrop & Prime Sale Intelligence

### Starting point verification

Phase 4 was branched from `phase-03-announcement-monitor`
at `94c9f96fa51a8d495ffc7ef79163e0146a59cdc5`, the
verified Phase 3 head. No Phase 5 work, no merge into
main, no history rewrite, and no branch deletion were
performed in this phase.

### Implementation decisions

- The Phase 3 collector was reused unchanged: Phase 4
  processing reads announcements the collector already
  stored, by category, and creates at most one module
  record per announcement. Scheduler jobs process
  stored announcements rather than re-fetching the CMS
  feed, so collection is not quadrupled.
- Title parsing is deliberately conservative, because
  announcement bodies are not fetched. A field that is
  not in the title is null, a status that does not
  match a listed phrase is UNKNOWN, and an allocation
  rule that is not stated is "unknown". The estimate
  endpoint then requires the caller to supply verified
  inputs, including the total commitment.
- Alpha market data uses the existing Phase 2 Spot
  client, with the symbol's USDT pair. A failed lookup
  (including a 400 for a symbol that does not trade on
  Spot) leaves price fields null, never zero.
- Allocation arithmetic uses Decimal only, and the
  result is labelled an estimate in the API, the bot,
  and the documentation.

### Technical issues

- Live smoke testing found that the current CMS first
  page contains no PRIME_SALE announcements, 21 AIRDROP
  announcements (mostly distribution completions, all
  UNKNOWN under the conservative rules), and only 5
  ALPHA announcements — trading competitions and
  removal lists, not new token listings. The parser
  initially turned a removal list into a single fake
  token name (the text before the first parenthesis).
  It was corrected: removal announcements are now
  recorded as multi-token removal announcements with
  no symbol, and competition titles are cleaned to the
  token name (for example "Axis Robotics").
- Numeric(28, 8) serialisation: a Decimal price of
  2.50 serialises as "2.50000000" and an estimate of
  250 serialises as "250.00" in some paths, because
  Decimal preserves exponent. Tests were corrected to
  compare Decimal values, not string spellings; the
  API contract is Decimal-as-string, not a fixed
  number of decimal places.

### Testing performed

- Backend tests: `pytest` from `backend/` — 52 passed
  (31 Phase 1+2+3, 21 Phase 4; the Phase 4 file
  contains 21 tests including parsing, allocation,
  processing, notifications, scheduler registration,
  API, and bot tests).
- Lint/format: `ruff check`, `ruff format --check`,
  and `black --check` all pass.
- Alembic against SQLite: upgrade to `0005`
  succeeded, current reports `0005` (head), 17 data
  tables present (10 Phase 1–3 + 7 Phase 4).
- Live CMS smoke test via the running API with a
  SQLite database and Spot data via
  data-api.binance.vision: first `/alpha/collect`
  created 5 Alpha records, `/airdrops/collect`
  created 21 campaigns, `/prime-sales/collect`
  created 0 (no Prime Sale announcements in the live
  first page). Alpha market data was unavailable for
  the live symbols (400 from Spot for non-trading
  symbols), correctly recorded as null/unavailable.
- Frontend: `npm run build` succeeded.
- Not tested live: PostgreSQL migration `0005`,
  Docker Compose run, Telegram delivery (mock only),
  a production-environment run, and live Prime Sale
  processing against a real Prime Sale announcement.
  See docs/ALPHA_INTELLIGENCE.md,
  docs/AIRDROP_INTELLIGENCE.md, and
  docs/PRIME_SALE_INTELLIGENCE.md.

## Phase 5 — Binance Trading Competition Intelligence

### Decisions

- Competition discovery processes TRADING_COMPETITION
  announcements plus ALPHA announcements whose title
  contains "competition". The Phase 3 classifier's
  "binance alpha" rule runs before its "competition"
  rule, so "Binance Alpha Trading Competition" titles
  are classified ALPHA; changing the classifier order
  would break Phase 3/4 behaviour, so the processing
  query covers both categories instead.
- Article-detail re-check (2026-10-30, live article
  id 288627, parameters id, articleId, and code):
  still HTTP 400 with CMS code 000002 "illegal
  parameter". Phase 5 therefore works from titles and
  catalog metadata only, exactly as Phase 3/4 did.
- Change detection matches on a normalised name with
  lifecycle suffixes ("has been cancelled", and so
  on) stripped, because a cancellation title is built
  on the original name plus a suffix. Prefix matching
  is allowed only for lifecycle announcements, never
  for plain new competitions, so two distinct
  competitions are not merged by a shared prefix.
- Telegram duplicate prevention reuses the Phase 4
  `campaign_notifications` table with entity_type
  "competition" instead of a second identical table.
- Reward parsing deliberately does not handle K/M
  suffixes or currency-less amounts: "$200K Worth of
  Rewards" stays null, as the live smoke test showed.
  Converting it would require assuming a multiplier
  and a currency.

### Bugs found and fixed during testing

- SQLite returns naive datetimes while PostgreSQL
  returns aware ones, so `recompute_status` raised
  "can't compare offset-naive and offset-aware
  datetimes" on the date test. The function now
  normalises naive start/end times to aware UTC
  before comparison. This also affects any later
  date logic and is worth remembering whenever a
  stored datetime is compared in tests.
- Two test expectations (not code) were wrong after
  name cleaning: cleaned competition names drop the
  "Binance Futures/Spot" prefix, so "Futures Trading
  Competition" and a "Spot" name search do not match
  stored names. The tests were corrected to the
  stored names and to Type: FUTURES / ETHUSDT
  searches; the cleaning behaviour itself is
  intended.

### Testing performed

- Backend tests: `pytest` from `backend/` — 75 passed
  (52 Phase 1–4, 23 Phase 5; the Phase 5 file
  contains 23 tests including parsing, type
  classification, date/timezone handling, reward and
  pair extraction, missing information, duplicate
  prevention, persistence, unique constraints, status
  transitions, postponement, cancellation, updates,
  scheduler registration, collection runs, API
  pagination/filtering/sorting, Telegram formatting,
  duplicate notification prevention, DB-failure 503,
  and bot commands).
- Lint/format: `ruff check`, `ruff format --check`,
  and `black --check` all pass.
- Alembic against SQLite: upgrade to `0006`
  succeeded, current reports `0006` (head), 23 data
  tables present (17 Phase 1–4 + 6 Phase 5).
- Live CMS smoke test via the running API with a
  SQLite database: first `/competitions/collect`
  found 2 and created 2 (Alpha trading competitions
  for Axis Robotics and Orochi Network; the live
  first page held 140 announcements, none classified
  TRADING_COMPETITION), second collect skipped 2
  duplicates. Reward pools stayed null for "$200K
  Worth of Rewards" (no currency code, K suffix).
- Frontend: `npm run build` succeeded.
- Not tested live: PostgreSQL migration `0006`,
  Docker Compose run, Telegram delivery (mock only),
  a production-environment scheduler run, and live
  processing of a non-Alpha (TRADING_COMPETITION)
  competition announcement. See
  docs/COMPETITION_INTELLIGENCE.md.

## Phase 6 — Competition Volume Tracker (2026-10-30)

- Implemented 30-minute UTC volume tracking for
  Phase 5 competitions on branch
  `phase-06-volume-tracker` (from Phase 5 head
  `93d4ee67`): models + migration `0007`, interval
  engine, aggTrades collection/backfill, scheduler
  job `competition_volume_tracking` (30 minutes,
  max_instances=1), Telegram interval reports,
  `/competition-volume` API routes (no `/api/v1`
  prefix, per existing router conventions; the
  divergence is documented in `docs/API.md` and
  `docs/VOLUME_TRACKER.md`), and a Competition
  Volume section on the home page (Recharts chart,
  already a dependency).
- Decisions: aggTrades over klines (boundary
  accuracy) and over rolling-24h-ticker subtraction
  (forbidden, never used); public vs estimated
  (verified multiplier only) vs official (always
  null in Phase 6) kept strictly separate in code,
  API, Telegram, and frontend; cumulative volume
  only from stored intervals; checkpoint advances
  only over a contiguous complete/partial prefix so
  an incomplete interval is retried next run.
- Live findings that changed the code (both covered
  by tests): aggTrades has no quote-quantity field,
  so quote volume is derived as Decimal(price) x
  Decimal(qty) per trade; Binance rejects fromId
  combined with startTime/endTime, so collection
  pages windowed first, then fromId-only, with
  bucketing filtering every page to the interval.
- Live smoke test via `data-api.binance.vision`
  (BTCUSDT 10:00–10:30 UTC 2026-10-30): 26,000
  trades fetched, 24,208 in-interval after
  bucketing, base 426.84376 BTC, quote
  33,070,381.6869031 USDT. `api.binance.com`
  returned HTTP 451 code 0 (restricted location).
  No competition interval was written from it.
- Tests: full suite 103 passed (29 new Phase 6
  tests); `ruff check`, `ruff format --check`,
  `black --check` pass; Alembic upgrade to `0007`
  against SQLite succeeded (29 tables); `npm run
  build` succeeded.
- Not verified live: PostgreSQL migration `0007`,
  Docker run, Telegram delivery (mock only),
  production scheduler run, official eligible volume
  source, leaderboard data. Manual collect remains
  ungated until Phase 8 auth. Phase 7 NOT started.
