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


app = FastAPI(title="Crypto Intelligence API", version="0.1.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
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
