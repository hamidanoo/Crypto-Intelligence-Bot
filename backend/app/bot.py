"""Telegram bot connection structure for Phase 1.

This module owns the bot handlers only. No market, announcement, or
competition logic lives here; later phases call the backend services
and publish through the handlers defined in this module's router.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command

from app.config import settings

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def start_handler(message: types.Message) -> None:
    await message.answer(
        "Crypto Intelligence Bot is online. Use /help to see available commands."
    )


@router.message(Command("help"))
async def help_handler(message: types.Message) -> None:
    await message.answer(
        "Available commands:\n"
        "/start - Check the bot is online\n"
        "/help - Show this help message\n"
        "/status - Show the bot status"
    )


@router.message(Command("status"))
async def status_handler(message: types.Message) -> None:
    await message.answer("Bot status: online. Foundation phase only; market modules arrive in later phases.")


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
