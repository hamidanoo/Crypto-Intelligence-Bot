# Phase 1 and Phase 2 Issue Fix Plan

Branch: `fix-phase1-phase2-issues`, created from
`phase-02-binance-integration`. No Phase 3 work is included.

## Classification

### A. Fixable in the current development environment

- Scheduler lifecycle: the scheduler was never started or shut
  down by the API lifespan.
- Database migration and startup: no automatic migration on
  container start; migration execution was only checked as
  history, not run.
- Frontend API proxy: the frontend called the backend directly
  instead of using the Nginx / Next.js `/api` proxy.
- Production secret validation: a known default secret could
  run in production without failing.
- CORS restrictions: methods and headers were unrestricted.
- Binance funding-rate ordering: the latest rate was assumed
  to be the last row, without sorting by funding time.
- Retry and error handling: a non-numeric Retry-After header
  could crash, a final 429/5xx produced a misleading error,
  and database failures in collect endpoints returned a raw 500.
- Decimal precision: snapshot prices and volumes were stored
  as binary floats.
- Concurrent health checks: Spot and Futures pings ran
  sequentially.
- API request validation: collect endpoints took symbols as
  a query parameter with no documented body contract and no
  symbol-count limit.
- Redis caching and request controls: no cache and no rate
  limit existed on Binance routes.
- CI, linting, formatting, and tests: no workflow, linter,
  formatter configuration, or tests for the above fixes.
- PROJECT_STATUS latest-commit lag: the status file always
  named the main commit, not the branch head after the
  status-update commit.

### B. Requires external infrastructure or credentials

These are documented, not faked, and remain open after this
fix pass. Exact verification commands are in
`docs/EXTERNAL_VERIFICATION.md`.

- Docker Compose run on a Docker host.
- Live PostgreSQL migration execution for 0001, 0002, and 0003.
- Live Redis connection and Redis-backed cache verification.
- Live Telegram bot polling, which requires a bot token.
- Live Binance Futures testing, which requires a VPS in a
  location where fapi.binance.com is not restricted.

### C. Not currently necessary, documented for a later phase

- shadcn/ui dashboard components: Phase 8.
- Dashboard authentication, roles, and credential encryption:
  Phase 8.
- Nginx TLS: Phase 10.
- Distributed rate limiting across multiple instances: later,
  after multi-instance deployment is a real requirement. The
  fix pass implements a single-instance limit and Redis
  caching, which is sufficient for the current architecture.
- Scheduled collection jobs: later phases, when collectors
  exist to schedule. The scheduler lifecycle itself is fixed
  in this pass, with no jobs registered yet.
- Full dashboard pages, announcement monitoring, and all
  Phase 3+ features: explicitly out of scope for this pass.
