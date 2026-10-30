# Production Deployment Guide — Phase 10, Stage A

> **Stage A only.** This guide prepares everything that
> can be prepared without real infrastructure. **Stage B
> (a live production deployment) has NOT happened.**
> There is currently no VPS, no domain, no production
> server, and no production DNS record. Every domain,
> IP address, and credential in this guide is a
> placeholder (YOUR_DOMAIN, YOUR_VPS_IP) unless it is
> explicitly labelled as an example. Nothing in Stage A
> purchases anything, issues a certificate, or exposes
> the application publicly.
>
> **Hard gate:** do not serve production traffic through
> the HTTP-only Nginx config. TLS (section 14) must be
> verified first, and only then may HSTS be enabled.

## 1. VPS requirements

Starting specification — explicitly **not a measured
minimum** (no load test has been run against this stack):

- Ubuntu Server LTS (24.04 or newer at deploy time)
- 4 vCPU
- 8 GB RAM
- 100–160 GB SSD/NVMe
- Public IPv4 address
- SSH access (key authentication, section 3)
- Firewall (section 4)
- Backup or snapshot capability from the provider
  (in addition to the application's own backups,
  section 19)

Re-check the provider's CPU, RAM, storage, bandwidth,
backup, firewall, support, renewal pricing, and refund
policy at purchase time. Prices are not quoted here:
they change, and any price seen elsewhere must be
re-verified before buying. Nothing is purchased on
your behalf.

**Data-centre location for latency from Pakistan
(general comparison, verify at purchase time):**
Singapore and Mumbai are the nearest major regions
for most providers and are the natural first
candidates; Frankfurt is a common farther fallback
with more provider choice but higher latency. Latency
is not the only factor: compare the same provider's
CPU/RAM/storage/bandwidth, backup and snapshot
options, firewall features, support quality, renewal
(not just first-term) pricing, and refund policy
before choosing. Binance API latency matters for
market data freshness, but this application is
intelligence/monitoring only — it does not trade —
so a few tens of milliseconds of extra latency are
not a correctness problem.

## 2. Ubuntu installation

Install Ubuntu Server LTS from the provider's image.
Create a non-root deploy user with sudo, and disable
password authentication for SSH once key login works
(section 3). Keep the system updated:

```
sudo apt update && sudo apt upgrade -y
```

## 3. SSH hardening

- Log in with an SSH key only; disable `PasswordAuthentication`
  and `PermitRootLogin` in `/etc/ssh/sshd_config`, then
  `sudo systemctl reload ssh`.
- Change the SSH port only if you document it for
  yourself; port changes alone are not security.
- Use `fail2ban` or the provider firewall to limit
  brute-force attempts.
- Never share the deploy user's private key, and never
  store it in this repository.

## 4. Firewall

Allow inbound only: SSH (your port), HTTP 80 (for
Let's Encrypt challenges and the HTTPS redirect),
and HTTPS 443. Deny everything else, including
PostgreSQL 5432 and Redis 6379 — those services are
bound to 127.0.0.1 inside Compose and must never be
published. Example with UFW:

```
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 5. Docker installation

Install Docker Engine and the Compose v2 plugin from
Docker's official repository for your Ubuntu release
(follow Docker's current install docs; do not use an
untrusted install script you have not read). Verify:

```
docker --version
docker compose version
```

Docker was **not available** in the Stage A
environment (`docker: command not found`), so no
Docker build or Compose run is claimed in Stage A.

## 6. Docker Compose installation

Compose v2 ships as the `docker compose` plugin with
Docker Engine (section 5). There is no separate
Compose v1 binary to install. Verify with
`docker compose version` before proceeding.

## 7. DNS setup

Prerequisites for HTTPS (section 14):

1. Register a domain (Stage B decision; no domain is
   named here).
2. Create an A record pointing the domain at the
   VPS's public IPv4 address (YOUR_VPS_IP).
3. Wait for DNS propagation and verify from the VPS:
   `getent hosts YOUR_DOMAIN` must return the VPS IP.
4. Keep ports 80 and 443 open (section 4).

Domain structure recommendation (placeholders only):
serve everything through one domain,
`admin.example.com`, with the backend reached
privately through the frontend proxy (`/api/`), as
this stack already does. A separate public API
hostname, `api.example.com`, is only needed if a
separate public API is genuinely required; prefer
private backend access through the frontend proxy
where practical, so only one hostname needs a
certificate and only Nginx is publicly reachable.

## 8. Environment setup

On the VPS, clone the repository and check out the
Phase 10 branch (do not deploy from `main`):

```
git clone <repository-url> crypto-intelligence
cd crypto-intelligence
git checkout phase-10-production-deployment
cp .env.example .env
chmod 600 .env
```

Then fill in `.env` with real values — see section 9
and `.env.example` for every variable. Rules:

- `.env` is never committed (see `.gitignore`).
- `.env` permissions must be `0600`, owned by the
  deploy user.
- No default production passwords: `SECRET_KEY`
  must not be `change-me-in-production`, and
  `POSTGRES_PASSWORD` must not be `crypto`.
- `ENVIRONMENT=production` is required; the backend
  refuses to start in production without `SECRET_KEY`
  and `CREDENTIAL_ENCRYPTION_KEY`.

## 9. Secret generation

Generate secrets on the VPS terminal only — never
paste them into chat, logs, or Git. Safe commands:

```
# SECRET_KEY (any long random string)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# CREDENTIAL_ENCRYPTION_KEY (base64, exactly 32 bytes)
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
# POSTGRES_PASSWORD
openssl rand -hex 24
```

Scripts never print secret values; only variable
names are mentioned in logs and error messages.

**Credential-encryption key, separately:** back up
`CREDENTIAL_ENCRYPTION_KEY` (and, during rotation,
the previous key) **separately from database
backups**, in a place an attacker who obtains a
database backup cannot also reach — for example a
password manager or sealed offline copy. Losing this
key means AES-GCM-encrypted credentials in the
database cannot be decrypted, even from a perfect
backup. That is a credential-recovery risk, not a
database-restore problem: after restoring without
the key, credentials must be re-entered through the
admin panel.

## 10. PostgreSQL

PostgreSQL 16 runs as the `postgres` Compose service
with a persistent named volume (`postgres_data`).
It is bound to 127.0.0.1 and is not publicly
exposed. Fresh-database behaviour:

- On first backend start, the entrypoint runs
  `alembic upgrade head` (migrations 0001→0010)
  before the API starts. If migrations fail, the
  container exits and the API is never exposed with
  a stale schema.
- Verify the head after deploy: the backend logs
  show the migration run, and `alembic current`
  inside the backend container reports 0010.

PostgreSQL was **not tested** in Stage A (no server
or Docker in that environment). On the VPS, run the
exact commands in docs/PRODUCTION_CHECKLIST.md
(fresh DB, migration head, constraints, restart
persistence) and record the results before going
live. Do not infer PostgreSQL compatibility from
SQLite tests.

## 11. Redis

Redis 7 runs as the `redis` Compose service with a
persistent volume (`redis_data`), bound to
127.0.0.1, not publicly exposed. The application
treats Redis as a cache with an in-memory fallback:
a restart that drops cached entries is safe, and a
Redis failure must degrade to that fallback, not
crash the API. Redis was **not tested** in Stage A;
verify connection, set/get with expiry, failure
handling, and recovery after restart on the VPS
(checklist, Stage B).

## 12. Migrations

Migrations run exactly once per deployment, by the
backend entrypoint only. The bot's entrypoint is
cleared in Compose so it cannot race the backend.
Rules for operators:

- Never run `alembic downgrade` on production
  (the deploy script never does).
- Never edit historical migrations (0001–0010) to
  hide a problem; a correction is a new migration.
- After a restore, verify the migration head before
  pointing any service at the restored database.

## 13. Nginx

Nginx is the only publicly exposed service (80/443).
Two configs ship in `nginx/`:

- `nginx.conf` — HTTP only, local development.
  Serves the Let's Encrypt webroot path.
- `production.conf` — HTTP→HTTPS redirect, TLS
  1.2/1.3 only, modern ciphers, security headers,
  request-size limits (10 MB), proxy timeouts,
  forwarded headers, generic error pages.

Select the config with `NGINX_CONFIG_FILE` in the
deployment environment (default: the HTTP config).
Internal services are reached by container DNS
(`backend:8000`, `frontend:3000`) and are never
published.

## 14. HTTPS

With a real domain and DNS pointing at the VPS:

```
DOMAIN=your-real-domain CERTBOT_EMAIL=you@example.com ./scripts/setup-https.sh
```

The script: starts Nginx with the HTTP config,
obtains a certificate with certbot (webroot mode),
switches Nginx to `production.conf`, verifies an
HTTPS request, and **only then** enables HSTS in
`production.conf` and reloads. If the HTTPS check
fails, HSTS is not enabled and the script exits with
the reason (DNS, firewall, or certificate).

Renewal (install on the VPS, twice daily):

```
0 3,15 * * * cd <repo-path> && docker compose --profile certbot run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
```

Or run `./scripts/setup-https.sh renew` manually.
**HTTPS is NOT verified in Stage A**: no domain
exists, so no certificate was issued and HSTS
remains commented out in the template. Do not
uncomment HSTS until section 14's HTTPS check has
passed on the real domain.

## 15. Application startup

```
./scripts/production-check.sh   # must pass first
./scripts/deploy.sh             # validates env, builds, starts, health-checks
./scripts/health-check.sh       # backend, frontend, postgres, redis
```

Deploy never deletes volumes and never downgrades
migrations. If `deploy.sh` fails at the migration
step, fix the database/migration problem — do not
work around it by starting the API anyway.

## 16. Health checks

- Backend: `GET http://127.0.0.1:8000/health`
- Frontend: `GET http://127.0.0.1:3000/`
- PostgreSQL: `pg_isready` inside the container
- Redis: `redis-cli ping` inside the container
- Admin health page: `/admin/health` (after login)
  shows per-service healthy/degraded/unavailable
  from real checks, including Binance Spot status
  and Futures degraded status.

## 17. Telegram setup

Live Telegram verification is **pending** (no token,
no message sent in Stage A). Stage B procedure
(only after explicit authorisation from the owner):

1. Create a dedicated test group (never the
   production group for testing).
2. Create the bot, keep its token in `.env` only
   (`TELEGRAM_BOT_TOKEN`, `chmod 600 .env`), and
   add the bot to the test group as an admin with
   permission to post.
3. Set `TELEGRAM_GROUP_ID` to the test group's ID.
4. Send one test message from the admin panel's
   Telegram test-message control (explicit click
   only; the page never sends on load).
5. Check formatting, delivery, failure handling,
   and duplicate prevention (the same notification
   must not be sent twice after a retry/restart).
6. Only after the test group passes, point the
   configuration at the production group — again
   only with explicit authorisation.

## 18. Scheduler verification

On the VPS, after startup, confirm in the admin
Scheduler page (or backend logs) that exactly one
scheduler is running with the 12 known jobs, no
duplicates, and no overlaps (`max_instances=1`).
Confirm paused jobs stay paused after a restart.
Never scale the backend service past one replica:
a second scheduler needs a distributed lock, which
does not exist in this stack.

## 19. Backups

```
./scripts/backup.sh   # pg_dump custom format, timestamped, integrity-checked
```

- Default directory `./backups` (outside any web
  root), permissions 0700, files 0600.
- Integrity: `pg_restore --list` must succeed or
  the file is deleted and the script exits non-zero.
- Retention: files older than `BACKUP_RETENTION_DAYS`
  (default 30) are deleted.
- Schedule (VPS cron, daily): `0 2 * * * cd <repo-path> && ./scripts/backup.sh`
- The encryption key is backed up separately
  (section 9); it is not in the database backup.

## 20. Restore

```
./scripts/restore.sh <backup-file> [--target-db NAME] [--force-production]
```

Default target is a separate test database
(`<production-db>_restore`). Restoring into the
production database is refused unless
`--force-production` is passed AND the operator
types exactly `OVERWRITE PRODUCTION`. The backup is
integrity-checked before any restore. After a
restore, verify the migration head and run the
health checks before pointing any service at the
restored database. A real restore drill is a
Stage B task; Stage A tested only the script's
argument, refusal, and syntax behaviour (no real
PostgreSQL was available).

## 21. Monitoring

Minimum viable monitoring on the VPS:

- Container status and restarts: `docker compose ps`
  and the restart policies (`unless-stopped`).
- Disk space and log growth: Compose logging is
  capped at 10 MB × 3 files per service; watch the
  backup directory and database volume growth.
- Application health: the admin Health page and
  `scripts/health-check.sh` on a schedule, alerting
  through whatever channel the operator already
  uses (no monitoring service is bundled here).
- Collection errors: the admin dashboard's latest
  collection errors and the audit log.

## 22. Troubleshooting

- Backend exits on start: read its logs first —
  a migration failure is the usual cause; fix the
  database problem, do not bypass migrations.
- `SECRET_KEY` / encryption-key errors in
  production: the validator fails fast by design;
  set the missing variable in `.env` (0600) and
  restart.
- Futures shows unavailable (HTTP 451): expected
  from restricted locations; degraded mode is the
  correct behaviour, not an error to bypass.
- Spot data stale: check Binance base URL
  (`data-api.binance.vision` where `api.binance.com`
  is restricted), then the market collection runs.
- Nginx serves HTTP only: you are on the dev
  config; follow section 14, do not publish it.
- Login lockout: wait 15 minutes or use the admin
  bootstrap/operator process; do not disable
  lockout to work around it.

## 23. Updates

1. Back up the database (`scripts/backup.sh`) and
   note the encryption-key backup location.
2. Pull the new branch/commit on the VPS.
3. Re-run `scripts/production-check.sh`.
4. Re-run `scripts/deploy.sh` (migrations run via
   the backend entrypoint).
5. Re-run `scripts/health-check.sh` and check the
   admin Health page.
6. If anything fails, follow section 24 — do not
   improvise a downgrade.

## 24. Rollback

Rollback is: stop the stack, restore the previous
code checkout, restore the pre-update database
backup into a test database first, verify it, and
only then — with explicit confirmation — restore
it as production (section 20). There is no
automatic rollback and no automatic migration
downgrade: a migration that has run against
production data must be handled deliberately, with
a new forward migration if needed. Record every
rollback in the deployment log.
