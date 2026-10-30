# Market, Futures & News Intelligence (Phase 7)

Phase 7 adds three intelligence modules on top of the
existing platform. It does not rebuild Phase 2 market
data, Phase 3 announcements, or Phase 5 competitions,
and it does not build the Phase 8 admin dashboard.

## Reuse decisions (documented, not hidden)

- Market prices reuse the Phase 2 `MarketSnapshot`
  table. No second price table was created.
- Funding rates, next funding time, mark price, and
  open interest reuse the Phase 2 `FuturesSnapshot`
  table. No second funding/open-interest table was
  created; history queries read `FuturesSnapshot`.
- Long/short ratios are genuinely new (no ratio
  fields exist in `FuturesSnapshot`), so they get
  the new `futures_market_ratios` table.
- News is built from Phase 3 announcements, not by
  duplicating them: `CryptoNews.announcement_id` is
  unique, and a second processing run creates
  nothing new.
- Notification duplicate prevention reuses the
  Phase 4 `campaign_notifications` table
  (`entity_type` "market_alert" / "crypto_news").
- The scheduler, API patterns, and Telegram
  notification patterns are the existing ones.

## Market intelligence

Source: Binance Spot public market data
(`/api/v3/ticker/24hr`, single symbol and all
tickers). The client method `get_all_tickers_24hr`
keeps values as strings so the service converts
them to Decimal via `str()`, never via float.

- Overview: latest `MarketSnapshot` per symbol,
  with price, 24h change, 24h base and quote
  volume, high/low, source, collection time, and
  an `is_stale` flag (older than
  `MARKET_FRESHNESS_MINUTES`, default 10).
- Gainers/losers: top 10 each by 24h percent
  change (configurable limit), excluding symbols
  below `MARKET_MIN_QUOTE_VOLUME_USDT` (default
  1,000,000). Excluded symbols are counted in
  `excluded_low_liquidity`, not hidden silently,
  and are never presented as reliable
  opportunities. Rows without a percent change
  are excluded as unavailable records.
- Watchlist: `MarketWatchlist` rows (symbol
  unique). The API returns the latest snapshot
  price per watchlist symbol, or null with
  `is_stale: true` when none exists.
- Movement detection: the latest snapshot is
  compared with the previous snapshot per symbol.
  A price alert fires at the configured threshold
  (default 5%; the stored threshold is 10% when a
  10% move is reached, else the configured
  level). A volume alert fires when quote volume
  reaches `MARKET_VOLUME_SPIKE_MULTIPLIER`
  (default 2.0) times the previous snapshot.
  Alerts are records of threshold crossings, never
  trading recommendations, and price movements are
  never described as opportunities.
- Alert cooldown/dedup: one alert per symbol +
  alert type within `MARKET_ALERT_COOLDOWN_MINUTES`
  (default 60). A second detection in the window
  creates nothing.
- Data freshness: snapshots older than the
  freshness window are flagged stale in API and
  frontend output. Alerts are never sent from
  stale or incomplete data by the scheduler jobs,
  which compare stored snapshots only.

## Futures intelligence

Source: Binance Futures public endpoints
(`fundingRate`, `premiumIndex`, `openInterest`,
and the long/short ratio endpoints). All values
are Decimal in storage.

- Funding: symbol, rate, next funding time,
  mark price, source, collection time, stored in
  `FuturesSnapshot`. Highest/lowest funding
  lists sort the latest snapshot per symbol.
  Funding alerts reuse `MarketAlert` with types
  `funding_high` / `funding_low` at
  `FUTURES_FUNDING_ALERT_THRESHOLD` (default
  0.001, i.e. 0.1%), with the same cooldown rule.
- Open interest: latest value per symbol, plus
  the percent change between the two latest
  snapshots (`open_interest_change_percent_since_previous`).
  Open interest alone is never used to infer
  market direction; the API and frontend say so.
- Long/short ratios: four datasets, each stored
  under its own `ratio_type` and never merged:
  `global_account`, `top_account`,
  `top_position` (account vs position ratios are
  different datasets), and `taker_buy_sell_volume`
  (where the stored values are buy/sell volumes
  and `long_short_ratio` is the buy/sell ratio).
  Period and collection time are stored.

### Futures availability and HTTP 451

From this environment, `fapi.binance.com` returns
HTTP 451 "Service unavailable from a restricted
location". Phase 7 handles this as degraded mode,
by design:

- A Futures failure is caught per symbol, recorded
  on a `MarketCollectionRun` (job
  `futures_collection`) with status
  `degraded` (some symbols collected) or
  `unavailable` (none collected), and returned in
  API output. It never raises to break Spot
  collection or the application.
- `POST /futures/collect` returns 502 only when
  the whole collection is unavailable; partial
  failures return 200 with status `degraded` and
  the errors listed.
- `GET /futures/summary` reports `availability`
  (`available` / `degraded` / `unavailable`),
  the last collection status and error.
- No geographic restriction is bypassed, and no
  unofficial proxy is used to evade one. Live
  Futures verification requires a VPS in an
  allowed location, as in earlier phases.

## Listings, delistings, and news

Primary source: Phase 3 Binance announcements
(the official website CMS feed, undocumented,
documented as such in `docs/ANNOUNCEMENT_MONITOR.md`).
No announcement is duplicated into news.

Category mapping (announcement -> news):

- `SPOT_LISTING`, `FUTURES_LISTING` -> `LISTINGS`
- `DELISTING` -> `DELISTINGS`
- Other categories -> keyword rules first
  (delist, hack, exploit, security, regulation,
  ETF, NFT, DeFi, Bitcoin, Ethereum, inflation /
  interest rate / Federal Reserve), then the
  announcement-category fallback, else `OTHER`.

News fields: headline, summary (null when
article bodies are unavailable — the API
serialises this as "Summary unavailable" with
`summary_available: false`; summaries are never
invented), original URL, publisher, category,
related symbols, published timestamp, collected
timestamp, source identifier, duplicate
fingerprint, processing status. Full copyrighted
articles are never reproduced.

- Related symbols: trading-pair bases in the
  title, parenthesised listing symbols (as in
  "Binance Will List Foo (FOO)"), and known
  tickers as whole words. A title with no
  identifiable symbol yields an empty list, never
  a guessed symbol.
- Listing/delisting extraction: token name and
  symbol from the parenthesised group in the
  title, with listing prefixes stripped. Dates
  are never inferred: a listing/delisting date
  appears only when the source provides one, and
  in practice the title-only pipeline leaves
  dates null. A listing title such as "Listing
  Will Be Postponed" is classified `LISTINGS`
  because its announcement category is a listing
  category; postponement is a status of that
  listing announcement, not a separate category.
- Duplicate detection: unique `announcement_id`,
  unique `original_url`, and unique fingerprint
  (SHA-256 of normalised headline + canonical
  URL). The same story from different sources is
  kept as separate rows (different URLs and
  fingerprints), never silently deleted.
- RSS: a generic collector (`parse_rss` with
  stdlib XML, `collect_rss_items`) driven by
  `NewsSource` rows. The only enabled default
  source is "Binance Announcements". No
  third-party publisher feed is enabled by
  default, so no publisher is claimed as
  integrated until a feed is deliberately added
  as a `NewsSource` row and its reliability is
  assessed. RSS descriptions supplied by a
  publisher are used as summaries (truncated to
  500 characters); nothing is invented.

## Scheduler

All jobs run on the existing single APScheduler
instance, each with `max_instances=1` and
`coalesce=True`, idempotent registration:

| Job | Interval |
| --- | --- |
| `market_snapshot` | 5 minutes |
| `funding_collection` | 5 minutes |
| `open_interest_collection` | 15 minutes |
| `news_collection` | 5 minutes |
| `listing_processing` | 5 minutes |
| `market_movement_detection` | 5 minutes |

Each job logs and returns its result, never
raising to stop other jobs. Restart recovery is
via stored snapshots, alerts, and collection
runs: a restarted job reads the latest stored
state and continues. Times are UTC internally;
Telegram and frontend display uses Asia/Karachi
(PKT) labels alongside UTC.

## Telegram

Commands: `/market`, `/price <symbol>`,
`/gainers`, `/losers`, `/watchlist`, `/funding`,
`/funding <symbol>`, `/openinterest`,
`/longshort`, `/news`, `/news <category>`,
`/listings`, `/delistings`, `/alerts`,
`/marketalerts`. Arguments are validated;
invalid symbols get a usage message, not a
crash. Lists are capped at 5-10 items.
Unavailable data is shown as "Unavailable",
never as zero. Market alert, funding alert,
and news messages are formatted with source and
time, and duplicate prevention reuses
`campaign_notifications` (one row per entity +
notification type). Live delivery requires a
token and group id; without them, sending is
skipped (not marked sent) and live delivery
stays unverified.

## API

Routes are `/market`, `/futures`, `/news` (no
`/api/v1` prefix), matching existing routers;
the frontend calls `/api/market` etc., which
the proxy maps to these backend routes.
Decimals are strings. Manual collect endpoints
are ungated until Phase 8 authentication and
must only be exposed behind deployment access
controls; they are not claimed to be
authenticated. Full endpoint list: `docs/API.md`.

## Frontend

The existing home page gains Market, Futures,
and News sections (not the full dashboard):
market overview table with stale flags, top
gainers/losers, watchlist, futures availability
with highest/lowest funding, latest news with
category/publisher/published time/original
links, and listings. All data is real backend
data, with loading/error/empty states. UTC and
PKT labels are shown together.

## Configuration

New settings (all actually implemented; see
`.env.example`):

- `MARKET_SNAPSHOT_INTERVAL_MINUTES=5`
- `MARKET_MIN_QUOTE_VOLUME_USDT=1000000`
- `MARKET_ALERT_COOLDOWN_MINUTES=60`
- `MARKET_PRICE_ALERT_THRESHOLD_PERCENT=5.0`
- `MARKET_VOLUME_SPIKE_MULTIPLIER=2.0`
- `MARKET_FRESHNESS_MINUTES=10`
- `FUTURES_FUNDING_INTERVAL_MINUTES=5`
- `FUTURES_OPEN_INTEREST_INTERVAL_MINUTES=15`
- `FUTURES_FUNDING_ALERT_THRESHOLD=0.001`
- `NEWS_COLLECTION_INTERVAL_MINUTES=5`
- `MARKET_NOTIFICATIONS_ENABLED=true`

## Limitations and external verification

- Live Futures data is unverified here (HTTP
  451); it needs a VPS in an allowed location.
- Live Telegram delivery is unverified (no
  token); formatting and dedup are mock-tested.
- Live PostgreSQL migration 0008, Docker run,
  and a production scheduler run are unverified
  (SQLite migration, mock Telegram, and live
  Spot data via the vision endpoint were
  verified).
- News summaries stay unavailable until article
  bodies can be fetched; the article-detail
  endpoint still returned CMS 000002 in Phase 5.
- No RSS publisher feed is enabled by default;
  any future feed needs a reliability assessment
  before enabling.
- Manual collect endpoints remain ungated until
  Phase 8 authentication.
