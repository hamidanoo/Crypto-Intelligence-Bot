"""Phase 4 API: Alpha tokens, airdrops, and Prime Sales.

Follows the Phase 3 API conventions: pagination with
page/page_size, filters, sorting, 404 for missing
records, 400 for invalid input, 502 when the upstream
announcement collection fails, and 503 on database
errors. Financial values are serialised as strings, so
Decimal precision survives JSON encoding.

Manual collection endpoints are gated in Phase 8 by
the collections.run permission and CSRF protection.
That limitation is documented in docs/API.md and in the
Phase 4 module docs, not hidden.
"""

import logging
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.announcements.client import AnnouncementAPIError, BinanceAnnouncementClient
from app.announcements.service import collect_from_source_async, ensure_default_source
from app.database import get_db
from app.api.admin_common import audit as _audit_collection
from app.auth.dependencies import require_csrf, require_permission
from app.intelligence.allocation import estimate_allocation
from app.intelligence.processing import (
    process_airdrops,
    process_alpha,
    process_prime_sales,
)
from app.models import (
    AirdropCampaign,
    AirdropEligibility,
    AlphaToken,
    AlphaTokenUpdate,
    PrimeSale,
    PrimeSaleAllocationRule,
)
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intelligence"])

ELIGIBILITY_NOTE = "Eligibility details not officially confirmed."


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _serialise_token(token: AlphaToken) -> dict:
    return {
        "id": token.id,
        "announcement_id": token.announcement_id,
        "token_name": token.token_name,
        "token_symbol": token.token_symbol,
        "contract_address": token.contract_address,
        "blockchain_network": token.blockchain_network,
        "trading_status": token.trading_status,
        "trading_pairs": token.trading_pairs or [],
        "announcement_url": token.announcement_url,
        "announcement_timestamp": _iso(token.announcement_timestamp),
        "token_metadata": token.token_metadata or {},
        "data_source": token.data_source,
        "verification_status": token.verification_status,
        "current_price": _dec(token.current_price),
        "price_change_24h": _dec(token.price_change_24h),
        "volume_24h": _dec(token.volume_24h),
        "market_data_source": token.market_data_source,
        "market_data_updated_at": _iso(token.market_data_updated_at),
        "market_data_status": token.market_data_status,
        "created_at": _iso(token.created_at),
        "updated_at": _iso(token.updated_at),
    }


def _serialise_update(update: AlphaTokenUpdate) -> dict:
    return {
        "id": update.id,
        "token_id": update.token_id,
        "update_type": update.update_type,
        "changes": update.changes or {},
        "created_at": _iso(update.created_at),
    }


def _serialise_airdrop(campaign: AirdropCampaign, eligibility: list[AirdropEligibility]) -> dict:
    return {
        "id": campaign.id,
        "announcement_id": campaign.announcement_id,
        "campaign_name": campaign.campaign_name,
        "token_name": campaign.token_name,
        "token_symbol": campaign.token_symbol,
        "description": campaign.description,
        "eligibility_summary": campaign.eligibility_summary,
        "eligibility_note": None if eligibility else ELIGIBILITY_NOTE,
        "eligibility": [
            {
                "id": item.id,
                "requirement_type": item.requirement_type,
                "description": item.description,
                "source_text": item.source_text,
                "is_confirmed_details": item.is_confirmed_details,
            }
            for item in eligibility
        ],
        "start_date": _iso(campaign.start_date),
        "end_date": _iso(campaign.end_date),
        "claim_period_start": _iso(campaign.claim_period_start),
        "claim_period_end": _iso(campaign.claim_period_end),
        "distribution_schedule": campaign.distribution_schedule,
        "reward_info": campaign.reward_info,
        "supported_networks": campaign.supported_networks or [],
        "official_url": campaign.official_url,
        "status": campaign.status,
        "created_at": _iso(campaign.created_at),
        "updated_at": _iso(campaign.updated_at),
    }


def _serialise_prime(sale: PrimeSale, rule: PrimeSaleAllocationRule | None) -> dict:
    return {
        "id": sale.id,
        "announcement_id": sale.announcement_id,
        "token_name": sale.token_name,
        "token_symbol": sale.token_symbol,
        "sale_description": sale.sale_description,
        "subscription_start": _iso(sale.subscription_start),
        "subscription_end": _iso(sale.subscription_end),
        "distribution_time": _iso(sale.distribution_time),
        "trading_availability": sale.trading_availability,
        "subscription_price": _dec(sale.subscription_price),
        "min_commitment": _dec(sale.min_commitment),
        "max_commitment": _dec(sale.max_commitment),
        "eligible_assets": sale.eligible_assets or [],
        "allocation_methodology": sale.allocation_methodology,
        "reward_info": sale.reward_info,
        "official_url": sale.official_url,
        "status": sale.status,
        "allocation_rule": (
            {
                "id": rule.id,
                "formula_type": rule.formula_type,
                "description": rule.description,
                "total_token_allocation": _dec(rule.total_token_allocation),
                "sale_price": _dec(rule.sale_price),
            }
            if rule
            else None
        ),
        "created_at": _iso(sale.created_at),
        "updated_at": _iso(sale.updated_at),
    }


def _paginate(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


async def _collect_and_process(db: Session, category: str) -> dict:
    """Collect announcements (Phase 3 service), then
    process one category. Raises AnnouncementAPIError on
    collection failure, so callers return 502."""
    source = ensure_default_source(db)
    client = BinanceAnnouncementClient(base_url=source.base_url)
    await collect_from_source_async(db, source, client)
    if category == "ALPHA":
        return await process_alpha(db)
    if category == "AIRDROP":
        return process_airdrops(db)
    return process_prime_sales(db)


def _collect_endpoint(category: str):
    async def handler(request: Request, db: Session = Depends(get_db)):
        check_rate_limit(request)
        try:
            summary = await _collect_and_process(db, category)
        except AnnouncementAPIError as exc:
            return JSONResponse(
                status_code=502, content={"detail": f"Announcement collection failed: {exc}"}
            )
        except SQLAlchemyError as exc:
            logger.warning("Intelligence collection database error: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"category": category, **summary}

    return handler


# Alpha ----------------------------------------------------------------


@router.get("/alpha/tokens")
async def list_alpha_tokens(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    symbol: str | None = None,
    trading_status: str | None = None,
    search: str | None = None,
    sort: str = Query("created_at_desc"),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(AlphaToken)
        if symbol:
            query = query.filter(AlphaToken.token_symbol == symbol.strip().upper())
        if trading_status:
            query = query.filter(AlphaToken.trading_status == trading_status)
        if search:
            query = query.filter(AlphaToken.token_name.ilike(f"%{search}%"))
        if sort == "created_at_asc":
            query = query.order_by(AlphaToken.created_at.asc(), AlphaToken.id.asc())
        elif sort == "token_name_asc":
            query = query.order_by(AlphaToken.token_name.asc(), AlphaToken.id.asc())
        else:
            query = query.order_by(AlphaToken.created_at.desc(), AlphaToken.id.desc())
        total, items = _paginate(query, page, page_size)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialise_token(t) for t in items],
    }


@router.get("/alpha/tokens/{token_id}")
async def get_alpha_token(token_id: int, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        token = db.query(AlphaToken).filter_by(id=token_id).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if token is None:
        raise HTTPException(status_code=404, detail="Alpha token not found")
    return _serialise_token(token)


@router.get("/alpha/updates")
async def list_alpha_updates(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    token_id: int | None = None,
    update_type: str | None = None,
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(AlphaTokenUpdate)
        if token_id is not None:
            query = query.filter(AlphaTokenUpdate.token_id == token_id)
        if update_type:
            query = query.filter(AlphaTokenUpdate.update_type == update_type)
        query = query.order_by(AlphaTokenUpdate.created_at.desc(), AlphaTokenUpdate.id.desc())
        total, items = _paginate(query, page, page_size)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialise_update(u) for u in items],
    }


@router.post("/alpha/collect")
async def collect_alpha(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("collections.run")),
    _csrf=Depends(require_csrf),
):
    _audit_collection(
        db, _admin, "collection.requested", entity="collection", details={"path": request.url.path}
    )
    return await _collect_endpoint("ALPHA")(request, db)


# Airdrops --------------------------------------------------------------


@router.get("/airdrops/active")
async def list_active_airdrops(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = (
            db.query(AirdropCampaign)
            .filter(AirdropCampaign.status.in_(["ACTIVE", "UPCOMING", "CLAIMING"]))
            .order_by(AirdropCampaign.created_at.desc(), AirdropCampaign.id.desc())
        )
        total, items = _paginate(query, page, page_size)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            _serialise_airdrop(
                item,
                db.query(AirdropEligibility).filter_by(campaign_id=item.id).all(),
            )
            for item in items
        ],
    }


@router.get("/airdrops")
async def list_airdrops(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    symbol: str | None = None,
    search: str | None = None,
    sort: str = Query("created_at_desc"),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(AirdropCampaign)
        if status:
            query = query.filter(AirdropCampaign.status == status.upper())
        if symbol:
            query = query.filter(AirdropCampaign.token_symbol == symbol.strip().upper())
        if search:
            query = query.filter(AirdropCampaign.campaign_name.ilike(f"%{search}%"))
        if sort == "created_at_asc":
            query = query.order_by(AirdropCampaign.created_at.asc(), AirdropCampaign.id.asc())
        else:
            query = query.order_by(AirdropCampaign.created_at.desc(), AirdropCampaign.id.desc())
        total, items = _paginate(query, page, page_size)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            _serialise_airdrop(
                item,
                db.query(AirdropEligibility).filter_by(campaign_id=item.id).all(),
            )
            for item in items
        ],
    }


@router.get("/airdrops/{campaign_id}")
async def get_airdrop(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        campaign = db.query(AirdropCampaign).filter_by(id=campaign_id).first()
        eligibility = (
            db.query(AirdropEligibility).filter_by(campaign_id=campaign_id).all()
            if campaign
            else []
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if campaign is None:
        raise HTTPException(status_code=404, detail="Airdrop campaign not found")
    return _serialise_airdrop(campaign, eligibility)


@router.post("/airdrops/collect")
async def collect_airdrops(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("collections.run")),
    _csrf=Depends(require_csrf),
):
    _audit_collection(
        db, _admin, "collection.requested", entity="collection", details={"path": request.url.path}
    )
    return await _collect_endpoint("AIRDROP")(request, db)


# Prime Sales ------------------------------------------------------------


@router.get("/prime-sales/active")
async def list_active_prime_sales(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = (
            db.query(PrimeSale)
            .filter(PrimeSale.status.in_(["ACTIVE", "UPCOMING"]))
            .order_by(PrimeSale.created_at.desc(), PrimeSale.id.desc())
        )
        total, items = _paginate(query, page, page_size)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            _serialise_prime(
                item,
                db.query(PrimeSaleAllocationRule).filter_by(sale_id=item.id).first(),
            )
            for item in items
        ],
    }


@router.get("/prime-sales")
async def list_prime_sales(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    symbol: str | None = None,
    search: str | None = None,
    sort: str = Query("created_at_desc"),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(PrimeSale)
        if status:
            query = query.filter(PrimeSale.status == status.upper())
        if symbol:
            query = query.filter(PrimeSale.token_symbol == symbol.strip().upper())
        if search:
            query = query.filter(PrimeSale.token_name.ilike(f"%{search}%"))
        if sort == "created_at_asc":
            query = query.order_by(PrimeSale.created_at.asc(), PrimeSale.id.asc())
        else:
            query = query.order_by(PrimeSale.created_at.desc(), PrimeSale.id.desc())
        total, items = _paginate(query, page, page_size)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            _serialise_prime(
                item,
                db.query(PrimeSaleAllocationRule).filter_by(sale_id=item.id).first(),
            )
            for item in items
        ],
    }


@router.get("/prime-sales/{sale_id}")
async def get_prime_sale(sale_id: int, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        sale = db.query(PrimeSale).filter_by(id=sale_id).first()
        rule = (
            db.query(PrimeSaleAllocationRule).filter_by(sale_id=sale_id).first() if sale else None
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if sale is None:
        raise HTTPException(status_code=404, detail="Prime Sale not found")
    return _serialise_prime(sale, rule)


@router.post("/prime-sales/collect")
async def collect_prime_sales(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("collections.run")),
    _csrf=Depends(require_csrf),
):
    _audit_collection(
        db, _admin, "collection.requested", entity="collection", details={"path": request.url.path}
    )
    return await _collect_endpoint("PRIME_SALE")(request, db)


class EstimateRequest(BaseModel):
    user_commitment: Decimal = Field(..., gt=0)
    total_commitment: Decimal = Field(..., gt=0)
    total_token_allocation: Decimal = Field(..., gt=0)
    sale_price: Decimal | None = Field(default=None, gt=0)
    formula: str | None = None


@router.post("/prime-sales/estimate-allocation")
async def estimate_allocation_endpoint(
    request: Request, payload: EstimateRequest = Body(...), db: Session = Depends(get_db)
):
    """Estimate a proportional allocation. The result is
    labelled an estimate and is never a guarantee; a
    missing or zero total commitment is rejected, never
    replaced with an invented figure."""
    check_rate_limit(request)
    try:
        result = estimate_allocation(
            payload.user_commitment, payload.total_commitment, payload.total_token_allocation
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "estimated_allocation": str(result["estimated_allocation"]),
        "user_commitment": str(result["user_commitment"]),
        "total_commitment": str(result["total_commitment"]),
        "total_token_allocation": str(result["total_token_allocation"]),
        "sale_price": str(payload.sale_price) if payload.sale_price is not None else None,
        "formula": payload.formula or result["formula"],
        "is_estimate": True,
        "guarantee": result["guarantee"],
    }
