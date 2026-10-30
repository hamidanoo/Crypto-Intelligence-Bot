# External Verification

The following checks could not be completed in the development
environment used for Phases 1 and 2 and for this fix pass.
Do not claim they are complete until they have been run in an
appropriate environment and their output has been recorded.

## 1. Docker Compose run

On a machine with Docker and Docker Compose installed:

```bash
cp .env.example .env
# Fill in real values in .env, especially SECRET_KEY and
# PostgreSQL credentials. Do not commit .env.
docker compose up --build
```

Expected: postgres, redis, backend, bot, frontend, and nginx
all start healthy. Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
curl http://localhost:3000/
```

`/health/ready` should report database and redis as `ok`
when those services are healthy.

## 2. Live PostgreSQL migrations

Inside the backend service, or from a backend checkout with
a live PostgreSQL URL in `.env`:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

Expected: `alembic current` reports revision `0003` as head,
and the tables `admin_users`, `telegram_groups`,
`system_settings`, `api_integrations`, `audit_logs`,
`market_snapshots`, and `futures_snapshots` exist in the
database. Migration execution against SQLite was verified
in this fix pass; PostgreSQL execution was not.

## 3. Live Redis cache

With the stack running, call a Binance price endpoint
twice in quick succession:

```bash
curl http://localhost:8000/binance/price/BTCUSDT
curl http://localhost:8000/binance/price/BTCUSDT
```

The second response should report `"cached": true` when
Redis is available. In this fix pass, Redis was unavailable,
so the cache fell back to in-memory storage and the
fallback path was tested, not the Redis path.

## 4. Live Telegram bot

Set a real bot token and group id in `.env`, then:

```bash
docker compose up bot
```

Send `/start`, `/help`, and `/status` to the bot in the
group. The bot must reply to all three. No token was
available in this fix pass, so live polling was not tested.

## 5. Live Binance Futures

On a VPS in a location where Binance Futures is not
restricted, with the stack running and Spot base URL set
to the standard endpoint:

```bash
curl http://localhost:8000/binance/status
curl http://localhost:8000/binance/funding/BTCUSDT
curl http://localhost:8000/binance/open-interest/BTCUSDT
```

Expected: `/binance/status` reports both Spot and Futures
as `ok`, and funding and open interest return real data
instead of the restricted-location error seen in the
development environment.
