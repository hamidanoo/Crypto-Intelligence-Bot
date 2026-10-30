"""SSRF protection for RSS feed URLs.

Only http/https URLs are allowed. The hostname is
resolved and EVERY resolved address is checked against
loopback, private, link-local, reserved, multicast, and
unspecified ranges before connecting, and the same check
is repeated for every redirect target (at most three
redirects). The response body is capped so a feed cannot
exhaust memory. Redirects are followed manually rather
than by the HTTP client, so a redirect into a prohibited
range cannot slip past the initial check.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

MAX_REDIRECTS = 3
MAX_BODY_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 10.0


class SSRFBlockedError(Exception):
    """Raised when a URL or a resolved address is prohibited."""


def _is_prohibited(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_host(hostname: str) -> None:
    """Resolve a hostname and reject it if any address is prohibited."""
    if not hostname:
        raise SSRFBlockedError("URL has no hostname")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception as exc:
        raise SSRFBlockedError(f"Hostname could not be resolved: {hostname}") from exc
    if not infos:
        raise SSRFBlockedError(f"Hostname could not be resolved: {hostname}")
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_prohibited(ip):
            raise SSRFBlockedError(f"Hostname resolves to a prohibited address: {hostname}")


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError("Only http and https feed URLs are allowed")
    validate_host(parsed.hostname or "")
    return url


def fetch_feed(url: str) -> dict:
    """Fetch a feed URL with SSRF checks at every hop.

    Returns {"status": int, "text": str, "final_url": str}.
    Raises SSRFBlockedError for prohibited URLs and
    httpx.HTTPError for transport failures.
    """
    current = validate_url(url)
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        for hop in range(MAX_REDIRECTS + 1):
            response = client.get(
                current,
                headers={"User-Agent": "Crypto-Intelligence/1.0 (RSS feed check)"},
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location or hop == MAX_REDIRECTS:
                    raise SSRFBlockedError("Too many redirects or missing redirect target")
                current = validate_url(urljoin(current, location))
                continue
            body = response.read()
            if len(body) > MAX_BODY_BYTES:
                body = body[:MAX_BODY_BYTES]
            return {
                "status": response.status_code,
                "text": body.decode("utf-8", errors="replace"),
                "final_url": current,
            }
    raise SSRFBlockedError("Too many redirects")
