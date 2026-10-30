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

## Phase 8 deployment notes

- Set `ENVIRONMENT=production`, a real `SECRET_KEY`,
  and `CREDENTIAL_ENCRYPTION_KEY` (base64, 32 bytes);
  production startup fails without the last two.
- Create the first administrator on the server with
  `backend/scripts/create_admin.py` (see
  docs/ADMIN_SETUP.md); do not bake credentials into
  images or compose files.
- Serve the frontend and backend behind Nginx with
  the existing proxy; admin cookies require HTTPS in
  production for the Secure flag to apply.
- Live PostgreSQL migration 0009, Docker run, live
  Telegram delivery, and a production scheduler run
  are not yet verified for Phase 8.
