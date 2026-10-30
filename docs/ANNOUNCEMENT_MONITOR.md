# Announcement Monitor (Phase 3)

Phase 3 provides the shared announcement collection and
processing foundation. It does NOT implement the complete
Alpha, Airdrop, Prime Sale, or Competition modules; those
phases reuse this foundation and add their own rules on top.

## Supported sources

### Binance Announcements (default, seeded automatically)

- **Source name:** Binance Announcements
- **Source type:** `binance_website_cms`
- **Official or third-party:** Official Binance website data,
  served from `https://www.binance.com`. The endpoint itself
  is NOT a documented public API (see below), so the source
  is labelled "official website", not "documented public API".
- **Access method:** HTTP GET, no authentication, no API key.
  Endpoint: `/bapi/composite/v1/public/cms/article/list/query`
  with query parameters `type=1`, `pageNo=1`,
  `pageSize=<page_size>` (default 20, configured per source).
- **Data format:** JSON. Response `code` is `"000000"` on
  success. `data.catalogs[]` groups articles by catalog;
  each article has `id`, `code`, `title`, and `releaseDate`
  (milliseconds since epoch).
- **Catalogs observed in live testing (2026-10-30):**
  48 New Cryptocurrency Listing, 49 Latest Binance News,
  93 Latest Activities, 161 Delisting, 157 Maintenance
  Updates, 51 API Updates, 128 Crypto Airdrop.
- **Update frequency:** On publication by Binance. This
  system polls every 5 minutes by default
  (`ANNOUNCEMENT_POLLING_INTERVAL_SECONDS`, per-source
  `polling_interval_seconds`, minimum 60 seconds via the API).
- **Rate limits:** Binance does not publish a limit for this
  website endpoint. Polling every 5 minutes with one page
  per run is modest; the client retries 429/5xx with
  exponential backoff and records failures as failed runs.
  Do not poll more often without checking for 429s first.
- **Reliability:** Good in live testing from this
  environment (see below), but fragile by design: Binance
  may change the endpoint, block it with CloudFront 403,
  or change the response shape without notice. The
  collector never fabricates data on failure; it records
  a failed CollectionRun and surfaces the error.
- **Available categories:** All Phase 3 categories, via
  title rules and catalog fallback (see Classification).
- **Authentication:** None required.
- **Canonical URL:** Derived from title and code:
  `https://www.binance.com/en/support/announcement/<slug>-<code>`,
  where `<slug>` is the lower-case, hyphenated title.
  The `code` is the stable identifier; the slug is
  presentation only. This pattern was verified live for
  one article (HTTP 202 from Binance's challenge page,
  with the correct URL).
- **What is NOT fetched:** Article body/detail. The detail
  endpoint tried during investigation returned
  `code 000002 "illegal parameter"`, so Phase 3 stores
  title, catalog, publication time, and link only, with
  `summary` and `original_content` left null. A later
  phase may add detail fetching if a working endpoint is
  found, without changing the collection engine.

### Sources investigated and rejected / deferred

- **api.binance.com / fapi.binance.com public APIs:** No
  announcement endpoint exists there; they serve market
  data only (Phase 2). Not used for announcements.
- **Binance support HTML page
  (`/en/support/announcement`):** No structured data, and
  direct fetching returned HTTP 202 (challenge page) in
  this environment. Not used; the CMS JSON endpoint is
  preferred.
- **Binance CMS POST endpoint:** A POST to the same CMS
  path timed out in this environment, while GET succeeded.
  GET is used.
- **Third-party announcement scrapers / aggregators:** Not
  used. They would add unverified data and fragile
  dependencies for no benefit over the official website
  feed.

## Collection architecture

```
Binance CMS (GET, JSON)
  -> BinanceAnnouncementClient.fetch_announcements()
  -> normalize_article() (slug, canonical URL, UTC time, hash)
  -> classify_announcement() (category + confidence)
  -> collect_from_source_async() (deduplicate, persist, run)
  -> notify_pending_announcements() (Telegram, once only)
```

- **Scheduled collection:** One APScheduler job,
  id `announcement_collection`, every 5 minutes,
  `max_instances=1`, `coalesce=True`. It collects from
  every enabled source that is due (last success older
  than its polling interval), then runs a notification
  pass. Registration is idempotent: a second call to
  `register_jobs()` does not duplicate the job.
- **Manual collection:** `POST /announcements/collect`
  (all enabled sources, or one source by id) and
  `POST /announcements/sources/{id}/collect`.
- **Source-specific collectors:** The engine is
  source-agnostic except for the Binance CMS client.
  A new source needs a client returning the normalised
  article shape, plus an `AnnouncementSource` row; the
  service, deduplication, runs, and notifications are
  reused unchanged.
- **Parsing and normalization:** Titles are stripped,
  publication times are converted from milliseconds to
  UTC datetimes, and content hash is
  SHA-256 of `title|code|published_at`.
- **Duplicate detection:** By `(source_id, external_id)`
  and by `canonical_url` (both unique in the database),
  never by title alone. A re-collected article with a
  changed title/category is updated in place, not
  duplicated, and counted as skipped.
- **Collection status tracking:** Every attempt creates a
  `CollectionRun` before fetching, with found / created /
  skipped counts, status, and error message.
- **Retry handling:** CMS client retries network errors,
  429, and 5xx with exponential backoff (non-numeric
  Retry-After falls back to backoff). A failed run does
  not retry immediately; the next scheduled run retries.
- **Recovery after restart:** Scheduler jobs are
  re-registered on API startup (APScheduler is
  in-memory, not persistent). Announcements published
  while the app was down are found on the next poll, as
  long as they are still within the first page
  (page_size per catalog). If more than page_size
  articles per catalog were published while down, the
  oldest of those could be missed — this is a known
  limitation, mitigated by manual collection with a
  larger page_size.
- **Redis:** Not required for Phase 3 collection.
  The existing Redis cache (Phase 2) is not used for
  announcements; a Redis lock for multi-instance
  coordination is a later-phase item (see Limitations).

## Polling intervals

- Default job interval: 5 minutes.
- Default source polling interval: 300 seconds.
- Per-source interval is configurable via
  `PATCH /announcements/sources/{id}` (60–86400 seconds).
- The scheduler job checks each source's last success
  time against its interval, so a source with a longer
  interval is skipped until due.

## Category classification

Rules in `app/announcements/classifier.py`, in order:
title rules (delisting, airdrop, Alpha, Prime Sale,
competition, Futures launch, token migration, deposit /
withdrawal, maintenance, listing) first, then catalog
fallback (48 Spot Listing, 49 General, 51 Other,
93 Other, 128 Airdrop, 157 Maintenance, 161 Delisting),
then OTHER with low confidence.

- **Confidence:** "high" for an explicit title match,
  "medium" for a catalog fallback or a plain "will list"
  match, "low" when no rule matches.
- **Uncertain announcements are never labelled
  confirmed:** a low-confidence OTHER category, and a
  medium-confidence listing, are exactly that — the
  source is official, the category is a heuristic.
  `verification_status` ("official_website") describes
  the source, not the category.
- **Extensibility:** Add a rule or a catalog mapping in
  the classifier; later phases reuse the same category
  list and add their own detail extraction on top.

## Database design

See `docs/DATABASE.md` for the full schema. Summary:

- `announcement_sources`: name (unique), source_type,
  base_url, enabled, polling_interval_seconds,
  configuration (JSON), last_success_at, last_error_at,
  last_error_message, created/updated at (UTC).
- `announcements`: source_id, source_name, external_id,
  code, title, slug, canonical_url (unique),
  category + category_confidence, summary, original_content,
  published_at (UTC), collected_at (UTC), content_hash,
  verification_status, metadata (JSON: catalog_id,
  catalog_name, type), notification_status, notified_at,
  notification_attempts, last_notification_error.
  Unique: `(source_id, external_id)` and `canonical_url`.
  Indexes on source, external id, code, category,
  published/ collected time, content hash, notification
  status.
- `collection_runs`: source_id, started/completed at
  (UTC), status (running/success/failed), found/created/
  skipped counts, error_message. Indexes on source,
  started time, status.
- Migration `0004` (from `0003`) creates all three
  tables; it is non-destructive and does not alter
  previous tables.

## API endpoints

See `docs/API.md` for request/response formats. Summary:

- `GET /announcements` — pagination (page, page_size
  1–100), category, source_id, title search, published
  date range, sort (published_at_desc/asc,
  collected_at_desc).
- `GET /announcements/{id}` — one announcement, 404 if
  missing.
- `GET /announcements/categories` — category list with
  counts from the database.
- `GET /announcements/sources` — all sources.
- `GET /announcements/collection-runs` — pagination,
  source and status filters.
- `POST /announcements/collect` — manual collection,
  optional source_id and page_size in the body.
  Returns runs + created/skipped counts; 502 if all
  runs failed, 503 on database failure.
- `POST /announcements/sources/{id}/collect` — manual
  collection for one source; 404 if missing, 400 if
  disabled.
- `PATCH /announcements/sources/{id}` — enable/disable,
  polling interval (60–86400), configuration.

Database failures on read endpoints return 503, not 500.

## Telegram notification behaviour

- **Only new announcements:** Notification status starts
  as "pending" (or "disabled" if its category is excluded
  by `ANNOUNCEMENT_NOTIFICATION_CATEGORIES`).
- **Duplicate prevention:** A record is only sent when
  its status is not "sent", and a successful send
  immediately marks it "sent" with `notified_at`.
  Re-collection does not re-notify.
- **Message format (HTML, title escaped):**
  category, title, published time (UTC), source name,
  and a link to the canonical URL.
- **Delivery errors:** Caught per announcement, recorded
  as "failed" with error and attempt count, and retried
  by the next notification pass up to 3 attempts total.
  A failure in one announcement does not stop others.
- **Categories:** Set
  `ANNOUNCEMENT_NOTIFICATION_CATEGORIES` to a
  comma-separated list to notify only those categories;
  empty (default) means all categories.
- **Live delivery:** Requires `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_GROUP_ID`. Without them, sending is skipped
  and the record stays "pending" — it is never marked
  sent without a real delivery. Live delivery was NOT
  tested in this phase (no token available); mock
  sender tests cover formatting, duplicate prevention,
  and failure handling.

## Configuration

Environment variables (see `.env.example` for the full
list; Phase 3 additions):

- `BINANCE_ANNOUNCEMENTS_BASE_URL` — default
  `https://www.binance.com`
- `BINANCE_ANNOUNCEMENTS_ENDPOINT` — default
  `/bapi/composite/v1/public/cms/article/list/query`
- `ANNOUNCEMENT_POLLING_INTERVAL_SECONDS` — default 300
- `ANNOUNCEMENT_NOTIFICATION_CATEGORIES` — default empty
  (all categories)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_GROUP_ID` — required
  only for live Telegram delivery (Phase 1, already
  documented).

No secrets are hardcoded or committed. No credentials
are logged.

## Known limitations

- The CMS endpoint is undocumented and may change or
  be blocked; the system handles that as a failed run,
  not as data.
- Article body/detail is not fetched (detail endpoint
  returned an error in investigation); summary and
  original_content are null in Phase 3.
- Classification is heuristic; a title like "Listing
  Will Be Postponed" is classified as a listing with
  medium confidence, not as a confirmed listing.
- APScheduler is single-instance: multiple API instances
  would each run the collection job. Redis distributed
  locking is deferred to a later phase.
- Page-size limit on restart recovery (see above).
- Admin authentication for manual collection and source
  configuration is a Phase 8 feature. In Phase 3 those
  endpoints are not admin-gated, so they must only be
  exposed behind the deployment's own access controls.
  This is stated on the endpoint documentation, not
  hidden.
- Frontend scope in Phase 3 is only a small "Latest
  announcements" section on the existing home page,
  showing real collected data or "No announcements
  collected yet" — not a dashboard (Phase 8).

## External verification requirements

- Live PostgreSQL migration `0004` execution (SQLite
  execution verified; PostgreSQL not yet).
- Live Telegram delivery (mock tests only; no token).
- Live Docker Compose run with the scheduler job
  (scheduler registration tested; a 5-minute live run
  was not waited for in this phase).
- Live CMS collection on a VPS / Docker host (live
  collection was verified from this environment via
  the API, see Development Log; that is not a substitute
  for a production-environment run).
