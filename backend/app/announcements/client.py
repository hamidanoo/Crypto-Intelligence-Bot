"""Binance website CMS announcement client.

Source: https://www.binance.com, endpoint
/bapi/composite/v1/public/cms/article/list/query (GET, with
type, pageNo, and pageSize query parameters). This is the
feed the official Binance announcement pages use, but it is
NOT a documented public API: Binance may change it, block
it, or rate-limit it without notice. That limitation is
documented in docs/ANNOUNCEMENT_MONITOR.md and is the reason
the collector treats every failure as a failed collection
run, never as fabricated data, and never silently ignores it.

No authentication is required. The response groups articles
by catalog (for example 48 New Cryptocurrency Listing, 161
Delisting, 128 Crypto Airdrop), each article carrying an id,
a stable code, a title, and a releaseDate in milliseconds.
"""

import asyncio
import hashlib
import logging
import os
import re
import ssl
from datetime import datetime, timezone

import httpx

from app.announcements.classifier import classify_announcement
from app.config import settings

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_title(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug[:200]


def canonical_url_for(title: str, code: str) -> str:
    slug = slugify_title(title)
    return f"https://www.binance.com/en/support/announcement/{slug}-{code}"


def _utc_from_ms(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000, tz=timezone.utc)


def content_hash_for(title: str, code: str, published_at: datetime | None) -> str:
    payload = f"{title}|{code}|{published_at.isoformat() if published_at else ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AnnouncementAPIError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def normalize_article(
    article: dict, catalog_id: int | None, catalog_name: str | None
) -> dict | None:
    """Normalise one CMS article, or return None if it cannot
    be trusted (missing id, code, title, or publication time).
    Publication time is never invented: an article without a
    valid releaseDate is skipped and logged, not stored with a
    guessed time."""
    external_id = article.get("id")
    code = article.get("code")
    title = (article.get("title") or "").strip()
    release_ms = article.get("releaseDate")
    if external_id is None or not code or not title or release_ms is None:
        logger.warning("Skipping announcement with missing id, code, title, or releaseDate")
        return None
    try:
        published_at = _utc_from_ms(int(release_ms))
    except (TypeError, ValueError):
        logger.warning(
            "Skipping announcement %s with invalid releaseDate %r", external_id, release_ms
        )
        return None
    category, confidence = classify_announcement(title, catalog_id)
    return {
        "external_id": str(external_id),
        "code": str(code),
        "title": title,
        "slug": slugify_title(title),
        "canonical_url": canonical_url_for(title, str(code)),
        "category": category,
        "category_confidence": confidence,
        "published_at": published_at,
        "content_hash": content_hash_for(title, str(code), published_at),
        "metadata": {
            "catalog_id": catalog_id,
            "catalog_name": catalog_name,
            "type": article.get("type"),
        },
    }


class BinanceAnnouncementClient:
    def __init__(
        self,
        base_url: str | None = None,
        endpoint: str | None = None,
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or settings.binance_announcements_base_url).rstrip("/")
        self.endpoint = endpoint or settings.binance_announcements_endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)
        self._transport = transport
        self.proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
        ca_bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        if ca_bundle and os.path.exists(ca_bundle):
            context = ssl.create_default_context(cafile=ca_bundle)
        else:
            context = ssl.create_default_context()
        self._ssl_context = context

    async def fetch_announcements(self, *, page_size: int = 20) -> list[dict]:
        """Fetch and normalise the first page of announcements."""
        page_size = max(1, min(int(page_size), 100))
        data = await self._get_with_retries(
            self.endpoint, {"type": 1, "pageNo": 1, "pageSize": page_size}
        )
        catalogs = data.get("data", {}).get("catalogs", []) if isinstance(data, dict) else []
        normalised: list[dict] = []
        for catalog in catalogs:
            catalog_id = catalog.get("catalogId")
            catalog_name = catalog.get("catalogName")
            for article in catalog.get("articles", []) or []:
                item = normalize_article(article, catalog_id, catalog_name)
                if item is not None:
                    normalised.append(item)
        return normalised

    async def _get_with_retries(self, path: str, params: dict) -> dict:
        last_status: int | None = None
        last_message: str | None = None
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                client_kwargs: dict = {
                    "base_url": self.base_url,
                    "timeout": self.timeout_seconds,
                    "transport": self._transport,
                }
                if self._transport is None:
                    client_kwargs.update(
                        {"proxy": self.proxy, "trust_env": False, "verify": self._ssl_context}
                    )
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.get(
                        path,
                        params=params,
                        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    last_status = response.status_code
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = (
                                float(retry_after) if retry_after else 0.5 * (2 ** (attempt - 1))
                            )
                        except (TypeError, ValueError):
                            delay = 0.5 * (2 ** (attempt - 1))
                        await asyncio.sleep(delay)
                    continue
                if response.status_code >= 400:
                    body = {}
                    try:
                        parsed = response.json()
                        body = parsed if isinstance(parsed, dict) else {}
                    except ValueError:
                        pass
                    raise AnnouncementAPIError(
                        body.get("message")
                        or f"Announcement request failed with status {response.status_code}",
                        status=response.status_code,
                    )
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("code") not in (None, "000000", 0):
                    # Binance CMS returns code "000000" on success;
                    # anything else is an upstream error, not data.
                    if isinstance(payload, dict) and payload.get("code"):
                        detail = payload.get("message") or payload.get("code")
                        raise AnnouncementAPIError(
                            f"Announcement request failed: {detail}",
                            status=response.status_code,
                        )
                return payload
            except AnnouncementAPIError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        if last_status is not None:
            message = last_message or (
                f"Announcement request failed with status {last_status} "
                f"after {self.max_retries} attempts"
            )
            raise AnnouncementAPIError(message, status=last_status)
        raise AnnouncementAPIError(
            f"Announcement request failed after {self.max_retries} attempts: {last_error}"
        )
