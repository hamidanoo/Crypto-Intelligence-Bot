# Competition Volume Tracker (Phase 6)

30-minute UTC volume tracking for Phase 5 trading
competitions, from Binance public trade data. This
page is the methodology record: what each volume
figure means, where it comes from, and what is
explicitly not claimed.

## The three volumes — never blurred

- **Public Market Volume**: what Binance public
  trades show for a pair in an interval — base
  volume (sum of trade quantities) and quote volume
  (sum of trade quote quantities, derived as price x
  quantity per trade; see below). Source: Binance
  Spot aggTrades.
- **Estimated Eligible Volume**: public base volume
  multiplied by a multiplier, calculated ONLY when a
  `CompetitionPairConfiguration` exists with
  `multiplier_verified=True` and a multiplier set.
  Otherwise it is null, displayed as "Unavailable".
  No multiplier, weight, or eligibility rule is ever
  invented. Every estimate names its method in
  `calculation_method`.
- **Official Eligible Volume**: ONLY a figure
  verified by an authoritative Binance source. No
  such source is implemented in Phase 6, so this
  field is always null and displayed as
  "Unavailable", never zero.
- **Official Leaderboard Data**: not implemented,
  never claimed. Public market volume is never
  presented as eligible volume or as a leaderboard.

## Data source decision

Primary source: Binance Spot aggTrades
(`GET /api/v3/aggTrades`) with exact exchange
timestamps, because trade-level data gives exact
accuracy at competition start/end boundaries.

Rejected alternatives, and why:

- **Klines**: a 30-minute kline cannot be split at
  a mid-interval competition boundary, so kline
  volume would misattribute trades outside the
  competition window. Klines are never substituted
  for aggTrades.
- **Rolling-24h-ticker subtraction**: forbidden.
  Subtracting successive 24h ticker volumes does not
  give interval volume and is never used anywhere in
  this phase.

Two live aggTrades behaviours found during Phase 6
testing (2026-10-30) are handled in code and covered
by tests:

1. **No quote-quantity field**: the live aggTrades
   response carries `p` (price) and `q` (quantity)
   but no `Q` field, so quote volume is derived per
   trade as `Decimal(price) x Decimal(qty)` in
   `BinanceClient.get_agg_trades` (Decimal, never
   float). When a `Q` field is present it is used
   as returned.
2. **Paging rule**: Binance rejects `fromId`
   combined with `startTime`/`endTime`
   ("Combination of optional parameters invalid").
   Collection therefore fetches the first page with
   the time window only, and later pages with
   `fromId` only; bucketing filters every page to
   `[interval_start, interval_end)` regardless, so
   trades spilling past the interval end from a
   `fromId`-only page are excluded, never counted.

If aggTrades is unavailable for a symbol, the
interval is marked `incomplete` and its volumes stay
null — never zero, never fabricated.

## Intervals

Intervals are half-open 30-minute UTC boundaries:
00:00–00:30, 00:30–01:00, and so on. Only intervals
whose end is at or before "now" are collected or
reported; an in-progress interval is never published.

- `interval_bounds_for(dt)`: the interval
  containing `dt`.
- `completed_intervals_between(start, end, now)`:
  intervals overlapping `[start, end)` with
  `end <= now`.
- **Boundary intervals**: if a competition starts
  or ends mid-interval, that interval is marked
  `partial` and only trades inside
  `[competition_start, competition_end)` are
  counted. A competition with no dates never makes
  an interval partial.
- **Missing data is never zero**: a fetch failure
  produces `data_status=incomplete` with null
  volumes; a successful fetch that genuinely
  returned no trades in the window produces
  Decimal 0 with status `complete`. The two cases
  are distinct in code, API, Telegram, and frontend
  labels.

## Collection and backfill

`collect_competition_volumes(db, client, now)` in
`backend/app/volume/collection.py`:

- Global runs process ACTIVE/UPCOMING competitions
  only. A manual single-competition collect
  processes that competition regardless of status,
  because the caller asked for it explicitly.
- Pairs come from Phase 5 `CompetitionTradingPair`
  rows; a competition with no pairs gets a
  collection run with 0 intervals and a note, never
  invented pairs. A pair with a configuration row
  with `tracking_enabled=False` is skipped.
- Missed intervals are determined from the per-pair
  `CompetitionVolumeCheckpoint` (last contiguous
  collected interval end), or the competition start,
  or the last 24 hours when no start date exists.
- Backfill is capped at 48 intervals per pair per
  run (`VOLUME_BACKFILL_MAX_INTERVALS_PER_PAIR`);
  intervals beyond the cap are counted as skipped
  and picked up by the next run.
- Fetching is paged by `fromId` (see the paging
  rule above) with a bounded page guard
  (`VOLUME_MAX_PAGES_PER_INTERVAL`, default 50);
  exceeding the guard marks that interval
  `incomplete` and collection continues.
- Upserts are idempotent on the unique constraint
  (competition, pair, interval_start):
  re-collecting the same interval from the same
  trade set yields identical totals (counted as
  skipped); a re-fetch returning additional late
  trades updates the totals and marks the interval
  `recalculated`, without creating a duplicate row
  and without re-sending a Telegram report.
- The checkpoint advances only over the longest
  prefix of complete/partial intervals from the
  run's window start. An incomplete interval stops
  the advance (it is retried next run), even though
  later intervals in the same run are still
  collected; the next run re-processes from the
  checkpoint, idempotently.
- One pair's failure never stops other pairs or
  competitions; errors are recorded on the
  collection run (`CompetitionVolumeCollectionRun`).
- Collection is safe to retry and safe under
  overlap: the scheduler job uses `max_instances=1`,
  and collection itself relies on the interval unique
  constraint.

Cumulative volume is computed ONLY by summing
stored intervals for a competition+pair
(`cumulative_volume` in
`backend/app/volume/aggregation.py`): complete and
partial-boundary intervals contribute their stored
volumes; incomplete intervals (null volumes)
contribute nothing. It is therefore reproducible
from interval data, and a test verifies it equals
a DB-side SUM over the same rows. All financial
math uses Decimal via string conversion; no float
financial math exists in this phase.

## Scheduler

One new job on the existing single APScheduler
instance (see `backend/app/scheduler.py`):
`competition_volume_tracking`, every 30 minutes
(`VOLUME_TRACKING_INTERVAL_MINUTES`), with
`max_instances=1`, `coalesce=True`, and
`misfire_grace_time=60`. It runs collection, then
the Telegram reporting pass.

APScheduler interval triggers are not guaranteed to
align to :00/:30 wall-clock boundaries. That is
safe because only completed intervals are
processed: a late trigger collects the same
completed intervals, idempotently. The scheduler
remains single-instance; a multi-instance
deployment would run the job on every instance
(the same documented limitation as earlier phases).

## Telegram reporting

After collection, `send_volume_reports` reports
every newly completed (complete or partial)
interval with no sent `CompetitionVolumeReport`
row, via the Phase 3 injectable-sender pattern
(`send_telegram_message` with a `bot` argument for
tests, otherwise a real bot from the configured
token and group id).

Each report contains: competition name, reporting
period in UTC plus PKT display (both labelled),
trading pair, public market volume (base + quote,
or "Unavailable" if null), estimated eligible
volume (value + method, or "Unavailable"),
official eligible volume ("Unavailable"), data
status, last updated UTC, cumulative public volume
(sum of stored intervals), and the calculation
method "Binance public trade data (aggTrades)".

Rules:

- Incomplete intervals get no Telegram report, ever.
- A sent report is never re-sent: the unique
  constraint on (competition, pair, interval_start)
  plus the status check blocks retries and
  re-collections. A failed row may be retried and
  is updated in place, never duplicated.
- Telegram errors and rate limits are recorded on
  the report row, never raised to break other
  competitions.
- Notifications are gated by
  `VOLUME_NOTIFICATIONS_ENABLED` (default on, same
  config style as the Phase 3 category setting in
  spirit: a setting controls the pass). Without a
  bot token and group id, sending is skipped
  without marking anything sent.
- Live delivery remains unverified without a token;
  mock-format tests only, stated plainly.

## API

Route naming divergence, stated explicitly: the
routes are `/competition-volume` (no `/api/v1`
prefix), matching the existing routers
(`/announcements`, `/alpha`, `/competitions`). The
frontend calls `/api/competition-volume`, which the
frontend proxy maps to the backend route. There is
no `/api/v1/competition-volume` route. See
`docs/API.md` for the endpoint list.

Manual collect endpoints are ungated until Phase 8
auth and must only be exposed behind the
deployment's own access controls. Collect returns
502 when the whole collect fails upstream with
nothing usable collected (individual pair failures
are recorded on the run and stay 200 when other
intervals were collected), and 503 on database
errors. Decimals are serialised as strings.

## Frontend

The home page (`frontend/app/page.tsx`) gains a
Competition Volume section (not the full Phase 8
dashboard): competition selector, trading-pair
selector, latest completed 30-minute volume,
cumulative public volume, estimated eligible volume
when available, official eligible volume shown as
Unavailable, interval history table, a Recharts bar
chart of public quote volume over intervals
(Recharts was already a frontend dependency; no new
dependency was added), data-completeness indicators
(data status, recalculated flag), last collection
timestamp, and UTC + PKT labels, with public,
estimated, and official volumes kept visually
separate. It uses only real backend data — no mock
or hardcoded statistics.

## Database

Migration `0007` (down_revision `0006`, old
migrations untouched) adds:

- `competition_volume_intervals` — one row per
  competition+pair+interval, unique on that triple,
  with public/estimated/official volumes (Numeric),
  `calculation_method`, `data_status`
  (complete/partial/incomplete), `recalculated`,
  and `collected_at`.
- `competition_volume_checkpoints` — per-pair
  resume point (`last_interval_end`,
  `last_trade_id`), unique on competition+pair.
- `competition_volume_collection_runs` — per
  competition run with found/created/updated/
  skipped counts, status, and error message.
- `competition_volume_reports` — one report attempt
  per competition+pair+interval, unique on that
  triple, with status (sent/failed/pending),
  `sent_at`, message text, and error message.
- `competition_pair_configurations` — per-pair
  multiplier (only applied when
  `multiplier_verified=True`), tracking toggle,
  calculation method, and note, unique on
  competition+pair.

All timestamps are UTC; all money/volume columns
are Numeric (Decimal).

## Configuration

New settings in `.env.example` (all actually
implemented and read from `app/config.py`):

- `VOLUME_TRACKING_INTERVAL_MINUTES=30` —
  scheduler interval.
- `VOLUME_BACKFILL_MAX_INTERVALS_PER_PAIR=48` —
  backfill cap per pair per run.
- `VOLUME_MAX_PAGES_PER_INTERVAL=50` — aggTrades
  page guard per interval.
- `VOLUME_NOTIFICATIONS_ENABLED=true` — Telegram
  volume report pass on/off (still requires
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_GROUP_ID`).

## Known limitations and production verification

- Live Spot aggTrades was verified from this
  environment via `data-api.binance.vision` (see
  "Live test results" below); `api.binance.com`
  remains location-restricted here (HTTP 451, code
  0). In production, point
  `BINANCE_SPOT_BASE_URL` at the reachable endpoint
  for the deployment location.
- Live PostgreSQL migration `0007`, Docker run,
  live Telegram delivery, and a production
  scheduler run are NOT verified (SQLite migration,
  mock Telegram, and live aggTrades via the vision
  endpoint were verified).
- No official eligible volume source and no
  leaderboard source is implemented; both stay
  "Unavailable"/unclaimed until a verified source
  exists.
- Admin gating for manual collect is Phase 8 work.
- The GitHub Actions workflow file
  `.github/workflows/ci.yml` remains local-only
  (GitHub App 403 for workflow files, documented in
  the fix pass); local checks run via
  `scripts/check.sh`.

## Live test results (2026-10-30, this environment)

- `GET /api/v3/aggTrades` via
  `data-api.binance.vision` for BTCUSDT over the
  last completed 30-minute interval (10:00–10:30
  UTC): 26,000 trades fetched across 26 pages
  (first page windowed, later pages `fromId`-only;
  pages spilling past 10:30 were filtered by
  bucketing to 24,208 in-interval trades).
  Bucketed public volume: base 426.84376 BTC,
  quote 33,070,381.6869031 USDT. This is a smoke
  test of the client and bucketing only — no
  competition interval was written from it, and it
  is not presented as any competition's volume.
- Same call via `api.binance.com`: HTTP 451, code
  0, "Service unavailable from a restricted
  location" — the known location limitation, not a
  code failure.
- First live attempt also exposed the two aggTrades
  behaviours documented above (missing `Q` field,
  forbidden `fromId`+time-window combination);
  both were fixed in code and are covered by tests
  before this document was written.
