"""Telegram message formatters for competitions.

Times stored in UTC are shown in Asia/Karachi time and
labelled PKT, because that is the audience's display
timezone; the stored value is never converted in place.
Reward pools and trading pairs appear only when they
were actually confirmed from the announcement title;
otherwise they are omitted, never shown as zero or as a
guessed list.

Duplicate prevention reuses the Phase 4
CampaignNotification table with entity_type
"competition": one row per (competition, notification
type), so a second run never re-sends the same notice.
That choice is deliberate — a separate table would
duplicate identical logic — and it is documented in
docs/COMPETITION_INTELLIGENCE.md.
"""

import html
from datetime import timezone
from zoneinfo import ZoneInfo

from app.intelligence.notifications import record_notification

PKT = ZoneInfo("Asia/Karachi")

_TITLES = {
    "new_competition": "🏆 <b>New Binance trading competition</b>",
    "starting": "▶️ <b>Competition starting</b>",
    "ending_soon": "⏰ <b>Competition ending soon</b>",
    "postponed": "⏸️ <b>Competition postponed</b>",
    "cancelled": "⛔ <b>Competition cancelled</b>",
    "rule_change": "📋 <b>Competition update</b>",
    "reward_change": "💰 <b>Competition reward update</b>",
}


def format_pkt(value) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(PKT).strftime("%Y-%m-%d %H:%M PKT")


def format_competition_message(competition, notification_type: str = "new_competition") -> str:
    title = _TITLES.get(notification_type, _TITLES["new_competition"])
    lines = [title, "", html.escape(competition.competition_name)]
    lines.append(f"Type: {html.escape(competition.competition_type or 'GENERAL')}")
    lines.append(f"Status: {html.escape(competition.status or 'UNKNOWN')}")
    start = format_pkt(competition.start_time)
    end = format_pkt(competition.end_time)
    if start or end:
        lines.append(f"Start: {start or 'Not officially confirmed'}")
        lines.append(f"End: {end or 'Not officially confirmed'}")
    else:
        lines.append("Dates: Not officially confirmed")
    if competition.reward_pool is not None:
        currency = competition.reward_currency or ""
        lines.append(f"Reward pool: {competition.reward_pool} {currency}".strip())
    pairs = competition.eligible_trading_pairs or []
    if pairs:
        lines.append(f"Pairs: {html.escape(', '.join(pairs))}")
    text = "\n".join(lines)
    if competition.official_url:
        text += f'\n<a href="{html.escape(competition.official_url)}">Read announcement</a>'
    return text


def record_competition_notification(db, competition, notification_type: str) -> bool:
    return record_notification(
        db,
        "competition",
        competition.id,
        notification_type,
        announcement_id=competition.announcement_id,
    )
