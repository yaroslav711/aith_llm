#!/usr/bin/env python3
from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.transport.session_manager import SessionManager
from src.transport.telegram_handlers import TelegramHandlers

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main():
    """Start Telegram bot for AI Mediator."""
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_username = os.getenv("TELEGRAM_BOT_USERNAME")

    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be set in .env file")

    if not telegram_username:
        raise ValueError("TELEGRAM_BOT_USERNAME must be set in .env file")

    logger.info("Starting AI Mediator bot @%s", telegram_username)

    # In-memory state
    session_manager = SessionManager()

    # Handlers
    handlers = TelegramHandlers(session_manager, telegram_username)

    # Build application
    app = Application.builder().token(telegram_token).build()

    async def error_handler(update, context):
        logger.error("Update %s caused error %s", update, context.error)

    app.add_error_handler(error_handler)

    # Commands
    app.add_handler(CommandHandler("start", handlers.start_command))
    app.add_handler(CommandHandler("invite", handlers.invite_command))
    app.add_handler(CommandHandler("help", handlers.help_command))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    logger.info("Bot initialized with commands: /start, /invite, /help")

    # Clear webhook to avoid conflicts with polling
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared successfully")
    except Exception as e:
        logger.warning("Could not clear webhook: %s", e)

    # Set bot commands (visible in Telegram menu)
    try:
        from telegram import BotCommand

        commands = [
            BotCommand("start", "Начать работу с ботом"),
            BotCommand("invite", "Создать приглашение для партнера"),
            BotCommand("help", "Показать справку"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully")
    except Exception as e:
        logger.warning("Could not set bot commands: %s", e)

    # Set bot description
    try:
        description = (
            "AI Mediator помогает парам находить решения в конфликтных ситуациях.\n\n"
            "🗣️ Каждый общается в своем чате\n"
            "💡 Бот помогает понять друг друга\n"
            "🤝 Вместе находим компромисс"
        )
        await app.bot.set_my_description(description)
        logger.info("Bot description set successfully")
    except Exception as e:
        logger.warning("Could not set bot description: %s", e)

    # Start polling
    logger.info("Starting polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    logger.info("Bot is now running. Press Ctrl+C to stop.")

    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Bot crashed: %s", e)
        import traceback

        traceback.print_exc()
