"""Announcement category classification.

Title rules run first, because a catalog alone is not reliable:
for example, a Futures launch can appear in the "New
Cryptocurrency Listing" catalog. Catalog metadata is used as a
fallback, and anything that does not match a rule is OTHER
with low confidence, never a confirmed category it does not
match. The classifier is deliberately extensible: add a rule
here, and later phases can reuse the same categories.
"""

CATEGORIES = [
    "GENERAL",
    "ALPHA",
    "AIRDROP",
    "PRIME_SALE",
    "TRADING_COMPETITION",
    "SPOT_LISTING",
    "FUTURES_LISTING",
    "DELISTING",
    "DEPOSIT_WITHDRAWAL",
    "NETWORK_MAINTENANCE",
    "TOKEN_MIGRATION",
    "OTHER",
]

# Binance CMS catalog ids observed in the live feed, used only
# as a fallback after title rules.
_CATALOG_CATEGORIES = {
    48: "SPOT_LISTING",
    49: "GENERAL",
    51: "OTHER",
    93: "OTHER",
    128: "AIRDROP",
    157: "NETWORK_MAINTENANCE",
    161: "DELISTING",
}


def classify_announcement(title: str, catalog_id: int | None = None) -> tuple[str, str]:
    """Return (category, confidence) for an announcement title.

    Confidence is "high" for an explicit title match, "medium"
    for a catalog fallback, and "low" when no rule matches.
    """
    text = (title or "").lower()

    if "delist" in text:
        return "DELISTING", "high"
    if "airdrop" in text:
        return "AIRDROP", "high"
    if "binance alpha" in text or text.startswith("alpha"):
        return "ALPHA", "high"
    if "prime sale" in text:
        return "PRIME_SALE", "high"
    if "trading competition" in text or "competition" in text:
        return "TRADING_COMPETITION", "high"
    if "futures will launch" in text or "perpetual contract" in text:
        return "FUTURES_LISTING", "high"
    if "token migration" in text or "token swap" in text:
        return "TOKEN_MIGRATION", "high"
    if "deposit" in text or "withdrawal" in text:
        return "DEPOSIT_WITHDRAWAL", "high"
    if "maintenance" in text or "network upgrade" in text or "wallet maintenance" in text:
        return "NETWORK_MAINTENANCE", "high"
    if "will list" in text or "listing" in text or "will launch" in text:
        # A plain "will launch" without "futures" above is a Spot
        # listing in practice, but keep confidence medium: the
        # title alone does not prove Spot vs Futures.
        if "futures" in text:
            return "FUTURES_LISTING", "high"
        return "SPOT_LISTING", "medium"

    if catalog_id is not None and catalog_id in _CATALOG_CATEGORIES:
        return _CATALOG_CATEGORIES[catalog_id], "medium"
    return "OTHER", "low"
