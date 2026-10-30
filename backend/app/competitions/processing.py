"""Announcement-to-competition processing for Phase 5.

Reads announcements the Phase 3 collector already stored
(category TRADING_COMPETITION); it never re-fetches the
CMS feed itself. Dedupe is by announcement_id, enforced
by a unique constraint as well. A second run over the
same announcements only skips them.

Lifecycle changes are not silently overwritten. When a
later announcement carries the same normalised
competition name and a lifecycle signal (cancelled,
postponed, ended) or a newly stated reward pool or pair
list, the existing competition is updated and a
CompetitionUpdate row records the old and new values.
Otherwise a new announcement creates a new competition.

No volume work lives here: Phase 6 owns volume tracking,
and this module stores no volume fields at all.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.competitions.parsing import (
    normalize_for_matching,
    parse_competition,
    recompute_status,
    title_signals_change,
)
from app.models import (
    Announcement,
    Competition,
    CompetitionCollectionRun,
    CompetitionReward,
    CompetitionTradingPair,
    CompetitionUpdate,
)

logger = logging.getLogger(__name__)

_TERMINAL = ("CANCELLED", "POSTPONED")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _record_update(
    db: Session,
    competition: Competition,
    update_type: str,
    field: str | None,
    old,
    new,
    note: str | None = None,
) -> None:
    db.add(
        CompetitionUpdate(
            competition_id=competition.id,
            update_type=update_type,
            field_name=field,
            old_value={"value": old} if old is not None else None,
            new_value={"value": new} if new is not None else None,
            note=note,
        )
    )


def _apply_pairs(db: Session, competition: Competition, pairs: list[str]) -> None:
    existing = {row.pair for row in competition_pairs(db, competition.id)}
    for pair in pairs:
        if pair in existing:
            continue
        quote = next(
            (q for q in ("USDT", "USDC", "BUSD", "FDUSD", "USDP", "TUSD") if pair.endswith(q)),
            None,
        )
        base = pair[: -len(quote)] if quote and len(pair) > len(quote) else None
        db.add(
            CompetitionTradingPair(
                competition_id=competition.id, pair=pair, base_asset=base, quote_asset=quote
            )
        )


def competition_pairs(db: Session, competition_id: int) -> list[CompetitionTradingPair]:
    return (
        db.query(CompetitionTradingPair)
        .filter_by(competition_id=competition_id)
        .order_by(CompetitionTradingPair.id.asc())
        .all()
    )


def _find_by_name(
    db: Session, normalized: str, *, allow_prefix: bool = False
) -> Competition | None:
    if not normalized:
        return None
    for candidate in db.query(Competition).all():
        meta = candidate.metadata_json or {}
        stored = meta.get("normalized_name") or normalize_for_matching(candidate.competition_name)
        if stored == normalized:
            return candidate
        # Prefix matching is only for lifecycle announcements
        # ("Competition X has been cancelled"), never for
        # plain new competitions: two distinct competitions
        # must not be merged just because one name is a
        # prefix of the other.
        if (
            allow_prefix
            and stored
            and normalized
            and (stored.startswith(normalized) or normalized.startswith(stored))
        ):
            return candidate
    return None


def process_competitions(db: Session) -> dict:
    found = created = updated = skipped = errors = 0
    # Alpha trading competitions are classified ALPHA by
    # the Phase 3 classifier (its "binance alpha" rule
    # runs before its "competition" rule), but they are
    # still trading competitions, so they are discovered
    # here too. They keep their Phase 4 Alpha token
    # record as well; the two tables are independent and
    # share only the announcement link.
    announcements = (
        db.query(Announcement)
        .filter(
            or_(
                Announcement.category == "TRADING_COMPETITION",
                (Announcement.category == "ALPHA") & (Announcement.title.ilike("%competition%")),
            )
        )
        .order_by(Announcement.id.asc())
        .all()
    )
    found = len(announcements)
    for announcement in announcements:
        try:
            if db.query(Competition).filter_by(announcement_id=announcement.id).first():
                skipped += 1
                continue
            parsed = parse_competition(announcement.title)
            existing = _find_by_name(
                db,
                parsed["normalized_name"],
                allow_prefix=title_signals_change(announcement.title) is not None,
            )
            if existing is not None:
                changed = False
                signal = title_signals_change(announcement.title)
                if signal and existing.status != signal:
                    _record_update(
                        db,
                        existing,
                        "status_change",
                        "status",
                        existing.status,
                        signal,
                        note=f"Lifecycle signal in announcement {announcement.id}",
                    )
                    existing.status = signal
                    changed = True
                if (
                    parsed["reward_pool"] is not None
                    and existing.reward_pool != parsed["reward_pool"]
                ):
                    _record_update(
                        db,
                        existing,
                        "reward_change",
                        "reward_pool",
                        str(existing.reward_pool) if existing.reward_pool is not None else None,
                        str(parsed["reward_pool"]),
                    )
                    existing.reward_pool = parsed["reward_pool"]
                    existing.reward_currency = parsed["reward_currency"]
                    changed = True
                new_pairs = [
                    p
                    for p in parsed["eligible_trading_pairs"]
                    if p not in (existing.eligible_trading_pairs or [])
                ]
                if new_pairs:
                    _record_update(
                        db,
                        existing,
                        "pairs_change",
                        "eligible_trading_pairs",
                        existing.eligible_trading_pairs,
                        parsed["eligible_trading_pairs"],
                    )
                    existing.eligible_trading_pairs = parsed["eligible_trading_pairs"]
                    existing.eligible_assets = parsed["eligible_assets"]
                    _apply_pairs(db, existing, new_pairs)
                    changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
                continue
            competition = Competition(
                announcement_id=announcement.id,
                competition_name=parsed["competition_name"] or announcement.title,
                description=announcement.title,
                competition_type=parsed["competition_type"],
                official_url=announcement.canonical_url,
                reward_pool=parsed["reward_pool"],
                reward_currency=parsed["reward_currency"],
                start_time=parsed["start_time"],
                end_time=parsed["end_time"],
                status=parsed["status"],
                eligible_trading_pairs=parsed["eligible_trading_pairs"],
                eligible_assets=parsed["eligible_assets"],
                competition_rules=[],
                eligibility_requirements=[],
                multiplier_rules=[],
                source="binance_website_cms",
                verification_status=parsed["verification_status"],
                metadata_json={
                    "normalized_name": parsed["normalized_name"],
                    "category_confidence": announcement.category_confidence,
                    "catalog": (announcement.metadata_json or {}).get("catalog_name"),
                },
            )
            db.add(competition)
            db.flush()
            _apply_pairs(db, competition, parsed["eligible_trading_pairs"])
            if parsed["reward_pool"] is not None:
                db.add(
                    CompetitionReward(
                        competition_id=competition.id,
                        reward_amount=parsed["reward_pool"],
                        reward_currency=parsed["reward_currency"],
                        description="Reward pool stated in the announcement title",
                    )
                )
            db.add(
                CompetitionUpdate(
                    competition_id=competition.id,
                    update_type="created",
                    field_name=None,
                    old_value=None,
                    new_value={"status": parsed["status"]},
                    note="Created from announcement",
                )
            )
            created += 1
        except Exception as exc:  # noqa: BLE001 - one bad announcement must not stop the run
            logger.warning(
                "Competition processing failed for announcement %s: %s", announcement.id, exc
            )
            db.rollback()
            errors += 1
    db.commit()
    return {
        "found": found,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def update_competition_statuses(db: Session, now: datetime | None = None) -> dict:
    """Recompute date-based statuses for competitions
    with dates. Terminal statuses are never overwritten,
    and every change is recorded as a CompetitionUpdate."""
    moment = now or _now_utc()
    changed = 0
    for competition in db.query(Competition).all():
        new_status = recompute_status(competition, moment)
        if new_status != competition.status:
            _record_update(
                db,
                competition,
                "status_change",
                "status",
                competition.status,
                new_status,
                note="Date-based lifecycle recomputation",
            )
            competition.status = new_status
            changed += 1
    db.commit()
    return {"status_updates": changed}


def run_competition_collection(db: Session, source_id: int | None = None) -> dict:
    """One recorded collection run: process stored
    announcements, then recompute date-based statuses.
    A failure is recorded on the run, not hidden."""
    run = CompetitionCollectionRun(source_id=source_id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        summary = process_competitions(db)
        status_summary = update_competition_statuses(db)
    except Exception as exc:  # noqa: BLE001 - the run row must still be closed
        db.rollback()
        run.status = "failed"
        run.error_message = str(exc)
        run.completed = _now_utc()
        db.commit()
        return {
            "found": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 1,
            "error": str(exc),
        }
    run.found = summary["found"]
    run.created = summary["created"]
    run.updated = summary["updated"]
    run.skipped = summary["skipped"]
    run.status = "completed_with_errors" if summary["errors"] else "completed"
    run.error_message = (
        f"{summary['errors']} announcement(s) failed during processing"
        if summary["errors"]
        else None
    )
    run.completed = _now_utc()
    db.commit()
    return {**summary, "status_updates": status_summary["status_updates"]}
