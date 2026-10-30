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
        "/prime estimate <yours> <total> <allocation> - Estimate an allocation"
    )


@router.message(Command("status"))
async def status_handler(message: types.Message) -> None:
    await message.answer(
        "Bot status: online. Foundation phase only; market modules arrive in later phases."
    )


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
