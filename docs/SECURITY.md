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

## Phase 10 deployment hardening

- **Trusted proxies (TRUSTED_PROXIES).** By default no
  forwarded header is trusted: rate limits and audit IPs
  use the direct remote address. Only when the direct
  address belongs to a network listed in TRUSTED_PROXIES
  is the first X-Forwarded-For entry used, and only if
  it parses as an IP. Set this only to proxies you
  operate (Nginx on the same host/VPC). Never list a
  public range: any client could then spoof its IP and
  evade rate limits. See app/auth/client_ip.py and
  tests/test_phase10.py.
- **Integration test-connection SSRF.** A stored
  integration base URL is now validated with the same
  SSRF rules as RSS feeds before any test-connection
  ping: literal private, loopback, and link-local
  addresses, and hostnames resolving to prohibited
  addresses, return a "blocked" status and are never
  connected to. This closes the Phase 9 finding that
  test-connection URLs were not SSRF-validated.
- **RSS SSRF, residual risk (honest).** Feed URLs are
  validated at resolution time and re-validated
  immediately before every request and every redirect,
  with size and timeout caps. The DNS-rebinding window
  is NOT eliminated: a record could still change
  between the final validation and the TCP connect,
  because httpx has no connect-time address pinning
  without a custom transport. That transport was not
  built in Stage A (it risks TLS hostname handling);
  treat RSS fetching as low-trust input and only enable
  feeds from publishers you have assessed.
- **Account lockout trade-off (documented, not fixed
  with CAPTCHA).** Five consecutive failures lock an
  account for 15 minutes. That deliberately trades a
  small denial-of-service risk (an attacker who knows a
  username can lock that account) against credential
  stuffing protection. No CAPTCHA dependency was added
  in Stage A because no provider has been selected or
  configured; adding one is a Stage B decision for the
  operator, not a silent default. Mitigations in place:
  generic login errors (no user enumeration), per-IP
  login rate limiting, and audit logging of failures.
- **Scheduler, single instance.** The deployment runs
  exactly one backend service, which owns the only
  scheduler. Never scale backend/bot past one replica
  without a distributed lock (documented in the
  production guide); a second scheduler would
  double-collect and double-notify.
- **HTTPS gate.** The application must NOT be publicly
  exposed through the HTTP-only Nginx config. TLS is
  prepared (nginx/production.conf, scripts/setup-https.sh)
  but NOT verified in Stage A: there is no domain yet,
  so no certificate was issued and HSTS stays commented
  out until HTTPS is confirmed working.

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
