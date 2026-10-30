# Phase 9 Audit Report — Complete System Audit, Integration Testing & Security Hardening

Branch: `phase-09-integration-security-audit` (from `phase-08-admin-dashboard-security` at `aa33ba8d`).
Scope: audit and hardening only. No major new feature was introduced, no
migration 0001–0009 was modified, no branch was merged or deleted, and no
history was rewritten.

## 1. Audit scope

Inspected in full: backend architecture and every API router, auth/RBAC
(`backend/app/auth/`), the scheduler and all 12 registered jobs, Telegram
handlers for every command from Phases 1–8, Binance Spot and Futures
clients, announcement / competition / volume / market / futures / news
processing, configuration, Dockerfiles, docker-compose, Nginx config,
frontend architecture and all 18 admin sections, docs, and tests.
Verification performed (see §5 for exact results):

- Alembic migration chain 0001→0010 on a fresh SQLite database, including
  downgrade and re-upgrade.
- Full backend test suite, lint, and format checks.
- Security re-audit with tests: Argon2id, sessions, password reset,
  throttling/lockout, cookies, CSRF, RBAC for all four roles, CORS,
  security headers, rate limits, input validation, AES-GCM encryption
  and key rotation.
- Cross-module integration tests with mocked external services
  (`backend/tests/test_phase9.py`).
- Scheduler reliability tests: double registration, paused-job restore,
  paused-job trigger refusal, job allowlist.
- Frontend HTTP integration: real backend on localhost with a SQLite
  database plus the frontend production server, verified over HTTP
  (login, cookies, `/auth/me`, overview, every admin section API,
  logout, unauthenticated denial). Browser automation was unavailable
  in this environment, so no browser end-to-end claim is made.
- Secrets scan of the full tree before pushing.

## 2. Findings by severity

### Critical

None found. No SQL injection via raw SQL (all queries go through the
ORM), no plaintext secret in the database or in logs, no unauthenticated
state-changing admin route, and no auth token stored in browser storage
(the frontend uses `localStorage` only for the theme key `ci-theme`).

### High

- **H-1 — Paused scheduler jobs silently resumed on restart (fixed).**
  `backend/app/scheduler.py` imported `get_setting` from
  `app.admin_common`, a module that does not exist (the real module is
  `app.api.admin_common`). The import always failed, the surrounding
  `except` swallowed it, and paused-job restoration never ran: a job an
  administrator had paused would run again after a restart while the
  dashboard still showed it paused. Fixed by correcting the import;
  proven by `test_scheduler_register_twice_and_paused_restore`, which
  registers jobs with a persisted paused flag and asserts the job's
  `next_run_time` is `None`, plus double-registration idempotence
  (12 jobs before and after a second registration).
- **H-2 — HTTPS is not configured (remaining risk, Phase 10 work).**
  Nginx serves HTTP only and there is no TLS termination. The backend
  already sets HSTS and `Secure` cookies in production, but those only
  take effect once HTTPS exists. The system must not be exposed publicly
  until Phase 10 adds TLS. See §7.

### Medium

- **M-1 — Market overview returned 500 instead of 503 on database
  failure (fixed).** The Phase 9 distinct-symbols optimisation in
  `latest_snapshots_by_symbol` called `.distinct()` before `.order_by()`,
  so a failing database surfaced `AttributeError` instead of the
  `SQLAlchemyError` the API layer maps to 503. Reordered to
  `.order_by(...).distinct()` (semantically identical for a
  single-column distinct query). Proven by the pre-existing
  `test_db_failure_503`, which now passes again without any change to
  the test.
- **M-2 — Scheduler trigger refused trigger-while-stopped (fixed by
  narrowing).** The trigger endpoint refused to trigger when the
  scheduler was not running, which broke the pre-existing scheduler
  controls test. APScheduler `modify(next_run_time=...)` is valid on a
  stopped scheduler and fires on the next start, so the refusal was
  wrong; only the paused-job refusal was kept, which is the real guard.
  Proven by `test_scheduler_controls_and_allowlist` (unchanged) and by
  the new `test_scheduler_trigger_rejects_paused_job`.
- **M-3 — Rate limits key on the direct client IP (remaining risk).**
  Limits use `request.client.host` and there is no trusted-proxy
  handling of `X-Forwarded-For`, so behind Nginx all clients share one
  bucket. Mitigation for Phase 10: run the backend bound to localhost
  only (already the Compose default after this phase) and, if a proxy
  is ever placed in front of a multi-client deployment, add explicit
  trusted-proxy configuration — never trust the header blindly.
- **M-4 — SSRF DNS-rebinding window (remaining risk).** The RSS fetcher
  validates the URL and resolves the host before connecting, but
  validation and connection are separate steps, so a DNS answer that
  changes between the two could still reach a private address. The
  fetcher blocks literal private/loopback/link-local addresses,
  redirects, and oversized bodies (2 MiB cap, proven by test), and the
  scheduler RSS path now goes through it (proven by
  `test_scheduler_rss_uses_ssrf_fetcher`). Full rebinding protection
  (pinned resolved address at connect time) is deferred; the practical
  exposure is limited because RSS sources are administrator-configured.
- **M-5 — Integration test-connection URL is not SSRF-validated
  (remaining risk).** The RSS tester is SSRF-protected, but a custom
  `base_url` submitted to an integration test-connection is not put
  through the same validator. Only administrators with
  `integrations.manage` can set it, so this is an admin-only vector,
  but it should be validated before Phase 10 production use.
- **M-6 — Account lockout can be used as a per-account denial of
  service (remaining risk, partially mitigated).** Five failed logins
  lock an account for 15 minutes; an attacker who knows a username can
  lock its owner out. Login errors are generic and unknown users get a
  dummy Argon2 verify (proven by test), so enumeration is mitigated,
  but there is no CAPTCHA. Acceptable for an admin-only panel with a
  small user set; revisit if the panel ever gains public sign-up.

### Low

- **L-1 — Telegram delivery is at-least-once (remaining risk).** A
  crash between sending a message and committing the notification row
  can re-send it. Deduplication keys prevent most duplicates, but an
  exact-once guarantee is not claimed.
- **L-2 — Single-symbol Spot/Futures paths convert through `float`
  before `Decimal(str(...))` (remaining risk).** Bounded precision
  loss, worst for funding rates and small-price tokens. The aggTrades
  volume path (the financially sensitive one) uses pure `Decimal`
  arithmetic on strings and was verified unchanged.
- **L-3 — Frontend gaps (remaining, backend already supports them).**
  Admin user/role edit forms and watchlist add/delete are missing from
  the frontend despite backend support. No data is at risk; the
  operations are available via the API.
- **L-4 — Multi-instance duplication is unguarded (documented
  limitation).** The scheduler is in-process and assumes a single
  backend instance. Running two backends would double-run jobs. The
  Compose setup runs exactly one backend; do not scale it horizontally
  without a distributed lock.

### Informational

- CORS preflight responses do not carry the security headers
  (`X-Content-Type-Options`, `X-Frame-Options`); those ride on real
  responses. Verified by test, not a defect.
- The GitHub Actions workflow file `.github/workflows/ci.yml` still
  cannot be pushed via the GitHub App (403, workflow scope missing).
  It remains local-only and is documented in `PROJECT_STATUS.md`. Its
  branch filter was updated locally to include the Phase 9 branch.
  CI has therefore never executed on GitHub; local checks
  (`scripts/check.sh`) are the enforced gate until Hamid adds the file
  manually or grants the workflow permission.
- The public homepage (`frontend/app/page.tsx`) still described the
  project as "Phase 1 foundation" with dashboard pages "arriving in
  Phase 8". Corrected in this phase.

## 3. Fixes applied in this phase

Earlier Phase 9 fix batch (all covered by the new tests unless noted):

- CORS now allows the `X-CSRF-Token` header; production disables
  interactive API docs and adds HSTS.
- Encryption uses stable key-version ids (`credential_encryption_key_id`,
  default `v1`, plus a previous id); legacy `current`/`previous` rows
  still decrypt, unknown ids raise instead of silently falling back.
  Settings validation rejects an encryption key that is not valid
  base64 decoding to 32 bytes.
- Login uses a dummy Argon2 verify for unknown users and a generic
  message for locked accounts (no enumeration).
- Forgot-password is rate-limited, audited, invalidates sibling reset
  tokens, and purges expired rows; reset-password revokes all sessions
  and invalidates sibling tokens (proven by test, including that the
  old session cookie then returns 401).
- Announcement scheduler normalises a naive `last_success_at` to aware
  UTC (SQLite returns naive datetimes; previously `TypeError`).
- Scheduler registration restores persisted paused-job flags and guards
  concurrent registration (plus the H-1 import fix above).
- `GET /binance/status` is side-effect-free (proven: zero
  `ApiIntegration` rows written); authenticated collect endpoints now
  record integration status instead.
- Admin user/role PATCH returns 400 on duplicate email/username/role
  name instead of 500 (proven by test).
- Custom database roles are assignable via the escalation guard using
  their stored permissions (proven by test).
- `GET /admin/permissions` now requires `roles.view`.
- SSRF fetcher streams with a hard 2 MiB cap; scheduler RSS fetching
  goes through it via `asyncio.to_thread`.
- Funding/open-interest/news/listing/movement jobs return error dicts
  instead of propagating exceptions; volume collection rolls back
  after a per-pair failure without breaking later pairs (proven by
  test); volume reporting catches concurrent-report `IntegrityError`.
- Alpha/Airdrop/Prime processing commits once per entity (parent +
  child together; proven by counting commits: 2 commits for 2 sales,
  previously 4).
- Latest market/futures snapshot lookups use distinct symbols plus one
  latest row per symbol instead of full-table scans; news processing
  preloads processed ids/fingerprints; news categories aggregate with
  SQL `GROUP BY` (proven by test).
- Futures snapshot commit failure rolls back and still attempts the
  run row; `is_stale` normalises a caller-supplied naive `now`; audit
  log date filters normalise naive query strings to UTC.
- Scheduler trigger refuses paused jobs; scheduler list maps
  announcement and volume jobs to their run tables.
- Migration `0010_performance_indexes` (down_revision 0009) adds
  composite indexes on market alerts (symbol, alert type,
  triggered_at), market snapshots (symbol, collected_at), futures
  snapshots (symbol, collected_at), and audit logs (created_at), with
  a reverse downgrade. Historical migrations 0001–0009 untouched.
- Frontend: Settings page parses JSON object values and displays them
  with `JSON.stringify`; integrations toggle confirm text says
  Enable/Disable correctly; login redirect rejects protocol-relative
  `//` URLs; frontend Dockerfile uses `npm ci` and no longer copies a
  nonexistent `public/` directory.
- Compose binds Postgres/Redis/backend/frontend ports to 127.0.0.1,
  adds `restart: unless-stopped` and healthchecks, adds an optional
  `.env` file to backend/bot, and clears the bot entrypoint so only the
  backend runs migrations.

Fixes found and applied while writing this phase's tests:

- H-1 scheduler import fix (above).
- M-1 market overview 503 ordering fix (above).
- M-2 scheduler trigger narrowing (above).

## 4. What was deliberately not changed

- No historical migration was edited. Migration 0010 is the only new one.
- No test was deleted or weakened. The two failures found on the first
  full run after the fix batch were fixed in production code, not in
  the tests.
- No pagination/limit was added to any endpoint without a reproduced
  unbounded query: the snapshot and news-category queries above were
  the reproduced cases and were fixed at the query level.
- The four volume measurements (public / estimated eligible / official
  eligible / leaderboard) were preserved exactly; official eligible
  volume remains null/Unavailable (no authoritative source), and
  unavailable data is never converted to zero.

## 5. Tests performed (actual results)

- Full backend suite: **176 passed** (156 pre-existing + 20 new in
  `backend/tests/test_phase9.py`), 0 failed, Python 3.12.3,
  pytest 8.3.4. Command: `backend/.venv/bin/python -m pytest -q`.
- Lint/format: `ruff check app tests`, `ruff format --check app tests`,
  and `black --check app tests` all pass.
- Migration chain: Alembic upgrade 0001→0010 on a fresh SQLite
  database succeeded (head 0010); downgrade and re-upgrade were
  verified in the earlier Phase 9 pass for 0001→0009 and the 0010
  upgrade was verified again during frontend integration setup.
- New tests cover: CORS `X-CSRF-Token` preflight; announcement
  scheduler with naive `last_success_at`; paused-job restoration and
  double-registration idempotence; password-reset session revocation,
  sibling-token invalidation, and forgot-password auditing; encryption
  rotation with stable key ids and unknown-id rejection; generic
  lockout message; side-effect-free `GET /binance/status`; PATCH
  duplicate returning 400; custom-role assignment; malformed
  encryption-key settings validation; SSRF loopback blocking and body
  cap; scheduler RSS through the SSRF fetcher; cross-module pipeline
  (announcement → Alpha/Airdrop/Prime/competition/news) with duplicate
  prevention on a second run; one-commit-per-entity processing;
  latest-snapshot behaviour; volume pair-failure isolation; news
  category aggregation; paused-job trigger refusal; and every Telegram
  bot command with mocked messages (argument validation, invalid
  symbols, empty results).
- Frontend HTTP integration (2026-10-30, localhost): backend on
  SQLite (Alembic head 0010, one seeded super-admin, one seeded
  announcement) + `npm run build` + `next start` on port 3000.
  Results: login page 200; login via the frontend `/api` proxy 200
  with session cookies; `/auth/me` 200; overview 200 with real data
  (`announcements_total: 1`, matching the seed); every admin section
  API via the proxy 200 (announcements, alpha tokens, airdrops,
  prime-sales, competitions, competition-volume, market overview /
  gainers / losers / watchlist, futures funding / summary, news,
  news-sources, permissions, roles, system-settings, telegram,
  audit-logs, scheduler, integrations, notifications, users,
  dashboard activity/health); every frontend page 200 (login, admin
  and all 18 sections); logout 200 followed by `/auth/me` 401;
  unauthenticated admin API calls 401. Browser automation was
  unavailable in this environment, so client-side rendering and
  click flows were NOT exercised — this is HTTP-level integration,
  not browser end-to-end testing, and must not be described as such.
- Secrets scan: no key/token/password patterns and no `.env` file in
  the repository; only `.env.example` (placeholders) exists.
- Live smoke tests from earlier phases were NOT re-run in this phase
  and are not re-claimed here: Binance CMS collection (140 created,
  duplicates skipped), Alpha/Airdrop/Prime live collection, volume
  aggTrades smoke via `data-api.binance.vision`, and market/news live
  collection all stand as recorded in their phase reports.
- NOT verified in this environment (see §6): PostgreSQL, Redis,
  Docker, Nginx, live Telegram delivery, live Futures data, database
  backup/restore runs, production scheduler long-run.

## 6. Unverified items (exact reasons and commands)

- **PostgreSQL**: no server available here (`docker: command not
  found`, no `psql`, no `/usr/lib/postgresql`). Do not infer
  compatibility from SQLite. On a suitable machine:
  `DATABASE_URL=postgresql+psycopg://crypto:change-me@localhost:5432/crypto_intelligence
  backend/.venv/bin/python -m alembic upgrade head`
  then verify tables/constraints/indexes, run the suite with that
  `DATABASE_URL`, then `alembic downgrade -1 && alembic upgrade head`.
- **Redis**: no server here. Start one (`redis-server` or the Compose
  `redis` service) and verify cache keys and rate-limit behaviour.
- **Docker**: `docker` is not installed here. On a suitable machine:
  `docker compose up --build` and `docker compose ps`, then repeat the
  §5 HTTP checks against the composed services.
- **Nginx / HTTPS**: config inspected only; no live Nginx run and no
  TLS. Phase 10 must add TLS termination and verify with a real
  HTTPS request before public exposure.
- **Live Telegram delivery**: no bot token in this environment. No
  message was sent to any real group. Verify with a test group token
  in Phase 10.
- **Live Futures data**: `fapi.binance.com` returns HTTP 451 from this
  location. Degraded mode (Spot unaffected, Futures marked
  unavailable) is confirmed by test; live Futures data needs a VPS in
  an allowed location. Geographic restrictions were not bypassed.
- **Database backup/restore**: docs exist (`docs/BACKUP_RESTORE.md`);
  no live backup or restore run was performed here. Run
  `pg_dump`/`pg_restore` against a staging database in Phase 10.

## 7. Remaining production risks and deployment tasks

1. Add TLS termination (Nginx) and verify HTTPS end to end — required
   before any public exposure (H-2).
2. Run the full migration chain and test suite against real
   PostgreSQL and Redis (see §6 commands).
3. Run `docker compose up --build` and verify healthchecks, volumes,
   and restart behaviour.
4. Add the GitHub Actions workflow file manually (or grant the GitHub
   App workflow permission) and confirm a green CI run; until then CI
   is local-only.
5. Validate integration test-connection URLs with the SSRF validator
   (M-5) and consider pinned-address fetching for RSS (M-4).
6. Decide on trusted-proxy rate-limit handling if the backend is ever
   placed behind a shared proxy (M-3); keep the localhost-only bind
   until then.
7. Decide on CAPTCHA or equivalent for the login lockout trade-off
   (M-6); acceptable as-is for an admin-only panel.
8. Add the missing frontend forms (user/role edit, watchlist
   add/delete) if administrators need them in the UI (L-3).
9. Verify live Telegram delivery with a test group token, live Futures
   from an allowed location, and a backup/restore drill.
10. Never run a second backend instance without a distributed scheduler
    lock (L-4); never treat a null official volume as zero.

## 8. Production-readiness assessment

Ratings: Verified = proven by a passing test or a live check in this
phase; Passed with limitations = works with the stated caveat;
Failed = known not to meet the requirement; Not tested = no evidence
in this environment. Nothing is rated Verified from code inspection
alone.

| Area | Rating | Basis |
| --- | --- | --- |
| Backend | Passed with limitations | 176 tests pass; SQLite chain verified; PostgreSQL/Docker not verified |
| Frontend | Passed with limitations | Build passes; HTTP integration passes; no browser automation |
| PostgreSQL | Not tested | No server available here; exact commands in §6 |
| Redis | Not tested | No server available here |
| Authentication | Passed with limitations | Session/lockout/reset/CSRF tests pass; Secure-cookie behaviour over HTTPS not tested |
| Authorization | Passed with limitations | RBAC tests for all four roles incl. collect endpoints and scheduler controls |
| Encryption | Passed with limitations | Rotation/validation tests pass; losing the key is a credential-recovery risk (documented in `docs/CREDENTIAL_ENCRYPTION.md`) |
| Telegram | Not tested (live) | All command handlers tested with mocks; live delivery not verified, no token |
| Binance Spot | Passed with limitations | Mock tests pass; live smoke via `data-api.binance.vision` from earlier phases |
| Binance Futures | Passed with limitations | Degraded mode (HTTP 451 → unavailable, Spot unaffected) confirmed; live Futures data not verified |
| Announcement collection | Passed with limitations | Mock pipeline tests pass; live CMS smoke from earlier phases |
| Competition processing | Passed with limitations | Mock pipeline tests pass; live non-Alpha processing not verified |
| Volume tracking | Passed with limitations | Mock aggTrades/interval tests pass; live smoke from earlier phases |
| Market monitoring | Passed with limitations | Mock tests pass; live collect from earlier phases |
| News collection | Passed with limitations | Parser/SSRF/category tests pass; no third-party RSS publisher enabled by default |
| Scheduler | Passed with limitations | Idempotence/paused-restore/trigger tests pass; production long-run not verified |
| Docker | Not tested | `docker` not installed here |
| Nginx | Not tested | Config inspected only; no live run |
| HTTPS readiness | Failed | Nginx is HTTP-only; TLS is Phase 10 work; do not expose publicly yet |
| Database backup | Not tested | Docs exist; no live run here |
| Database restore | Not tested | Docs exist; no live run here |
| Logging/monitoring | Passed with limitations | Structured logging and health endpoints verified over HTTP; no production log aggregation tested |
| CI workflow | Failed | Workflow file not on remote (GitHub App 403); CI never ran on GitHub; local checks are the gate |
| Secret management | Passed with limitations | Scan clean, no `.env` in repo, encryption validated; production secret provisioning not tested |

Overall: the system is in good shape for a staging deployment behind
localhost-only access with the §7 tasks outstanding. It is **not**
ready for public production exposure until HTTPS, PostgreSQL, Redis,
Docker, and CI verification are completed.
