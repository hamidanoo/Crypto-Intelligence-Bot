import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.admin import router as admin_router
from app.api.admin_ops import router as admin_ops_router
from app.api.announcements import router as announcements_router
from app.api.auth import router as auth_router
from app.api.competitions import router as competitions_router
from app.api.volume import router as volume_router
from app.api.binance import router as binance_router
from app.api.futures import router as futures_router
from app.api.health import router as health_router
from app.api.intelligence import router as intelligence_router
from app.api.market import router as market_router
from app.api.news import router as news_router
from app.config import settings
from app.logging_config import configure_logging
from app.scheduler import shutdown_scheduler, start_scheduler


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Response security headers for every API response.

    These are defence in depth: authorisation is enforced
    at the API layer, not by headers, CORS, or Nginx.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        if settings.environment == "production":
            # Only meaningful (and only safe to promise) when
            # the API is served over HTTPS, which production
            # deployment requires; see docs/VPS_DEPLOYMENT.md.
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Crypto Intelligence API starting in %s environment", settings.environment)
    start_scheduler()
    yield
    shutdown_scheduler()
    # Allow the scheduled APScheduler shutdown to execute.
    await asyncio.sleep(0.1)
    logger.info("Crypto Intelligence API shutting down")


# In production the interactive API docs are disabled: they
# disclose every route and permission shape to unauthenticated
# visitors. In development they remain available.
_is_production = settings.environment == "production"
app = FastAPI(
    title="Crypto Intelligence API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # X-CSRF-Token is required by require_csrf on every
    # state-changing authenticated request; omitting it
    # from allow_headers broke direct cross-origin admin
    # calls at preflight (Phase 9 audit).
    allow_headers=["Authorization", "Content-Type", "Accept", "X-CSRF-Token"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_ops_router)
app.include_router(binance_router)
app.include_router(announcements_router)
app.include_router(competitions_router)
app.include_router(intelligence_router)
app.include_router(volume_router)
app.include_router(market_router)
app.include_router(futures_router)
app.include_router(news_router)
