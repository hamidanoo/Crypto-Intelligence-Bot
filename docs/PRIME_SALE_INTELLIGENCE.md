# Binance Prime Sale Intelligence (Phase 4)

## Source

The primary discovery source is the Phase 3 Binance
announcement source: the official Binance website CMS
feed (type=1). That feed is the website's own feed,
not a documented public API. No third-party source is
used for Prime Sale data in this phase.

## How it works

Announcements classified as PRIME_SALE are processed
into `prime_sales`, one record per announcement,
deduplicated by `announcement_id`, plus one
`prime_sale_allocation_rules` row per sale. A second
run skips already-processed announcements.

## Status rules (conservative)

A status is set only when the title contains the
listed phrase; otherwise the status is UNKNOWN:

- CANCELLED: "cancel".
- DISTRIBUTION_COMPLETED: "distribution" and
  "completed"/"done".
- ENDED: "subscription closed/ended", "ended", or
  "closed".
- ACTIVE: subscription open/live, "now live", or
  "now open".
- UPCOMING: "coming soon", "will begin", or
  "upcoming".

Live feed note: the current first page of
announcements contains no PRIME_SALE announcements,
so live processing created 0 Prime Sales. That is a
real result from the live feed, not a failure of the
processor (mock and seeded tests cover the
processing path).

## Sale fields

Subscription times, distribution time, trading
availability, subscription price, minimum/maximum
commitment, eligible assets, allocation methodology,
and reward information stay null in this phase,
because announcement bodies are not fetched and
titles do not contain them. No Prime Sale is assumed
to follow another sale's rules. Each sale's
allocation rule is recorded as `formula_type`
"unknown" with a description stating that the
methodology is not officially confirmed in the
announcement title.

## Allocation estimation

Endpoint: `POST /prime-sales/estimate-allocation`,
and bot command `/prime estimate <yours> <total>
<allocation>`.

Formula (proportional allocation):

    user allocation = (user commitment / total
    eligible commitment) x total token allocation

All arithmetic uses Decimal. The result is labelled
an estimate and is never a guarantee. A missing,
zero, or negative total commitment, user
commitment, or total allocation is rejected with a
clear error (400 from the service, 422 from
Pydantic validation of non-positive API inputs);
a total commitment is never fabricated. The caller
must supply verified inputs, including the total
commitment when it is known.

## Notifications

Formatters for new Prime Sales live in
`app/intelligence/notifications.py`, with a source
link when available. `CampaignNotification`
prevents duplicate notifications. Subscription
reminders and distribution updates use the same
mechanism; live Telegram delivery was not verified
in this phase (mock formatting tests only).

## Scheduler

`prime_sale_processing` runs every 10 minutes by
default on the same APScheduler instance as every
other job, with `max_instances=1` and
`coalesce=True`. Single-instance limitation applies
(see docs/ALPHA_INTELLIGENCE.md).

## Limitations

- No article bodies, so most sale detail fields are
  null and the allocation rule is "unknown".
- No Prime Sale announcements in the live first
  page at test time, so live Prime Sale processing
  is still unverified against a real Prime Sale
  announcement.
- No live Telegram delivery, live PostgreSQL, or
  Docker verification yet.
- Manual collection endpoints are not admin-gated
  until Phase 8; expose them only behind deployment
  access controls.
