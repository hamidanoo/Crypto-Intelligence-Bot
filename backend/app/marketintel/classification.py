"""News category classification and symbol extraction.

Rules are keyword-based on the title, with the Phase 3
announcement category as the primary signal for
listings and delistings. Nothing is inferred beyond
the title: an item that matches no rule is OTHER.
"""

import hashlib
import re

NEWS_CATEGORIES = [
    "MARKET_NEWS",
    "BITCOIN",
    "ETHEREUM",
    "ALTCOINS",
    "REGULATION",
    "EXCHANGE_NEWS",
    "LISTINGS",
    "DELISTINGS",
    "SECURITY",
    "EXPLOITS",
    "HACKS",
    "DEFI",
    "NFT",
    "ETF",
    "MACROECONOMICS",
    "OTHER",
]

_ANNOUNCEMENT_CATEGORY_MAP = {
    "SPOT_LISTING": "LISTINGS",
    "FUTURES_LISTING": "LISTINGS",
    "DELISTING": "DELISTINGS",
    "GENERAL": "EXCHANGE_NEWS",
    "NETWORK_MAINTENANCE": "EXCHANGE_NEWS",
    "DEPOSIT_WITHDRAWAL": "EXCHANGE_NEWS",
    "TOKEN_MIGRATION": "EXCHANGE_NEWS",
    "ALPHA": "ALTCOINS",
    "AIRDROP": "ALTCOINS",
    "PRIME_SALE": "ALTCOINS",
    "TRADING_COMPETITION": "MARKET_NEWS",
    "OTHER": "OTHER",
}

_KEYWORD_CATEGORIES = [
    ("delist", "DELISTINGS"),
    ("will list", "LISTINGS"),
    ("listing", "LISTINGS"),
    ("lists ", "LISTINGS"),
    ("hack", "HACKS"),
    ("exploit", "EXPLOITS"),
    ("security breach", "SECURITY"),
    ("security", "SECURITY"),
    ("regulation", "REGULATION"),
    ("regulatory", "REGULATION"),
    ("sec ", "REGULATION"),
    ("etf", "ETF"),
    ("nft", "NFT"),
    ("defi", "DEFI"),
    ("bitcoin", "BITCOIN"),
    (" btc ", "BITCOIN"),
    ("ethereum", "ETHEREUM"),
    (" eth ", "ETHEREUM"),
    ("inflation", "MACROECONOMICS"),
    ("interest rate", "MACROECONOMICS"),
    ("federal reserve", "MACROECONOMICS"),
    ("fed ", "MACROECONOMICS"),
]

_KNOWN_TICKERS = [
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "LINK",
    "AVAX",
    "LTC",
    "DOT",
    "TRX",
    "NEAR",
    "APT",
    "SUI",
    "PEPE",
    "SHIB",
]

_PAIR_RE = re.compile(r"\b([A-Z]{2,12})(USDT|USDC|FDUSD|BUSD|BTC|ETH)\b")


def classify_news(title: str, announcement_category: str | None = None) -> str:
    """Return a news category for a title.

    Listing/delisting announcement categories win
    over keywords, because a delisting notice may
    mention other keywords; otherwise the first
    keyword rule wins, and anything unmatched is
    OTHER, never a guessed category.
    """
    if announcement_category in ("SPOT_LISTING", "FUTURES_LISTING", "DELISTING"):
        return _ANNOUNCEMENT_CATEGORY_MAP[announcement_category]
    text = f" {(title or '').lower()} "
    for keyword, category in _KEYWORD_CATEGORIES:
        if keyword in text:
            return category
    if announcement_category in _ANNOUNCEMENT_CATEGORY_MAP:
        return _ANNOUNCEMENT_CATEGORY_MAP[announcement_category]
    return "OTHER"


def extract_related_symbols(title: str) -> list[str]:
    """Symbols identifiable from a title, nothing more.

    Trading pairs contribute their base asset, and
    known tickers match as whole words. A title with
    no identifiable symbol returns an empty list,
    never a guessed symbol.
    """
    text = (title or "").upper()
    found: list[str] = []
    for base, _quote in _PAIR_RE.findall(text):
        if base not in found:
            found.append(base)
    # A parenthesised symbol in a listing title, as in
    # "Binance Will List Foo (FOO)", is identifiable
    # even when it is not part of a trading pair.
    for symbol in re.findall(r"\(([A-Z0-9]{2,12})\)", text):
        if symbol not in found:
            found.append(symbol)
    for ticker in _KNOWN_TICKERS:
        if re.search(rf"\b{ticker}\b", text) and ticker not in found:
            found.append(ticker)
    return found


def extract_listing_token(title: str) -> tuple[str | None, str | None]:
    """Token name and symbol from a listing title.

    The symbol is the first parenthesised group, as
    in Phase 4 parsing; the name is the text before
    it with listing prefixes stripped. Returns
    (None, None) when no parenthesised symbol exists,
    rather than inventing one.
    """
    match = re.search(r"\(([^)]+)\)", title or "")
    if not match:
        return None, None
    symbol = match.group(1).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", symbol):
        return None, None
    name = (title or "")[: match.start()].strip()
    for prefix in (
        "Binance Will List",
        "Binance Lists",
        "Binance Alpha Adds",
        "Will List",
        "Lists",
    ):
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix) :].strip()
            break
    name = re.split(r"\s+with\s+", name, flags=re.IGNORECASE)[0].strip()
    return (name or None), symbol


def news_fingerprint(headline: str, original_url: str) -> str:
    """Stable duplicate fingerprint for one source.

    Normalised headline plus canonical URL, hashed.
    Different sources keep different rows even for
    the same story, because their URLs differ; within
    one source, the same URL can never create a
    second news row.
    """
    payload = f"{' '.join((headline or '').lower().split())}|{(original_url or '').strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
