"""Telegram notification foundation for announcements.

Only announcements whose notification_status is not "sent"
are sent, and a successful send immediately marks the record
as sent with a timestamp, so a restart or a second collection
run cannot send the same announcement twice. Failed sends
are recorded with their error and attempt count, and are
retried by the next notification pass (up to 3 attempts in
total for a single announcement in this phase; after that
the record stays "failed" for manual review, rather than
retrying forever).

Message format is HTML, with the title escaped, so special
characters in titles cannot break Telegram parsing. Live
delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_GROUP_ID;
without them, sending is skipped (not marked sent) and the
limitation is logged, so tests can use a mock sender and
live delivery remains honestly unverified.
"""

import html
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Announcement

logger = logging.getLogger(__name__)
MAX_NOTIFICATION_ATTEMPTS = 3


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_announcement_message(announcement: Announcement) -> str:
    published = announcement.published_at.isoformat() if announcement.published_at else "Unknown"
    title = html.escape(announcement.title)
    url = html.escape(announcement.canonical_url)
    return (
        f"📢 <b>{html.escape(announcement.category)}</b>\n\n"
        f"{title}\n\n"
        f"Published: {published} UTC\n"
        f"Source: {html.escape(announcement.source_name)}\n"
        f'<a href="{url}">Read announcement</a>'
    )


async def send_telegram_message(chat_id: str, text: str, *, bot=None) -> None:
    """Send one message. ``bot`` is an injectable sender for
    tests (an object with an async send_message method, or a
    plain callable). When no bot is supplied, a real aiogram
    Bot is created from the configured token."""
    if bot is not None:
        if hasattr(bot, "send_message"):
            await bot.send_message(chat_id, text, parse_mode="HTML")
        else:
            await bot(chat_id, text)
        return
    if not settings.telegram_bot_token or not settings.telegram_group_id:
        raise RuntimeError("Telegram bot token or group id is not configured")
    from aiogram import Bot

    telegram_bot = Bot(token=settings.telegram_bot_token)
    try:
        await telegram_bot.send_message(chat_id, text, parse_mode="HTML")
    finally:
        await telegram_bot.session.close()


async def notify_announcement(db: Session, announcement: Announcement, *, bot=None) -> bool:
    """Notify about one announcement. Returns True on success.
    Does nothing (and returns False) if the announcement was
    already sent, was disabled by category configuration, or
    has exhausted its attempts."""
    if announcement.notification_status == "sent":
        return False
    if announcement.notification_status == "disabled":
        return False
    if announcement.notification_attempts >= MAX_NOTIFICATION_ATTEMPTS:
        return False
    chat_id = settings.telegram_group_id
    if bot is None and (not settings.telegram_bot_token or not chat_id):
        logger.warning(
            "Telegram not configured; announcement %s left as %s, not marked sent",
            announcement.id,
            announcement.notification_status,
        )
        return False
    announcement.notification_attempts += 1
    try:
        await send_telegram_message(chat_id, format_announcement_message(announcement), bot=bot)
    except Exception as exc:  # noqa: BLE001 - delivery failures must be recorded, not crash the run
        announcement.notification_status = "failed"
        announcement.last_notification_error = f"{type(exc).__name__}: {exc}"
        db.commit()
        logger.warning("Telegram notification failed for announcement %s: %s", announcement.id, exc)
        return False
    announcement.notification_status = "sent"
    announcement.notified_at = _now_utc()
    announcement.last_notification_error = None
    db.commit()
    return True


async def notify_pending_announcements(db: Session, *, bot=None) -> int:
    """Send all pending or failed (within attempt limit)
    announcements, oldest first. Returns the number sent."""
    pending = (
        db.query(Announcement)
        .filter(Announcement.notification_status.in_(["pending", "failed"]))
        .filter(Announcement.notification_attempts < MAX_NOTIFICATION_ATTEMPTS)
        .order_by(Announcement.published_at.asc().nulls_last(), Announcement.id.asc())
        .all()
    )
    sent = 0
    for announcement in pending:
        if await notify_announcement(db, announcement, bot=bot):
            sent += 1
    return sent
