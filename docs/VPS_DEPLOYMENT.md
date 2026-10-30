# VPS Deployment

Full production deployment is Phase 10. Phase 1 establishes the
pieces that deployment will use: Dockerfiles, Docker Compose,
and the Nginx reverse proxy.

Planned production steps (Phase 10):

1. Provision an Ubuntu VPS with Docker and Docker Compose.
2. Clone the repository and create `.env` from `.env.example`
   with production secrets.
3. Build and start the stack with `docker compose up --build -d`.
4. Run `docker compose exec backend alembic upgrade head`.
5. Configure Nginx with a domain name and TLS (the Phase 1
   Nginx configuration is HTTP-only and must be extended with
   TLS in Phase 10).
6. Verify `/health`, `/health/ready`, the dashboard, and the bot.

Do not use the Phase 1 development defaults (`SECRET_KEY`,
database password) in production.
