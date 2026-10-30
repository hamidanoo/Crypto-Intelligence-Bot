# Telegram Setup

Phase 1 covers the bot connection structure only. Full Telegram
management, notification controls, and templates arrive in
Phase 8.

1. Create a bot with BotFather on Telegram and copy the bot token.
2. Add the bot to the community group and note the group chat id.
3. Set the values in `.env` (never commit this file):
   ```
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_GROUP_ID=
   ```
   Fill in the token from BotFather and the group chat id.
4. Start the bot service (`docker compose up bot`) or run
   `python -m app.bot` from `backend/`.
5. In the group, send `/start`, `/help`, and `/status` to confirm
   the bot responds.

Without a token, the bot service logs a warning and does not
start polling, instead of crashing in a restart loop.

The bot never executes trades or withdrawals. It publishes
intelligence and accepts read-only commands, with administrative
commands restricted to authorised administrators in later phases.

## Admin Telegram management (Phase 8)

Administrators with telegram.manage can view and edit
Telegram configuration at `/admin/telegram`: group id
and title, notification enable/disable, and category
settings. The bot token itself is never returned by
the API and never shown in the UI; only its presence
is reported. The test-message button sends only when
explicitly clicked and only when a token and group
are configured.
