"""Title parsing for Alpha, airdrop, and Prime Sale announcements.

Only information actually present in an announcement title is
extracted. Anything else is None, an empty list, or UNKNOWN:
a missing field is never filled with a guess, a zero, or a
default campaign rule. Announcement bodies are not fetched
in this phase, so title parsing is deliberately conservative
and its limits are documented, not hidden.
"""

import re

_SYMBOL_RE = re.compile(r"\(([A-Z0-9]{2,20})\)")
_CONTRACT_RE = re.compile(r"0x[0-9a-fA-F]{40}\b")

_PREFIXES = [
    "binance alpha adds",
    "binance alpha lists",
    "binance alpha",
    "binance prime sale",
    "binance will list",
    "binance will launch",
    "binance lists",
    "binance launches",
    "binance airdrop:",
    "binance airdrop",
    "binance ",
]

_SUFFIX_PHRASES = [
    " with seed tag applied",
    " with seed tag",
]

_NETWORKS = [
    ("bnb chain", "BNB Chain"),
    ("bnb smart chain", "BNB Chain"),
    ("bsc", "BNB Chain"),
    ("ethereum", "Ethereum"),
    ("solana", "Solana"),
    ("arbitrum", "Arbitrum"),
    ("base", "Base"),
    ("polygon", "Polygon"),
]

# Title hints that are recognisable enough to record as an
# eligibility record. A hint is not a full condition, so
# every record created from a title has
# is_confirmed_details=False.
_ELIGIBILITY_PATTERNS = [
    (
        "alpha points",
        "alpha_points",
        "Binance Alpha points requirement mentioned in the announcement",
    ),
    ("holding", "holding", "Holding requirement mentioned in the announcement"),
    ("hold ", "holding", "Holding requirement mentioned in the announcement"),
    ("participat", "participation", "Participation condition mentioned in the announcement"),
    ("stak", "staking", "Staking condition mentioned in the announcement"),
]


def _strip_prefixes(text: str) -> str:
    lowered = text.strip().lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix):
            return text.strip()[len(prefix) :].strip()
    return text.strip()


def _clean_name(text: str) -> str:
    cleaned = _strip_prefixes(text)
    lowered = cleaned.lower()
    for suffix in _SUFFIX_PHRASES:
        if lowered.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            lowered = cleaned.lower()
    # "Trading Competition: Trade Axis Robotics (AXIS)" is a
    # campaign about one token, not a token called
    # "Trading Competition".
    if lowered.startswith("trading competition:"):
        cleaned = cleaned[len("trading competition:") :].strip()
        lowered = cleaned.lower()
    if lowered.startswith("trade "):
        cleaned = cleaned[len("trade ") :].strip()
    return cleaned.strip(" -:").strip()


def parse_token(title: str) -> dict:
    """Return token name, symbol, contract, and network from a title.

    The symbol is the first parenthesised uppercase group, for
    example (TEST). The name is the text before that group,
    with announcement prefixes stripped. A title without a
    parenthesised symbol yields a name and a None symbol.
    """
    raw = (title or "").strip()
    lowered = raw.lower()
    # A removal announcement lists many tokens, not one:
    # recording the whole list as a single token name would
    # be false data. Callers record it as a multi-token
    # removal announcement instead, with no symbol.
    if "will remove" in lowered or "to be removed" in lowered:
        return {
            "token_name": None,
            "token_symbol": None,
            "contract_address": None,
            "blockchain_network": parse_network(raw),
            "is_multi_token": True,
        }
    match = _SYMBOL_RE.search(raw)
    symbol = match.group(1) if match else None
    if match:
        name = _clean_name(raw[: match.start()])
    else:
        name = _clean_name(raw)
    # Remove a trailing "with ..." clause case-insensitively.
    name = re.split(r"\s+with\s+", name, flags=re.IGNORECASE)[0].strip(" -:").strip()
    contract_match = _CONTRACT_RE.search(raw)
    contract = contract_match.group(0) if contract_match else None
    network = parse_network(raw)
    return {
        "token_name": name or None,
        "token_symbol": symbol,
        "contract_address": contract,
        "blockchain_network": network,
        "is_multi_token": False,
    }


def parse_network(title: str) -> str | None:
    lowered = (title or "").lower()
    for keyword, name in _NETWORKS:
        if keyword == "base":
            if re.search(r"\bbase\b", lowered):
                return name
        elif keyword in lowered:
            return name
    return None


def parse_supported_networks(title: str) -> list[str]:
    network = parse_network(title)
    return [network] if network else []


def airdrop_status(title: str) -> str:
    """Conservative status: only the listed phrases set a
    status; anything else is UNKNOWN, never inferred."""
    text = (title or "").lower()
    if "cancel" in text:
        return "CANCELLED"
    if "claim" in text and "open" in text:
        return "CLAIMING"
    if "claim now" in text:
        return "CLAIMING"
    if "ended" in text or "closed" in text:
        return "ENDED"
    if "now live" in text or "is live" in text or "now open" in text or " is open" in text:
        return "ACTIVE"
    if "coming soon" in text or "will begin" in text or "upcoming" in text:
        return "UPCOMING"
    return "UNKNOWN"


def prime_sale_status(title: str) -> str:
    """Conservative status, same rule as airdrops: only the
    listed phrases set a status; anything else is UNKNOWN."""
    text = (title or "").lower()
    if "cancel" in text:
        return "CANCELLED"
    if "distribution" in text and ("complet" in text or "done" in text):
        return "DISTRIBUTION_COMPLETED"
    if "subscription" in text and ("closed" in text or "ended" in text):
        return "ENDED"
    if "ended" in text or "closed" in text:
        return "ENDED"
    if "subscription" in text and ("open" in text or "live" in text or "now" in text):
        return "ACTIVE"
    if "now live" in text or "is live" in text or "now open" in text:
        return "ACTIVE"
    if "coming soon" in text or "will begin" in text or "upcoming" in text:
        return "UPCOMING"
    return "UNKNOWN"


def extract_eligibility(title: str) -> list[dict]:
    """Eligibility hints actually present in the title, or [].

    Each hint records the announcement title as its source
    text. No hint means no eligibility records are created,
    and callers must then report eligibility as unconfirmed.
    """
    text = (title or "").lower()
    found: list[dict] = []
    seen: set[str] = set()
    for keyword, requirement_type, description in _ELIGIBILITY_PATTERNS:
        if keyword in text and requirement_type not in seen:
            seen.add(requirement_type)
            found.append(
                {
                    "requirement_type": requirement_type,
                    "description": description,
                    "source_text": title,
                    "is_confirmed_details": False,
                }
            )
    return found
