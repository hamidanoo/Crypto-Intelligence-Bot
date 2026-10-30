# Binance Alpha Intelligence (Phase 4)

## Source

The primary discovery source is the Phase 3 Binance
announcement source: the official Binance website CMS
feed, GET
`/bapi/composite/v1/public/cms/article/list/query`
(type=1). That feed is the website's own feed, not a
documented public API, and may change or be blocked
without notice. No third-party source is used for Alpha
data in this phase. Market data, when available, comes
from the Phase 2 Binance Spot client
(`/api/v3/ticker/24hr` for SYMBOLUSDT).

## How it works

Announcements already classified as ALPHA by Phase 3
are processed into `alpha_tokens`, one record per
announcement, deduplicated by `announcement_id`
(unique constraint as well as a pre-check). A second
processing run skips already-processed announcements.
A creation record is written to `alpha_token_updates`,
and `refresh_alpha_market_data` writes a
`price_update` record whenever a token's price or
volume changes.

## Parsing rules

- Symbol: the first parenthesised uppercase group in
  the title, for example (TEST).
- Name: the text before that group, with announcement
  prefixes stripped, including "Trading Competition:
  Trade " for campaign titles.
- Contract address: a `0x` + 40 hex character string
  in the title, otherwise null.
- Network: BNB Chain, Ethereum, Solana, Arbitrum,
  Base, or Polygon when named in the title, otherwise
  null.
- Removal announcements ("will remove") list many
  tokens, so they are never recorded as a single token:
  they are stored with token name "Multiple tokens
  (removal announcement)", no symbol, trading status
  `removal_announced`, and `is_multi_token: true` in
  token metadata. This was found in live testing:
  the current feed's Alpha announcements are mostly
  trading competitions and removal lists, not new
  token listings, and the parser was corrected so
  those do not become false single-token records.
- Trading status is `announced` unless the title
  says trading is live or available, in which case it
  is `trading`. The conventional USDT pair
  (SYMBOLUSDT) is recorded as the pair probed for
  market data; it is not, by itself, proof that the
  token trades on Spot.

## Market data

Market data is attempted only when a symbol exists.
On success, price, 24h change, and 24h volume are
stored as Decimal, with `market_data_status`
"available". On any failure (including a symbol that
does not trade on Spot, which returns 400), the
fields stay null and the status is "unavailable".
Unavailable data is never presented as zero.

## Notifications

Formatters for new Alpha tokens live in
`app/intelligence/notifications.py`, following the
Phase 3 HTML + source-link pattern.
`CampaignNotification` records one row per
(entity, notification type), so a second run cannot
send the same notification twice. Automatic delivery
still requires Telegram configuration and was not
verified live in this phase (mock formatting tests
only).

## Scheduler

`alpha_processing` runs every 10 minutes by default
(`INTELLIGENCE_PROCESSING_INTERVAL_SECONDS`, 600),
on the same APScheduler instance as every other job,
with `max_instances=1` and `coalesce=True`.
Single-instance limitation: a multi-instance
deployment would run the job on every instance;
distributed coordination is a later-phase item.

## Limitations

- Announcement bodies are not fetched, so contract
  addresses, networks, and full campaign details are
  often null; null means "not in the title", not
  "does not exist".
- No live Telegram delivery, live PostgreSQL, or
  Docker verification yet (see
  docs/EXTERNAL_VERIFICATION.md).
- Manual collection endpoints are not admin-gated
  until Phase 8 authentication; expose them only
  behind deployment access controls.
