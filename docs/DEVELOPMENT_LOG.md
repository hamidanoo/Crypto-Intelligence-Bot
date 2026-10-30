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
