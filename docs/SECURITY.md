# Security

- Authentication and role-based access control are
  implemented in Phase 8: server-side sessions with
  HttpOnly cookies, CSRF protection, Argon2id password
  hashes, login lockout and rate limiting, granular
  permissions enforced at the API layer, and audit
  logging. See docs/ADMIN_SETUP.md and docs/RBAC.md.
  Public read endpoints remain public; every
  administrative and collection control endpoint is
  gated.
- Passwords are stored only as Argon2id hashes (see
  `AdminUser`).
- API secrets entered through the admin API are
  AES-GCM encrypted at rest, masked in the dashboard,
  and never exposed in frontend responses, logs, or Git
  history. See docs/CREDENTIAL_ENCRYPTION.md.
- `.env` is excluded from Git. `.env.example` has placeholders only.
- Input validation uses Pydantic models in the backend and
  validated command arguments in the bot.
- The platform never executes trades, withdrawals, or wallet
  signing, and never requests seed phrases, private keys, or
  exchange passwords.
- Rate limiting, structured logging, audit logs, idempotent
  notifications, and health checks are implemented across
  Phases 1-8, with the models and endpoints for them
  introduced in the relevant phase, not before.
  Security headers (nosniff, DENY framing,
  strict-origin referrer, no-store) are set on API
  responses. RSS feed URLs are SSRF-protected (scheme,
  resolved-IP, and redirect revalidation, size and
  timeout limits).
- Report a suspected vulnerability by stopping the affected
  service, preserving logs, and notifying the administrator
  through a channel outside the platform.
