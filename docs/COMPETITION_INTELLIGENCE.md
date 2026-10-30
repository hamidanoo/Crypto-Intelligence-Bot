# Competition Intelligence (Phase 5)

Binance trading competition discovery and lifecycle
management, built on the Phase 3 announcement collector.
Phase 5 is discovery and lifecycle only. It stores no
volume data and performs no volume aggregation: 30-minute
volume tracking, cumulative volume, and
multiplier-adjusted volume reports are Phase 6 work and
are explicitly out of scope here.

## Supported competition types

Classification comes from the announcement title only,
in this documented order (a team event is a team event
first, even if it is also a Futures event):

| Type | Title signal |
| --- | --- |
| TEAM | "team" |
| FUTURES | "futures" |
| SPOT | "spot" |
| VOLUME | "volume" |
| GENERAL | none of the above |

Spot trading competitions, Futures trading
competitions, volume competitions, token trading
campaigns, team competitions, individual competitions,
and special trading events are all discovered through
the same path: any announcement the Phase 3 classifier
marks TRADING_COMPETITION, plus ALPHA announcements
whose title contains "competition". The second group
matters in practice: the Phase 3 classifier's
"binance alpha" rule runs before its "competition"
rule, so "Binance Alpha Trading Competition" titles
are classified ALPHA, and without this rule they
would be missed by competition discovery entirely.
Those announcements keep their Phase 4 Alpha token
record as well; the two tables are independent and
share only the announcement link. The classifier
order itself was not changed, to avoid breaking
Phase 3/4 behaviour.
No competition structure is assumed: a competition
with no pairs, no reward pool, and no dates is still a
valid record, with those fields missing.

## Official data sources

- **Primary, and only, source:** the Phase 3 Binance
  website CMS feed, `https://www.binance.com` GET
  `/bapi/composite/v1/public/cms/article/list/query?type=1`.
  This is the official website's own feed, **not a
  documented public API**. Binance may change or block
  it without notice.
- **No third-party sources are used.** No unofficial
  source is treated as confirmed official information.
- **No market-data source is used in Phase 5.**
  Competition discovery is announcement-driven; the
  Phase 2 Binance client is not consulted for
  competitions, because volume work belongs to Phase 6.

## Article-content investigation (re-checked 2026-10-30)

Phase 3 found the CMS article-detail endpoint returned
code `000002 "illegal parameter"`. It was re-checked in
Phase 5 against a live list response (first article id
288627, code a259777ee4104befa3daba5c1eadc7b5):

- GET `/bapi/composite/v1/public/cms/article/detail/query?id=288627`
  → HTTP 400, `{"code": "000002", "message": "illegal parameter"}`
- Same endpoint with `articleId=` and with `code=`
  → identical HTTP 400 / `000002` responses.

Article bodies therefore remain unavailable. All
detail fields in Phase 5 come from announcement titles
and catalog metadata alone, and anything not in the
title stays null, empty, or UNKNOWN. This is a source
limitation, not a parsing choice, and it is the reason
the extraction rules below are conservative.

## Extraction methods

All extraction lives in `backend/app/competitions/parsing.py`
and uses only the title:

- **Name:** the title with a leading "Binance ",
  "Binance Futures ", or "Binance Spot " prefix
  stripped. The rest is kept verbatim; shortening it
  further would risk inventing a cleaner name than the
  official one.
- **Trading pairs:** uppercase pairs ending in USDT,
  USDC, BUSD, FDUSD, USDP, or TUSD, written as
  `BTCUSDT` or `BTC/USDT`, deduplicated in order.
  Eligible assets are the base assets of those pairs.
  No pairs in the title means an empty list, not a
  guessed list.
- **Reward pool:** only an explicit amount plus a
  currency (`100,000 USDT`) in a title that mentions
  rewards, a prize, or a pool. An amount without a
  currency, or a trading amount in a non-reward title,
  is not a pool. Stored as Decimal, never as a float.
  In particular, "$200K Worth of Rewards" is not
  parsed: it has no currency code and a K suffix, so
  the pool stays null rather than being converted by
  an assumed multiplier — exactly as the live smoke
  test showed for the two Alpha competitions.
- **Dates:** only an explicit ISO date range — "from
  YYYY-MM-DD to YYYY-MM-DD" or "starts YYYY-MM-DD ...
  ends YYYY-MM-DD" — parsed as UTC midnight. Any
  other date-like text is ignored, because its meaning
  (start, end, registration) cannot be verified from
  the title alone. Registration dates are therefore
  always null in Phase 5.
- **Rules, eligibility, multipliers:** not extractable
  from titles, so they are stored as empty lists in
  Phase 5. The JSON fields and the `competition_rules`
  table exist so Phase 6 and later work can fill them
  from a verified source when one becomes available.
  Multiplier rules are never assumed; Phase 6 must
  still distinguish official, estimated, and
  multiplier-adjusted volumes.
- **Unreliable names:** if the cleaned name is shorter
  than 5 characters, or the title contains none of
  "competition", "campaign", "event", "tournament",
  "challenge", the record is still created (for review)
  with `verification_status` "needs_review" instead of
  being silently dropped or given invented details.
  Everything else from the official feed is
  "official_website".

## Database structure

Migration `0006` (down_revision `0005`, old
migrations untouched) adds:

- `competitions` — one row per announcement
  (`announcement_id` unique), name, description
  (the full title), type, official URL, reward pool
  (Numeric) and currency, start/end/registration
  times (UTC, nullable), status, eligible pairs and
  assets (JSON), rules/eligibility/multiplier JSON
  lists, source, verification status, and a `metadata`
  JSON column holding the normalised name used for
  change detection, category confidence, and catalog.
- `competition_trading_pairs` — normalised pairs per
  competition, unique on (competition, pair), with
  base and quote assets.
- `competition_rewards` — reward rows per
  competition; in Phase 5 at most one row, created
  only when the title states a pool.
- `competition_rules` — rule rows per competition;
  empty in Phase 5, structure ready for later phases.
- `competition_updates` — the change history: every
  creation, status change, reward change, and pairs
  change, with old and new values. Important changes
  are never silently overwritten.
- `competition_collection_runs` — one row per
  scheduled processing run, with found/created/
  updated/skipped counts, status, and error message.

No volume tables are created in Phase 5.

## Lifecycle rules

Statuses: UPCOMING, ACTIVE, ENDED, CANCELLED,
POSTPONED, UNKNOWN.

- **Default:** UNKNOWN. A title alone never makes a
  competition ACTIVE or UPCOMING, because without
  verified dates that would be a guess.
- **Title signals:** "cancelled" → CANCELLED,
  "postponed" → POSTPONED, "ended"/"completed"/
  "concluded" → ENDED. Nothing else changes status
  from the title.
- **Date logic (`recompute_status`):** CANCELLED and
  POSTPONED are terminal and are never overwritten by
  dates. Without both dates, a previously determined
  UPCOMING/ACTIVE/ENDED status is preserved and
  UNKNOWN stays UNKNOWN. With both dates, now before
  start is UPCOMING, within the window is ACTIVE, and
  after end is ENDED. All comparisons are UTC
  internally; SQLite's naive datetimes are normalised
  to aware UTC before comparison (a bug found by the
  Phase 5 tests and fixed in parsing).
- **Change detection:** a later announcement with the
  same normalised name (lifecycle suffixes such as
  "has been cancelled" stripped for matching, and
  prefix matching only for lifecycle announcements,
  never for plain new competitions) updates the
  existing competition instead of creating a
  duplicate, and records a `CompetitionUpdate` for
  each changed field. A second processing run over the
  same announcements only skips them (dedupe by
  `announcement_id`, plus the unique constraint).

## API endpoints

All under the competitions router; pagination with
`page`/`page_size`, filters, sorting, Decimal values
serialised as strings, 404 for missing records, 400
for invalid sort values, 502 when announcement
collection fails, 503 on database errors:

- `GET /competitions` — filters: `competition_type`,
  `status`, `pair`, `start_from`, `start_to`,
  `end_from`, `end_to`, `search` (competition name);
  sorts: `start_time_asc/desc`, `created_at_asc/desc`,
  `reward_pool_desc`.
- `GET /competitions/active`, `/upcoming`,
  `/completed` (ENDED).
- `GET /competitions/{id}` — includes
  `duration_seconds` (null when dates are missing),
  reward pool, eligible pairs, status, and metadata.
- `GET /competitions/{id}/updates` — the update
  timeline, newest first.
- `GET /competitions/{id}/pairs` — normalised pairs,
  rewards, and rules for the competition.
- `POST /competitions/collect` — runs announcement
  collection via the existing Phase 3 service, then
  processes TRADING_COMPETITION announcements.

Manual collection is not admin-gated in this phase
(authentication is Phase 8), so it must only be
exposed behind the deployment's own access controls.

## Scheduler configuration

One new job on the existing single APScheduler
instance (no second scheduler is created):

- `competition_processing`, every 10 minutes
  (`intelligence_processing_interval_seconds`, default
  600), `max_instances=1`, `coalesce=True`.
- It processes stored TRADING_COMPETITION
  announcements and recomputes date-based statuses;
  it does **not** re-fetch the CMS feed (manual
  collect does that). Each run writes a
  `competition_collection_runs` row; one bad
  announcement is logged and counted as an error
  without stopping the rest of the run.

Single-instance limitation: APScheduler runs
in-process, so a multi-instance deployment would run
this job on every instance. Distributed coordination
is a later-phase item.

## Telegram notifications

Commands (existing aiogram router):

- `/competition` — latest competitions.
- `/competition active`, `/competition upcoming`,
  `/competition completed` — by status.
- `/competition search <name>` — by name.

Replies are concise, show the official link, show
reward pools and pairs only when confirmed, show
dates in Asia/Karachi time labelled PKT when dates
exist (otherwise "Not officially confirmed"), and say
"None recorded yet" when empty.

Notification formatters exist for: new competition,
starting, ending soon, postponement, cancellation,
and rule/reward changes. Duplicate prevention reuses
the Phase 4 `campaign_notifications` table with
`entity_type` "competition" — one row per
(competition, notification type) — rather than a
duplicate table with identical logic. Live delivery
is **not** verified (no token); formatting and
duplicate-prevention are covered by mock tests only.

## Known limitations

- No article bodies: dates, rules, eligibility, and
  multipliers are almost always missing, and that is
  recorded as missing, not estimated.
- Status is UNKNOWN for most competitions until
  verified dates or a lifecycle announcement exist.
- Change detection by normalised name only handles
  announcements whose titles are built on the
  original name; a differently-worded update
  announcement creates a separate record for review.
- The scheduler is single-instance (see above).
- Manual collection endpoints are ungated until
  Phase 8 authentication.

## External verification still required

- Live PostgreSQL migration `0006`, Docker Compose
  run, production-environment scheduler execution.
- Live Binance competition announcements beyond the
  smoke test (see the Phase 5 report).
- Live Telegram delivery (mock tests only).
- All pre-existing open items: live PostgreSQL
  0001–0005, Docker, Redis-backed cache, live Futures
  (VPS in an allowed location), live Prime Sale
  processing.
- `.github/workflows/ci.yml` remains local-only
  (GitHub App 403 for workflow files).
