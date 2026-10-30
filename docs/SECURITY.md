# Security

- Authentication and role-based access control are implemented
  with the dashboard in Phase 8; Phase 1 has no authenticated
  routes beyond the public health endpoints.
- Passwords are stored only as hashes (see `AdminUser`).
- API secrets are encrypted at rest in later phases, masked in
  the dashboard, and never exposed in frontend responses, logs,
  or Git history.
- `.env` is excluded from Git. `.env.example` has placeholders only.
- Input validation uses Pydantic models in the backend and
  validated command arguments in the bot.
- The platform never executes trades, withdrawals, or wallet
  signing, and never requests seed phrases, private keys, or
  exchange passwords.
- Rate limiting, structured logging, audit logs, idempotent
  notifications, and health checks are implemented across
  Phases 8 and 9, with the models and endpoints for them
  introduced in the relevant phase, not before.
- Report a suspected vulnerability by stopping the affected
  service, preserving logs, and notifying the administrator
  through a channel outside the platform.
