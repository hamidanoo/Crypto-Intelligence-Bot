# Troubleshooting

## Backend does not start

- Check Python 3.12+ is installed and `requirements.txt` installed
  cleanly in a virtual environment.
- Check `.env` values, especially `DATABASE_URL` and `REDIS_URL`.
- Check the logs: the backend logs its environment on startup
  and never logs secrets.

## /health/ready reports "degraded"

This is the endpoint working correctly: one component is
unavailable. Check the `components` field to see whether it is
the database or Redis, then check that service's logs and
connection settings.

## Frontend cannot reach the backend

- Confirm the backend is running on port 8000 and
  `GET /health` returns `ok`.
- Confirm `NEXT_PUBLIC_API_URL` points at the backend URL.
- Confirm the backend CORS origins include the frontend origin.

## Bot does not respond

- Confirm `TELEGRAM_BOT_TOKEN` is set; without it the bot logs
  a warning and does not poll.
- Confirm the bot was added to the group and `/start` was sent.
- Check bot service logs for Telegram API errors.

## Docker is not available

Install Docker Desktop (Windows/macOS) or Docker Engine
(Ubuntu), then run `docker compose up --build` again. The
backend and frontend can also run directly, as described in
`docs/WINDOWS_SETUP.md`.
