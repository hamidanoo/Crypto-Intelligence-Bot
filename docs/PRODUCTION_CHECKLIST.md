# Production Checklist — Stage B (do in order)

> Stage A prepared this checklist; **no item below is
> claimed done**. Tick each item only after it has
> actually been verified on the real VPS. Placeholders
> (YOUR_DOMAIN, YOUR_VPS_IP) must be replaced with
> real values at the time of use. Do not serve
> production traffic until the HTTPS items pass.

## A. Purchase and access

- [ ] VPS purchased: Ubuntu Server LTS, 4 vCPU,
      8 GB RAM, 100–160 GB SSD/NVMe, public IPv4,
      firewall, backup/snapshot capability
      (starting specification, not a measured minimum;
      re-verify pricing, renewal, and refund terms).
- [ ] Data-centre region chosen (Singapore/Mumbai
      first candidates for latency from Pakistan;
      Frankfurt as farther fallback — compare
      latency, CPU/RAM/storage, bandwidth, backups,
      firewall, support, renewal pricing, refund
      policy at purchase time).
- [ ] SSH key login works; password authentication
      and root login disabled.
- [ ] Firewall allows only SSH, 80, 443.

## B. Server preparation

- [ ] System updated (`apt update && apt upgrade`).
- [ ] Docker Engine + Compose v2 installed and
      verified (`docker compose version`).
- [ ] Repository cloned; branch
      `phase-10-production-deployment` checked out
      (never deploy from `main`).
- [ ] `.env` created from `.env.example`,
      permissions `0600`, all real values filled in
      (no placeholder secrets).

## C. Secrets

- [ ] `SECRET_KEY` generated (not the placeholder).
- [ ] `CREDENTIAL_ENCRYPTION_KEY` generated
      (base64, 32 bytes) and backed up SEPARATELY
      from database backups.
- [ ] `POSTGRES_PASSWORD` generated (not `crypto`).
- [ ] `ENVIRONMENT=production` set.
- [ ] No secret committed to Git (check `git status`
      and the secret scan in section F).

## D. DNS and HTTPS

- [ ] Domain registered (real domain recorded here
      only after purchase: ______________________).
- [ ] A record points the domain at YOUR_VPS_IP;
      `getent hosts <domain>` returns the VPS IP.
- [ ] `scripts/setup-https.sh` run successfully;
      HTTPS request to the domain succeeds.
- [ ] HSTS enabled by that script AFTER the HTTPS
      check passed (verify the header in the
      response).
- [ ] Certificate renewal cron installed (twice
      daily) and tested with `setup-https.sh renew`.

## E. First deployment

- [ ] `scripts/production-check.sh` passes.
- [ ] `scripts/deploy.sh` passes (migrations run via
      the backend entrypoint; no manual downgrade).
- [ ] `scripts/health-check.sh` passes (backend,
      frontend, PostgreSQL, Redis).
- [ ] Admin health page shows real per-service
      status; no service reported healthy merely
      because config exists.

## F. Verification on the real stack

- [ ] PostgreSQL: fresh DB, migrations 0001→0010,
      head = 0010, constraints/FKs/indexes checked,
      Decimal precision checked, data persists
      across a container restart.
- [ ] Redis: connection, set/get with expiry,
      failure handling, recovery after restart.
- [ ] Docker Compose: `docker compose up --build`
      succeeds; healthchecks pass; volumes survive
      container recreation; restart behaviour
      verified.
- [ ] Scheduler: exactly one scheduler, 12 jobs,
      no duplicates, paused jobs stay paused.
- [ ] Telegram: dedicated test group configured,
      test message sent ONLY after explicit
      authorisation, formatting/delivery/failure/
      duplicate-prevention verified; production
      group pointed at only after test-group pass.
- [ ] Binance Spot: public data verified live.
- [ ] Binance Futures: availability checked; HTTP
      451 (if it occurs) preserved as degraded
      status — no restriction bypass, no proxy.
- [ ] Backup: `scripts/backup.sh` produces an
      integrity-checked dump; retention works.
- [ ] Restore drill: backup restored into a
      SEPARATE test database and verified; a
      production restore is never attempted without
      `--force-production` + typed confirmation.
- [ ] CI: workflow file added manually to
      `.github/workflows/ci.yml` on the branch
      (or GitHub App granted Workflows: Read and
      write) AND a GitHub Actions run succeeds.
      Until then CI is NOT passed.
- [ ] Frontend: login, logout, session expiry,
      overview, and one page per admin section
      verified against the live backend in a
      browser (HTTP-level checks in Stage A are
      not a substitute).

## G. Go-live gate

Do NOT tick this section until every item above
passes (or is explicitly accepted as a documented
risk by the owner):

- [ ] HTTPS verified, HSTS enabled.
- [ ] Backups scheduled (daily cron) and one
      restore drill completed.
- [ ] No HTTP-only production exposure.
- [ ] No default secrets anywhere.
- [ ] Monitoring in place (container status,
      disk, health checks, collection errors).
- [ ] Rollback procedure (guide section 24)
      understood and the pre-go-live backup taken.

## H. If anything fails

Stop, record the failure and the log output, and
do not work around it by disabling auth, bypassing
migrations, exposing internal ports, or serving
HTTP-only production traffic. Fix the root cause,
re-run the relevant checklist section, and only
then continue.
