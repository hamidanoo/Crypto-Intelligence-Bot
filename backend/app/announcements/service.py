"""Announcement collection service: fetch, deduplicate, persist.

Deduplication is by (source_id, external_id) and by
canonical_url, never by title alone. A run is recorded before
fetching, so a failed run is visible, and the run counts are
updated on completion. Database work is committed once per
run, not once per announcement, so a partially failed run
does not leave a half-written batch.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.announcements.client import AnnouncementAPIError, BinanceAnnouncementClient
from app.config import settings
from app.models import Announcement, AnnouncementSource, CollectionRun

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_NAME = "Binance Announcements"
DEFAULT_SOURCE_TYPE = "binance_website_cms"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def notification_categories_enabled() -> set[str] | None:
    raw = (settings.announcement_notification_categories or "").strip()
    if not raw:
        return None
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def ensure_default_source(db: Session) -> AnnouncementSource:
    source = db.query(AnnouncementSource).filter_by(name=DEFAULT_SOURCE_NAME).first()
    if source is not None:
        return source
    source = AnnouncementSource(
        name=DEFAULT_SOURCE_NAME,
        source_type=DEFAULT_SOURCE_TYPE,
        base_url=settings.binance_announcements_base_url,
        enabled=True,
        polling_interval_seconds=settings.announcement_polling_interval_seconds,
        configuration={
            "endpoint": settings.binance_announcements_endpoint,
            "type": 1,
            "page_size": 20,
        },
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    logger.info("Created default announcement source %s", DEFAULT_SOURCE_NAME)
    return source


async def collect_from_source_async(
    db: Session, source: AnnouncementSource, client: BinanceAnnouncementClient
) -> tuple[CollectionRun, list[Announcement]]:
    run = CollectionRun(source_id=source.id, started_at=_now_utc(), status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    page_size = 20
    if isinstance(source.configuration, dict):
        page_size = int(source.configuration.get("page_size", 20))
    enabled_categories = notification_categories_enabled()
    try:
        normalised = await client.fetch_announcements(page_size=page_size)
    except AnnouncementAPIError as exc:
        run.status = "failed"
        run.completed_at = _now_utc()
        run.error_message = str(exc)
        source.last_error_at = _now_utc()
        source.last_error_message = str(exc)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - collection failures must be recorded, not hidden
        run.status = "failed"
        run.completed_at = _now_utc()
        run.error_message = f"{type(exc).__name__}: {exc}"
        source.last_error_at = _now_utc()
        source.last_error_message = run.error_message
        db.commit()
        raise AnnouncementAPIError(run.error_message) from exc

    created: list[Announcement] = []
    found = len(normalised)
    skipped = 0
    for item in normalised:
        existing = (
            db.query(Announcement)
            .filter(
                (Announcement.source_id == source.id)
                & (Announcement.external_id == item["external_id"])
            )
            .first()
        )
        if existing is None:
            existing = (
                db.query(Announcement)
                .filter(Announcement.canonical_url == item["canonical_url"])
                .first()
            )
        if existing is not None:
            skipped += 1
            # Update in place if the source changed the title
            # or category, without creating a duplicate.
            if existing.content_hash != item["content_hash"]:
                existing.title = item["title"]
                existing.slug = item["slug"]
                existing.category = item["category"]
                existing.category_confidence = item["category_confidence"]
                existing.content_hash = item["content_hash"]
                existing.published_at = item["published_at"]
                existing.metadata_json = item["metadata"]
            continue
        notification_status = "pending"
        if enabled_categories is not None and item["category"] not in enabled_categories:
            notification_status = "disabled"
        announcement = Announcement(
            source_id=source.id,
            source_name=source.name,
            external_id=item["external_id"],
            code=item["code"],
            title=item["title"],
            slug=item["slug"],
            canonical_url=item["canonical_url"],
            category=item["category"],
            category_confidence=item["category_confidence"],
            summary=None,
            original_content=None,
            published_at=item["published_at"],
            collected_at=_now_utc(),
            content_hash=item["content_hash"],
            verification_status="official_website",
            metadata_json=item["metadata"],
            notification_status=notification_status,
        )
        db.add(announcement)
        created.append(announcement)

    run.status = "success"
    run.completed_at = _now_utc()
    run.announcements_found = found
    run.announcements_created = len(created)
    run.duplicates_skipped = skipped
    source.last_success_at = _now_utc()
    source.last_error_message = None
    db.commit()
    for announcement in created:
        db.refresh(announcement)
    db.refresh(run)
    return run, created
