"""Conservative parsing of competition announcements.

Only information actually present in an announcement title
is extracted. Article bodies are not available in this
phase (the CMS article-detail endpoint still returns code
000002 "illegal parameter", re-checked 2026-10-30), so
dates, reward pools, and trading pairs are null or empty
unless the title itself states them. A missing field is
never filled with a guess, a zero, or a default rule, and
a status is never inferred from dates that do not exist.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

_PAIR_RE = re.compile(r"\b([A-Z]{2,12})[/\-]?(USDT|USDC|BUSD|FDUSD|USDP|TUSD)\b")
_REWARD_RE = re.compile(r"\$?\s?([\d,]+(?:\.\d+)?)\s*(USDT|USDC|BNB|BTC|ETH|FDUSD|USD)\b")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATE_RANGE_RE = re.compile(r"from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_START_END_RE = re.compile(
    r"starts?\s+(\d{4}-\d{2}-\d{2}).{0,40}?ends?\s+(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE | re.DOTALL,
)

_COMPETITION_KEYWORDS = ("competition", "campaign", "event", "tournament", "challenge")


# Type classification order matters and is documented:
# a team competition is a team event first, even if it is
# also a Futures event; Futures beats Spot for the same
# reason. Nothing beyond the title is consulted.
def classify_competition_type(title: str) -> str:
    text = (title or "").lower()
    if "team" in text:
        return "TEAM"
    if "futures" in text:
        return "FUTURES"
    if "spot" in text:
        return "SPOT"
    if "volume" in text:
        return "VOLUME"
    return "GENERAL"


def clean_competition_name(title: str) -> str:
    """Strip a leading "Binance" prefix; the rest of the
    title is kept verbatim, because shortening it further
    would risk inventing a cleaner name than the official
    one."""
    text = (title or "").strip()
    lowered = text.lower()
    for prefix in ("binance futures ", "binance spot ", "binance "):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


_LIFECYCLE_SUFFIXES = (
    " has been cancelled",
    " has been postponed",
    " has ended",
    " is cancelled",
    " is postponed",
    " cancelled",
    " postponed",
    " ended",
    " completed",
    " concluded",
)


def normalize_for_matching(name: str) -> str:
    """Normalised name with a trailing lifecycle signal
    stripped, so "Competition X has been cancelled" still
    matches the original "Competition X" for change
    detection. The stored competition_name keeps the full
    official title; only matching uses this form."""
    lowered = (name or "").lower().strip()
    for suffix in _LIFECYCLE_SUFFIXES:
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)].strip()
            break
    return normalize_name(lowered)


def extract_trading_pairs(title: str) -> list[str]:
    pairs: list[str] = []
    for base, quote in _PAIR_RE.findall(title or ""):
        pair = f"{base}{quote}"
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def extract_assets(pairs: list[str]) -> list[str]:
    assets: list[str] = []
    for pair in pairs:
        for quote in ("USDT", "USDC", "BUSD", "FDUSD", "USDP", "TUSD"):
            if pair.endswith(quote) and len(pair) > len(quote):
                base = pair[: -len(quote)]
                if base not in assets:
                    assets.append(base)
                break
    return assets


def extract_reward_pool(title: str) -> tuple[Decimal | None, str | None]:
    """Only an explicit amount plus currency, in a title
    that mentions rewards, a prize, or a pool, counts. An
    amount without a currency, or a trading amount in a
    non-reward title, returns (None, None)."""
    text = title or ""
    lowered = text.lower()
    if not any(word in lowered for word in ("reward", "prize", "pool", "prize pool")):
        return None, None
    match = _REWARD_RE.search(text)
    if not match:
        return None, None
    try:
        amount = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None, None
    return amount, match.group(2)


def parse_dates(title: str) -> tuple[datetime | None, datetime | None]:
    """Only an explicit ISO date range counts: "from
    YYYY-MM-DD to YYYY-MM-DD" or "starts YYYY-MM-DD ...
    ends YYYY-MM-DD". Any other date-like text is ignored,
    because its meaning (start, end, registration) cannot
    be verified from the title alone. Times are UTC
    midnight, since titles carry no time of day."""
    text = title or ""
    match = _DATE_RANGE_RE.search(text) or _START_END_RE.search(text)
    if not match:
        return None, None
    try:
        start = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group(2), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None, None
    if end < start:
        return None, None
    return start, end


def status_from_title(title: str) -> str:
    """Title-signal status only. ACTIVE and UPCOMING are
    never assigned here: without verified dates they would
    be guesses, and date-based status is recompute_status's
    job, not the title parser's."""
    text = (title or "").lower()
    if "cancel" in text:
        return "CANCELLED"
    if "postpon" in text:
        return "POSTPONED"
    if "ended" in text or "completed" in text or "concluded" in text:
        return "ENDED"
    return "UNKNOWN"


def title_signals_change(title: str) -> str | None:
    """Return the lifecycle status a later announcement
    signals for an existing competition, or None when the
    title carries no lifecycle signal."""
    status = status_from_title(title)
    return status if status in ("CANCELLED", "POSTPONED", "ENDED") else None


def parse_competition(title: str) -> dict:
    name = clean_competition_name(title)
    pairs = extract_trading_pairs(title)
    reward_pool, reward_currency = extract_reward_pool(title)
    start, end = parse_dates(title)
    lowered = (title or "").lower()
    reliable_name = bool(name) and len(name) >= 5
    has_keyword = any(word in lowered for word in _COMPETITION_KEYWORDS)
    return {
        "competition_name": name,
        "competition_type": classify_competition_type(title),
        "eligible_trading_pairs": pairs,
        "eligible_assets": extract_assets(pairs),
        "reward_pool": reward_pool,
        "reward_currency": reward_currency,
        "start_time": start,
        "end_time": end,
        "status": status_from_title(title),
        "verification_status": (
            "official_website" if reliable_name and has_keyword else "needs_review"
        ),
        "normalized_name": normalize_for_matching(name),
    }


def recompute_status(competition, now: datetime | None = None) -> str:
    """Date-based lifecycle status, UTC internally.

    CANCELLED and POSTPONED are terminal and are never
    overwritten by date logic. Without both dates, a
    previously determined UPCOMING/ACTIVE/ENDED status is
    preserved and UNKNOWN stays UNKNOWN: no transition is
    invented from missing dates. With both dates, now
    before start is UPCOMING, within the window is ACTIVE,
    and after end is ENDED.
    """
    current = competition.status or "UNKNOWN"
    if current in ("CANCELLED", "POSTPONED"):
        return current
    start = getattr(competition, "start_time", None)
    end = getattr(competition, "end_time", None)
    # SQLite returns naive datetimes while PostgreSQL
    # returns aware ones; normalise both to aware UTC
    # before any comparison, or the comparison raises.
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start is None or end is None:
        return current if current in ("UPCOMING", "ACTIVE", "ENDED") else "UNKNOWN"
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if moment < start:
        return "UPCOMING"
    if moment <= end:
        return "ACTIVE"
    return "ENDED"
