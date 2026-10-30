"""Client-IP resolution with explicit trusted-proxy support.

By default no forwarded header is trusted: the direct remote
address is used for rate limits and audit records. Only when
the direct remote address belongs to a network listed in
TRUSTED_PROXIES is the first entry of X-Forwarded-For used,
and only if that entry parses as an IP address. Any other
case falls back to the direct address, so a public client
can never spoof its IP by sending its own forwarded header.
"""

import ipaddress


def resolve_client_ip(request, trusted_networks) -> str | None:
    direct = request.client.host if getattr(request, "client", None) else None
    if direct is None:
        return None
    if not trusted_networks:
        return direct
    try:
        direct_ip = ipaddress.ip_address(direct)
    except ValueError:
        # Test clients and non-IP hosts are never trusted.
        return direct
    if not any(direct_ip in network for network in trusted_networks):
        return direct
    forwarded = None
    headers = getattr(request, "headers", None)
    if headers is not None:
        forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if not forwarded:
        return direct
    first = forwarded.split(",")[0].strip()
    try:
        ipaddress.ip_address(first)
    except ValueError:
        return direct
    return first
