"""Single-instance rate limiting for Binance routes.

Limits are per client IP, per rolling minute. This is sufficient
for the current single-instance deployment; a distributed limit
would be required only after multi-instance deployment, which is
documented as a later-phase consideration.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

MAX_REQUESTS_PER_MINUTE = 120
_window_seconds = 60
_requests: dict[str, deque] = defaultdict(deque)


def check_rate_limit(request: Request, *, limit: int = MAX_REQUESTS_PER_MINUTE) -> None:
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _requests[client_ip]
    while window and window[0] <= now - _window_seconds:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded for Binance endpoints")
    window.append(now)


def reset_rate_limits() -> None:
    _requests.clear()
