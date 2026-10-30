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

## Phase 9 audit notes

- Paused scheduler jobs now restore correctly on restart
  (a broken import had silently disabled restoration).
- Login errors are generic for locked and unknown accounts
  (dummy Argon2 verify for unknown users); password reset
  revokes all sessions and invalidates sibling tokens.
- Encryption key ids are stable version labels (`v1` by
  default); unknown ids raise, legacy `current` rows still
  decrypt. Losing the key is a credential-recovery risk.
- Remaining risks, with evidence, are in
  `docs/PHASE_09_AUDIT_REPORT.md`: rate limits key on the
  direct client IP behind a proxy, the SSRF DNS-rebinding
  window, lockout as per-account denial of service,
  at-least-once Telegram delivery, and single-instance
  scheduler assumption. HTTPS is still missing (Phase 10):
  do not expose the panel publicly until TLS is added.
