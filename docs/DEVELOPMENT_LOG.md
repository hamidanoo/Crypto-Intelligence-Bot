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
