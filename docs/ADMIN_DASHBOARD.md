# Admin Dashboard Guide (Phase 8)

## Access

Log in at `/login`. The dashboard lives under
`/admin`. Navigation items are filtered by the
permissions returned by `GET /auth/me`; the backend
still enforces every permission, so hiding an item
never grants access to its endpoint.

Sidebar: Overview, Announcements, Alpha Tokens,
Airdrops, Prime Sales, Competitions, Competition
Volume, Market Intelligence, Futures Intelligence,
News, Telegram Management, API Integrations,
Notification Settings, Scheduler, Administrators,
Audit Logs, System Health, Settings. A theme toggle
(dark/light) is in the top bar; only the theme choice
is stored in `localStorage`.

## Overview

`GET /admin/dashboard/overview` returns real
aggregated counts (announcements total and new,
active Alpha tokens, active airdrops, upcoming Prime
Sales, active competitions, latest competition
volume), market status (with a stale flag), futures
availability, latest news, Telegram configuration
status, scheduler status, database and Redis health,
latest collection errors, and the dashboard refresh
interval. `GET /admin/dashboard/activity` returns
14-day time-bucketed counts for charts. Nothing is
fabricated: missing data is shown as unavailable or
stale, never as zero or healthy.

## Management pages

- **Announcements / Alpha / Airdrops / Prime Sales /
  Competitions / Volume / Market / Futures / News:**
  real lists with search, filters, and pagination,
  detail views where the backend provides them, and
  collection buttons that require the
  `collections.run` permission. Volume pages keep the
  strict public / estimated eligible / official
  eligible distinction; official values are shown as
  Unavailable unless a verified authoritative source
  exists.
- **Telegram Management:** bot configuration status
  (token presence only, never the token value), group
  id and title, notification enable/disable and
  category settings. The test-message button sends
  only when explicitly clicked, and only when a token
  and group are configured; otherwise it fails cleanly.
- **API Integrations:** masked credentials only.
  Adding or updating a credential encrypts the secret
  with AES-GCM at rest. Test-connection decrypts
  internally and, for Binance providers, pings Spot;
  for other providers it verifies decryptability.
  It never returns a secret.
- **Notification Settings:** global and per-category
  toggles, thresholds, and cooldown, persisted in
  `SystemSetting` rows and surviving restarts, plus a
  delivery history table from notification records.
- **Scheduler:** every registered job with interval,
  next run, last run, last status, and enabled flag.
  Pause, resume, and trigger accept only job ids from
  a server-side allowlist; trigger schedules an
  immediate run through the existing scheduler and
  never executes caller-supplied code. There is no
  second scheduler instance.
- **Administrators and Roles:** create, view, update,
  and deactivate administrators; create and update
  roles with explicit permission lists. The guards in
  docs/RBAC.md apply (no self-role-change, no
  self-deactivation, no last-Super-Admin removal, no
  granting unpossessed permissions).
- **Audit Logs:** paginated, filterable by action,
  actor, and date range. Audit rows are append-only
  for ordinary administrators: no update or delete
  endpoint exists, and reading requires `audit.view`.
- **System Health:** one row per service (database,
  Redis, scheduler, Telegram, Binance Spot, Binance
  Futures, announcement collection) with healthy /
  degraded / unavailable / unknown status from actual
  checks and last-success timestamps. Futures shows
  its real degraded status (HTTP 451 in restricted
  locations) instead of a fabricated healthy state.
- **Settings:** system settings key/value editing
  (sensitive keys are never returned in plaintext),
  dashboard refresh interval, and a link to change
  password.

## Audit logging

Recorded for: login success/failure, logout, password
changes and resets, administrator creation and
deactivation, role and permission changes, credential
updates (without secret values), Telegram
configuration changes, notification changes,
scheduler controls, manual collection requests,
sensitive settings changes, and failed authorisation
attempts. Each row carries administrator id, actor,
action, resource type and id, timestamp, outcome,
correlation id where available, source IP, and
non-sensitive metadata. Passwords, session tokens,
reset tokens, API secrets, and bot tokens are
redacted before writing and are never logged.

## Known limitations (Phase 8)

- Live PostgreSQL migration 0009, Docker run, live
  Telegram delivery, and a production scheduler run
  are not verified (SQLite migration, mock Telegram,
  and local scheduler tests were verified).
- Telegram bot username is not resolved in the admin
  API (it returns null); only token presence is
  reported, to avoid an extra Bot API call at page
  load.
- News source rows have no persisted last-success or
  last-error columns from Phase 7; the admin API
  reports those as null and the test endpoint result
  is returned directly instead.
- Dashboard notification activity by day is not yet
  charted from a dedicated table (the activity
  endpoint returns an empty series for notifications);
  delivery history is available from the
  notifications history endpoint.
- Manual collection endpoints are now gated, which
  changed earlier test setups: those tests now
  authenticate with a seeded Super Admin. Every
  original assertion is preserved; see
  docs/DEVELOPMENT_LOG.md.
