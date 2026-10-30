# Binance Airdrop Intelligence (Phase 4)

## Source

The primary discovery source is the Phase 3 Binance
announcement source: the official Binance website CMS
feed (type=1). That feed is the website's own feed,
not a documented public API. No third-party source is
used for airdrop data in this phase.

## How it works

Announcements classified as AIRDROP are processed
into `airdrop_campaigns`, one record per
announcement, deduplicated by `announcement_id`.
A second run skips already-processed announcements.

## Status rules (conservative)

A status is set only when the title contains the
listed phrase; otherwise the status is UNKNOWN,
never inferred:

- CANCELLED: "cancel" in the title.
- CLAIMING: "claim" and "open" in the title, or
  "claim now".
- ENDED: "ended" or "closed".
- ACTIVE: "now live", "is live", "now open", or
  "is open".
- UPCOMING: "coming soon", "will begin", or
  "upcoming".

Live feed note: the 21 airdrop announcements in the
current first page are mostly distribution-completion
notices, and all classify as UNKNOWN under these
rules, because their titles do not contain one of the
phrases above. That is the intended behaviour, not a
gap to be filled with guesses.

## Eligibility

Eligibility records are created only when the title
mentions a recognisable requirement: Alpha points,
holding, participation, or staking. Every such record
has `is_confirmed_details=False`, because a title
hint is not a full condition. When a campaign has no
eligibility records, the API returns
`eligibility_note`:
"Eligibility details not officially confirmed."
No eligibility condition is ever invented.

Dates, claim periods, distribution schedules, and
reward details stay null in this phase, because
announcement bodies are not fetched and titles do
not contain them. Null means "not officially
confirmed from the title", not "no such detail".

## Notifications

Formatters for new airdrops live in
`app/intelligence/notifications.py`, with a source
link when available. `CampaignNotification` prevents
duplicate notifications (one row per entity +
notification type). Claim reminders, deadline
reminders, and distribution updates use the same
mechanism in later work; in this phase the
notification records and formatters are in place,
and live Telegram delivery was not verified (mock
formatting tests only).

## Scheduler

`airdrop_processing` runs every 10 minutes by
default on the same APScheduler instance as every
other job, with `max_instances=1` and
`coalesce=True`. Single-instance limitation applies
(see docs/ALPHA_INTELLIGENCE.md).

## Limitations

- No article bodies, so most detail fields are null.
- No live Telegram delivery, live PostgreSQL, or
  Docker verification yet.
- Manual collection endpoints are not admin-gated
  until Phase 8; expose them only behind deployment
  access controls.
