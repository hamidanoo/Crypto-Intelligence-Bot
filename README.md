# Crypto Intelligence Bot

A Crypto Intelligence Platform consisting of a Telegram bot, a FastAPI
backend, background workers, PostgreSQL, Redis, and a Next.js admin
dashboard. The platform collects, processes, stores, analyses, and
publishes Binance ecosystem intelligence. It is an intelligence and
monitoring system only: it never executes trades, withdrawals, or
wallet signing.

## Current status

Phase 7 — Market, Futures & News Intelligence is complete on
branch `phase-07-market-futures-news`. See
`PROJECT_STATUS.md` for the current phase, test
results, and limitations. Nothing has been merged
into `main`.

## Architecture

Modular monolith, in one repository:

- `backend/` — FastAPI API, SQLAlchemy models, Alembic migrations,
  Telegram bot handlers, and the APScheduler job registry.
- `frontend/` — Next.js + TypeScript admin dashboard.
- `nginx/` — Reverse proxy in front of the API and dashboard.
- `docker-compose.yml` — PostgreSQL, Redis, backend, bot, frontend,
  and Nginx services.

Full details are in `docs/ARCHITECTURE.md`.

## Technology

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic
- Bot: aiogram 3.x, asynchronous
- Background work: APScheduler in-process, Redis for caching and
  deduplication keys in later phases
- Database: PostgreSQL, UTC timestamps
- Frontend: Next.js, TypeScript, Tailwind CSS, Recharts
- Infrastructure: Docker, Docker Compose, Nginx, Ubuntu VPS

## Quick start (development)

1. Copy the environment template and fill in real values:
   ```bash
   cp .env.example .env
   ```
2. Start the stack:
   ```bash
   docker compose up --build
   ```
3. Open the dashboard at http://localhost:3000 and the API health
   endpoint at http://localhost:8000/health.
4. Run database migrations inside the backend service:
   ```bash
   docker compose exec backend alembic upgrade head
   ```

Without Docker, run the backend from `backend/` with a virtual
environment, install `requirements.txt`, and start it with
`uvicorn app.main:app --reload`. Run tests with `pytest` from
`backend/`.

## Security

- Never commit `.env`, API keys, passwords, or secrets.
- Use `.env.example` placeholders only.
- Secrets are encrypted at rest in later phases and masked in the
  dashboard; they are never printed in logs or returned by the API.
- Never share a seed phrase, private wallet key, exchange password,
  or withdrawal authorisation with this platform.

## Documentation

- `PROJECT_STATUS.md` — current phase and test results
- `CHANGELOG.md` — changes by phase
- `docs/DEVELOPMENT_LOG.md` — decisions, issues, and testing
- `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/API.md`
- `docs/VOLUME_TRACKER.md` — Phase 6 volume methodology
- `docs/TELEGRAM_SETUP.md`, `docs/API_CONFIGURATION.md`,
  `docs/ADMIN_GUIDE.md`
- `docs/WINDOWS_SETUP.md`, `docs/VPS_DEPLOYMENT.md`,
  `docs/BACKUP_RESTORE.md`, `docs/SECURITY.md`,
  `docs/TROUBLESHOOTING.md`
