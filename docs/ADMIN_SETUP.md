# Administrator Setup (Phase 8)

## First administrator (bootstrap)

There is no public registration endpoint and no default
password. The first Super Admin is created with a CLI
script that reads its credentials from the environment
only:

```bash
cd backend
ADMIN_BOOTSTRAP_USERNAME=admin \
ADMIN_BOOTSTRAP_PASSWORD='<a strong password>' \
ADMIN_BOOTSTRAP_EMAIL=admin@example.com \
python scripts/create_admin.py
```

Rules enforced by the script:

- Both `ADMIN_BOOTSTRAP_USERNAME` and
  `ADMIN_BOOTSTRAP_PASSWORD` must be set; the password
  must be at least 8 characters.
- If any active Super Admin already exists, the script
  refuses to run. It cannot be used to create a second
  bootstrap administrator or to overwrite one.
- The password is never printed.

After bootstrap, log in at `/login`, create named
administrator accounts for each person, and rotate the
bootstrap password (or deactivate the bootstrap account
once named Super Admin accounts exist). Named accounts
make audit logs attributable; shared accounts should not
be used for daily work.

## Login and session architecture

- `POST /auth/login` verifies the Argon2id password
  hash, then creates a fresh server-side session. A
  pre-login cookie is never carried into an
  authenticated session (session-fixation protection).
- The browser receives two cookies: `admin_session`
  (HttpOnly, SameSite=Lax, Secure in production) holding
  an opaque token, and `admin_csrf` (readable by the
  frontend) holding the CSRF token. Only the SHA-256
  hash of the session token is stored in the database.
- State-changing requests under `/auth` and `/admin`
  must send `X-CSRF-Token` matching the session's CSRF
  token, or they are rejected with 403.
- Sessions expire after 60 minutes of inactivity
  (`SESSION_INACTIVITY_MINUTES`) and absolutely after 12
  hours (`SESSION_ABSOLUTE_HOURS`). `last_seen_at` is
  refreshed on every authenticated request.
- `POST /auth/refresh` rotates the session: a new token
  and CSRF token are issued and the old session is
  revoked immediately, so the old token stops working.
- `POST /auth/logout` revokes the session server-side
  and clears both cookies.
- No long-lived access token is ever stored in
  `localStorage` or `sessionStorage`. The frontend keeps
  only the theme preference in `localStorage`.
- On a 401 response the frontend redirects to `/login`
  with a session-expired message.

## Password rules

- Hashing is Argon2id (argon2-cffi) with time_cost=3,
  memory_cost=64 MiB, parallelism=4 by default; see
  `ARGON2_TIME_COST`, `ARGON2_MEMORY_COST_KIB`, and
  `ARGON2_PARALLELISM`.
- Passwords are never stored in plaintext, never
  returned by any API response, and never logged.
- `POST /auth/change-password` requires the current
  password and revokes all other sessions for that
  administrator.
- `POST /auth/forgot-password` always returns the same
  generic message, whether or not the account exists, so
  it cannot enumerate accounts. Reset tokens are stored
  hashed, expire after 60 minutes
  (`PASSWORD_RESET_TOKEN_MINUTES`), and are single-use.
- Login throttling: 5 consecutive failed logins lock
  the account for 15 minutes (`LOGIN_MAX_ATTEMPTS`,
  `LOGIN_LOCKOUT_MINUTES`), and logins are rate-limited
  per IP (30/minute, `LOGIN_RATE_LIMIT_PER_MINUTE`).
  Every login success and failure is audited.

## Production startup validation

When `ENVIRONMENT=production`, startup fails unless
`SECRET_KEY` is a real value and
`CREDENTIAL_ENCRYPTION_KEY` is set. There is no
fallback password and no hardcoded production secret.
