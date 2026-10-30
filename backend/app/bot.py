"""Telegram bot connection structure for Phase 1.

This module owns the bot handlers only. No market, announcement, or
competition logic lives here; later phases call the backend services
and publish through the handlers defined in this module's router.
"""

import asyncio
import logging
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command

from app.config import settings

logger = logging.getLogger(__name__)
router = Router()


def _db():
    from app.database import SessionLocal

    return SessionLocal()


def _args(message: types.Message) -> list[str]:
    text = (message.text or "").strip()
    parts = text.split()
    return parts[1:] if len(parts) > 1 else []


async def _reply_alpha(message: types.Message, query: str | None) -> None:
    from app.models import AlphaToken

    db = _db()
    try:
        q = db.query(AlphaToken)
        if query:
            needle = query.strip().upper()
            q = q.filter(
                (AlphaToken.token_symbol == needle)
                | (AlphaToken.token_name.ilike(f"%{query.strip()}%"))
            )
        tokens = q.order_by(AlphaToken.id.desc()).limit(5).all()
    finally:
        db.close()
    if not tokens:
        await message.answer("None recorded yet.")
        return
    lines = []
    for token in tokens:
        symbol = f" ({token.token_symbol})" if token.token_symbol else ""
        price = f" — {token.current_price} USDT" if token.current_price is not None else ""
        lines.append(f"{token.token_name}{symbol}{price}\n{token.announcement_url}")
    await message.answer("\n\n".join(lines))


async def _reply_airdrops(message: types.Message, active_only: bool) -> None:
    from app.models import AirdropCampaign

    db = _db()
    try:
        q = db.query(AirdropCampaign)
        if active_only:
            q = q.filter(AirdropCampaign.status.in_(["ACTIVE", "UPCOMING", "CLAIMING"]))
        campaigns = q.order_by(AirdropCampaign.id.desc()).limit(5).all()
    finally:
        db.close()
    if not campaigns:
        await message.answer("None recorded yet.")
        return
    lines = [f"{c.campaign_name}\nStatus: {c.status}\n{c.official_url}" for c in campaigns]
    await message.answer("\n\n".join(lines))


async def _reply_prime(message: types.Message, active_only: bool) -> None:
    from app.models import PrimeSale

    db = _db()
    try:
        q = db.query(PrimeSale)
        if active_only:
            q = q.filter(PrimeSale.status.in_(["ACTIVE", "UPCOMING"]))
        sales = q.order_by(PrimeSale.id.desc()).limit(5).all()
    finally:
        db.close()
    if not sales:
        await message.answer("None recorded yet.")
        return
    lines = [f"{s.token_name}\nStatus: {s.status}\n{s.official_url}" for s in sales]
    await message.answer("\n\n".join(lines))


@router.message(Command("start"))
async def start_handler(message: types.Message) -> None:
    await message.answer("Crypto Intelligence Bot is online. Use /help to see available commands.")


@router.message(Command("help"))
async def help_handler(message: types.Message) -> None:
    await message.answer(
        "Available commands:\n"
        "/start - Check the bot is online\n"
        "/help - Show this help message\n"
        "/status - Show the bot status\n"
        "/alpha [token] - Latest Alpha tokens\n"
        "/airdrop - Latest airdrops\n"
        "/airdrops active - Active airdrops\n"
        "/prime - Latest Prime Sales\n"
        "/prime active - Active Prime Sales\n"
        "/prime estimate <yours> <total> <allocation> - Estimate an allocation\n"
        "/market - Market overview\n"
        "/price BTC - Price for a symbol (BTCUSDT)\n"
        "/gainers - Top gainers\n"
        "/losers - Top losers\n"
        "/watchlist - Watchlist prices\n"
        "/funding [symbol] - Funding rates\n"
        "/openinterest - Open interest\n"
        "/longshort - Long/short ratios\n"
        "/news [category] - Latest news\n"
        "/listings - Latest listings\n"
        "/delistings - Latest delistings\n"
        "/alerts - Latest market alerts"
    )


@router.message(Command("status"))
async def status_handler(message: types.Message) -> None:
    await message.answer(
        "Bot status: online. Foundation phase only; market modules arrive in later phases."
    )


async def _reply_competitions(
    message: types.Message, status_filter: str | None = None, search: str | None = None
) -> None:
    from app.competitions.notifications import format_competition_message
    from app.models import Competition

    db = _db()
    try:
        q = db.query(Competition)
        if status_filter:
            q = q.filter(Competition.status == status_filter)
        if search:
            q = q.filter(Competition.competition_name.ilike(f"%{search}%"))
        competitions = q.order_by(Competition.id.desc()).limit(5).all()
    finally:
        db.close()
    if not competitions:
        await message.answer("None recorded yet.")
        return
    lines = [format_competition_message(c) for c in competitions]
    await message.answer("\n\n".join(lines))


@router.message(Command("competition"))
async def competition_handler(message: types.Message) -> None:
    args = _args(message)
    if not args:
        await _reply_competitions(message)
        return
    first = args[0].lower()
    if first == "active":
        await _reply_competitions(message, status_filter="ACTIVE")
    elif first == "upcoming":
        await _reply_competitions(message, status_filter="UPCOMING")
    elif first == "completed":
        await _reply_competitions(message, status_filter="ENDED")
    elif first == "search":
        if len(args) < 2:
            await message.answer("Usage: /competition search <name>")
            return
        await _reply_competitions(message, search=" ".join(args[1:]))
    else:
        await _reply_competitions(message, search=" ".join(args))


@router.message(Command("alpha"))
async def alpha_handler(message: types.Message) -> None:
    args = _args(message)
    await _reply_alpha(message, args[0] if args else None)


@router.message(Command("airdrop"))
async def airdrop_handler(message: types.Message) -> None:
    await _reply_airdrops(message, active_only=False)


@router.message(Command("airdrops"))
async def airdrops_handler(message: types.Message) -> None:
    args = _args(message)
    await _reply_airdrops(message, active_only=(args and args[0].lower() == "active"))


@router.message(Command("prime"))
async def prime_handler(message: types.Message) -> None:
    args = _args(message)
    if args and args[0].lower() == "estimate":
        if len(args) < 4:
            await message.answer(
                "Usage: /prime estimate <your commitment> <total commitment> <total allocation>"
            )
            return
        try:
            user = Decimal(args[1])
            total = Decimal(args[2])
            allocation = Decimal(args[3])
        except InvalidOperation:
            await message.answer("Commitment and allocation values must be numbers.")
            return
        from app.intelligence.allocation import estimate_allocation

        try:
            result = estimate_allocation(user, total, allocation)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await message.answer(
            f"Estimated allocation: {result['estimated_allocation']}\n"
            "This is an estimate only, not a guaranteed allocation."
        )
        return
    if args and args[0].lower() == "active":
        await _reply_prime(message, active_only=True)
        return
    await _reply_prime(message, active_only=False)


async def _reply_market(message: types.Message, kind: str = "overview") -> None:
    from app.marketintel.service import gainers_losers, latest_snapshots_by_symbol
    from app.models import MarketWatchlist

    db = _db()
    try:
        latest = latest_snapshots_by_symbol(db)
        rows = sorted(latest.values(), key=lambda r: r.symbol)
        if kind == "gainers" or kind == "losers":
            from app.config import settings as _settings

            result = gainers_losers(
                [
                    {
                        "symbol": r.symbol,
                        "price": r.price,
                        "price_change_24h": r.price_change_24h,
                        "price_change_percent_24h": r.price_change_percent_24h,
                        "high_24h": r.high_24h,
                        "low_24h": r.low_24h,
                        "volume_24h": r.volume_24h,
                        "quote_volume_24h": r.quote_volume_24h,
                        "source": r.source,
                    }
                    for r in rows
                ],
                limit=5,
                min_quote_volume=_settings.market_min_quote_volume_usdt,
            )
            chosen = result["gainers"] if kind == "gainers" else result["losers"]
            lines = [
                f"{r['symbol']}: {r['price']} ({r['price_change_percent_24h']}%)" for r in chosen
            ]
        elif kind == "watchlist":
            symbols = [w.symbol for w in db.query(MarketWatchlist).all()]
            lines = []
            for symbol in symbols:
                snapshot = latest.get(symbol)
                if snapshot:
                    lines.append(
                        f"{symbol}: {snapshot.price} ({snapshot.price_change_percent_24h}%)"
                    )
                else:
                    lines.append(f"{symbol}: Unavailable")
        else:
            lines = [f"{r.symbol}: {r.price} ({r.price_change_percent_24h}%)" for r in rows[:10]]
    finally:
        db.close()
    if not lines:
        await message.answer("None recorded yet.")
        return
    await message.answer("\n".join(lines))


async def _reply_price(message: types.Message, query: str | None) -> None:
    if not query:
        await message.answer("Usage: /price <symbol> (for example /price BTC)")
        return
    from app.binance.client import validate_symbol
    from app.marketintel.service import latest_snapshots_by_symbol

    try:
        symbol = validate_symbol(
            query if query.upper().endswith("USDT") else query.upper() + "USDT"
        )
    except ValueError:
        await message.answer("Invalid symbol. Use a symbol like BTC or BTCUSDT.")
        return
    db = _db()
    try:
        snapshot = latest_snapshots_by_symbol(db).get(symbol)
    finally:
        db.close()
    if snapshot is None:
        await message.answer(f"No market data for {symbol} yet.")
        return
    await message.answer(
        f"{symbol}: {snapshot.price} USDT\n"
        f"24h change: {snapshot.price_change_percent_24h}%\n"
        f"24h volume: {snapshot.quote_volume_24h} USDT\n"
        "Source: Binance Spot"
    )


async def _reply_futures(message: types.Message, kind: str, query: str | None = None) -> None:
    from app.marketintel.service import latest_futures_by_symbol
    from app.models import FuturesMarketRatio

    db = _db()
    try:
        if kind == "ratios":
            rows = (
                db.query(FuturesMarketRatio)
                .order_by(FuturesMarketRatio.collected_at.desc(), FuturesMarketRatio.id.desc())
                .limit(5)
                .all()
            )
            lines = [
                f"{r.symbol} {r.ratio_type}: long {r.long_ratio} / short {r.short_ratio}"
                for r in rows
            ]
        else:
            latest = latest_futures_by_symbol(db)
            if query:
                from app.binance.client import validate_symbol

                try:
                    symbol = validate_symbol(
                        query.upper() if query.upper().endswith("USDT") else query.upper() + "USDT"
                    )
                except ValueError:
                    await message.answer("Invalid symbol. Use a symbol like BTC or BTCUSDT.")
                    return
                latest = {k: v for k, v in latest.items() if k == symbol}
            if kind == "funding":
                rows = sorted(
                    [v for v in latest.values() if v.funding_rate is not None],
                    key=lambda v: v.funding_rate,
                    reverse=True,
                )
                lines = [f"{r.symbol}: funding {r.funding_rate}" for r in rows[:5]]
            else:
                rows = sorted(
                    [v for v in latest.values() if v.open_interest is not None],
                    key=lambda v: v.open_interest,
                    reverse=True,
                )
                lines = [f"{r.symbol}: open interest {r.open_interest}" for r in rows[:5]]
    finally:
        db.close()
    if not lines:
        await message.answer("Futures data unavailable.")
        return
    await message.answer("\n".join(lines))


async def _reply_news(
    message: types.Message, category: str | None = None, listing_kind: str | None = None
) -> None:
    from app.models import CryptoNews

    db = _db()
    try:
        query = db.query(CryptoNews)
        if listing_kind == "listings":
            query = query.filter(CryptoNews.category == "LISTINGS")
        elif listing_kind == "delistings":
            query = query.filter(CryptoNews.category == "DELISTINGS")
        elif category:
            query = query.filter(CryptoNews.category == category.upper())
        rows = query.order_by(CryptoNews.id.desc()).limit(5).all()
    finally:
        db.close()
    if not rows:
        await message.answer("None recorded yet.")
        return
    lines = [f"{r.headline}\n{r.original_url}" for r in rows]
    await message.answer("\n\n".join(lines))


async def _reply_alerts(message: types.Message) -> None:
    from app.models import MarketAlert

    db = _db()
    try:
        rows = (
            db.query(MarketAlert)
            .order_by(MarketAlert.triggered_at.desc(), MarketAlert.id.desc())
            .limit(5)
            .all()
        )
    finally:
        db.close()
    if not rows:
        await message.answer("None recorded yet.")
        return
    lines = [f"{r.symbol} {r.alert_type}: {r.change_percent}%" for r in rows]
    await message.answer("\n".join(lines))


@router.message(Command("market"))
async def market_handler(message: types.Message) -> None:
    await _reply_market(message, "overview")


@router.message(Command("price"))
async def price_handler(message: types.Message) -> None:
    args = _args(message)
    await _reply_price(message, args[0] if args else None)


@router.message(Command("gainers"))
async def gainers_handler(message: types.Message) -> None:
    await _reply_market(message, "gainers")


@router.message(Command("losers"))
async def losers_handler(message: types.Message) -> None:
    await _reply_market(message, "losers")


@router.message(Command("watchlist"))
async def watchlist_handler(message: types.Message) -> None:
    await _reply_market(message, "watchlist")


@router.message(Command("funding"))
async def funding_handler(message: types.Message) -> None:
    args = _args(message)
    await _reply_futures(message, "funding", args[0] if args else None)


@router.message(Command("openinterest"))
async def open_interest_handler(message: types.Message) -> None:
    await _reply_futures(message, "open_interest")


@router.message(Command("longshort"))
async def longshort_handler(message: types.Message) -> None:
    await _reply_futures(message, "ratios")


@router.message(Command("news"))
async def news_handler(message: types.Message) -> None:
    args = _args(message)
    await _reply_news(message, category=args[0] if args else None)


@router.message(Command("listings"))
async def listings_handler(message: types.Message) -> None:
    await _reply_news(message, listing_kind="listings")


@router.message(Command("delistings"))
async def delistings_handler(message: types.Message) -> None:
    await _reply_news(message, listing_kind="delistings")


@router.message(Command("alerts"))
async def alerts_handler(message: types.Message) -> None:
    await _reply_alerts(message)


@router.message(Command("marketalerts"))
async def marketalerts_handler(message: types.Message) -> None:
    await _reply_alerts(message)


async def run_bot() -> None:
    """Start long polling. Returns without crashing when no token is set,
    so the bot service does not enter a restart loop in Phase 1."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; bot will not start polling")
        return
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    logger.info("Telegram bot polling started")
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
