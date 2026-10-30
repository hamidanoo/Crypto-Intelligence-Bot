"""Phase 6 competition volume tracker package.

Data source: Binance Spot aggTrades (GET
/api/v3/aggTrades) with exact exchange timestamps.
Trade-level data is used because klines cannot split
a boundary candle, and the rolling-24h-ticker
subtraction method is forbidden: it is not used
anywhere in this package. If aggTrades is unavailable
for a symbol, the interval is marked incomplete and
its volumes stay null; klines volume is never
substituted silently and no value is fabricated.

Accuracy rules enforced throughout this package:
public market volume comes from public trade data;
estimated eligible volume is calculated only from a
verified multiplier configuration, otherwise null;
official eligible volume is always null in Phase 6
(no authoritative Binance source is implemented),
displayed as "Unavailable", never zero. Official
leaderboard data is not implemented and never claimed.
"""

from app.volume.aggregation import bucket_trades, cumulative_volume, estimate_eligible_volume
from app.volume.intervals import (
    INTERVAL_MINUTES,
    completed_intervals_between,
    interval_bounds_for,
    is_partial_interval,
)

__all__ = [
    "INTERVAL_MINUTES",
    "bucket_trades",
    "completed_intervals_between",
    "cumulative_volume",
    "estimate_eligible_volume",
    "interval_bounds_for",
    "is_partial_interval",
]
