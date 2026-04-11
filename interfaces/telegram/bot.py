from __future__ import annotations
import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

from db.database import Database
from interfaces.telegram.commands import (
    cmd_trending, cmd_deepdive, cmd_track, cmd_untrack,
    cmd_topics, cmd_ask, cmd_status, handle_callback,
)

logger = logging.getLogger(__name__)


def create_bot(bot_token: str, db: Database, config: dict):
    """Create and configure the Telegram bot application."""
    app = ApplicationBuilder().token(bot_token).build()

    # Store db in bot_data for handlers to access
    app.bot_data["db"] = db
    app.bot_data["config"] = config

    # Register command handlers
    app.add_handler(CommandHandler("trending", cmd_trending))
    app.add_handler(CommandHandler("deepdive", cmd_deepdive))
    app.add_handler(CommandHandler("track", cmd_track))
    app.add_handler(CommandHandler("untrack", cmd_untrack))
    app.add_handler(CommandHandler("topics", cmd_topics))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("start", cmd_status))  # /start shows status

    # Register callback query handler for inline keyboards
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app


async def send_alert(bot_token: str, chat_id: str, text: str) -> None:
    """Send a proactive alert message."""
    from telegram import Bot
    bot = Bot(token=bot_token)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
