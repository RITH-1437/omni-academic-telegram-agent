#!/usr/bin/env python3
"""
Year 5 CS/IT Telegram Supergroup Assistant Bot.

Production-grade asynchronous Telegram bot supporting 8 distinct course forum topics,
in-memory document summarization, academic Khmer/English translation, lab code debugging,
and scheduled deadline reminders.
"""

import asyncio
import logging
import sys
from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import settings
from database import db_manager
from handlers import (
    courses_command,
    deadlines_command,
    debug_command,
    delete_due_command,
    done_command,
    due_command,
    fix_command,
    get_id_command,
    global_error_handler,
    handle_document_upload,
    handle_text_message,
    help_command,
    set_topic_command,
    start_command,
    translate_command,
)
from services import deadline_checker_job, llm_engine

# Configure structured production logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("Year5Bot")

# Quiet down verbose HTTP request loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.INFO)


async def post_init(application: Application) -> None:
    """Post-initialization hook: Set bot commands menu and initialize database."""
    logger.info("Initializing SQLite database connection...")
    await db_manager.init_db()

    logger.info("Setting Telegram bot command menu autocomplete...")
    commands = [
        BotCommand("start", "Initialize bot & view course guide"),
        BotCommand("help", "Display full command reference"),
        BotCommand("get_id", "Get Chat ID & Topic Thread ID"),
        BotCommand("courses", "View 8 curriculum courses & status"),
        BotCommand("fix", "Polish message (Reply to text)"),
        BotCommand("debug", "Debug code/error (Reply or type)"),
        BotCommand("translate", "Translate to Khmer/English (Reply to text/doc)"),
        BotCommand("due", "Set deadline: /due <date> <task>"),
        BotCommand("deadlines", "View upcoming assignments"),
        BotCommand("done", "Complete task: /done <id>"),
    ]
    await application.bot.set_my_commands(commands)

    # Schedule recurring background deadline reminder job (every 15 minutes = 900 seconds)
    if application.job_queue:
        application.job_queue.run_repeating(
            deadline_checker_job,
            interval=900,
            first=10,
            name="deadline_reminder_service",
        )
        logger.info("Deadline reminder background job scheduled (every 15 minutes).")
    else:
        logger.warning("JobQueue is not enabled! Scheduled deadline reminders will not run.")

    bot_info = await application.bot.get_me()
    logger.info("Bot authenticated successfully as @%s (ID: %s)", bot_info.username, bot_info.id)


async def post_shutdown(application: Application) -> None:
    """Release the shared LLM HTTP connection pool."""
    await llm_engine.close()


def build_application() -> Application:
    """Construct and configure the python-telegram-bot Application."""
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("123456789:"):
        logger.critical("TELEGRAM_BOT_TOKEN is not configured! Please provide a valid token in .env")
        sys.exit(1)

    has_llm_key = any([
        settings.OPENROUTER_API_KEY and not settings.OPENROUTER_API_KEY.startswith("your_"),
        settings.OPENCODE_ZEN_API_KEY and not settings.OPENCODE_ZEN_API_KEY.startswith("your_"),
        settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("AIzaSyYour"),
    ])
    if not has_llm_key:
        logger.critical(
            "No valid LLM API key configured! Please set OPENROUTER_API_KEY, "
            "OPENCODE_ZEN_API_KEY, or GEMINI_API_KEY in your .env file."
        )
        sys.exit(1)

    # Build PTB Application with built-in JobQueue
    app = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(True)
        .build()
    )

    # 1. Navigation & Administrative Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("get_id", get_id_command))
    app.add_handler(CommandHandler("id", get_id_command))
    app.add_handler(CommandHandler("set_topic", set_topic_command))
    app.add_handler(CommandHandler("courses", courses_command))

    # 2. Academic Intelligence Commands
    app.add_handler(CommandHandler(["fix", "refactor", "polish"], fix_command))
    app.add_handler(CommandHandler(["debug", "solve"], debug_command))
    app.add_handler(CommandHandler(["translate", "khmer", "english"], translate_command))

    # 3. Deadline & Task Management Commands
    app.add_handler(CommandHandler("due", due_command))
    app.add_handler(CommandHandler(["deadlines", "tasks"], deadlines_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("delete_due", delete_due_command))

    # 4. Document Ingestion Handler (.pdf, .docx, .pptx, .txt)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_upload))

    # 5. Natural Language & Mention Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # 6. Global Uncaught Exception Handler
    app.add_error_handler(global_error_handler)

    return app


def main() -> None:
    """Main application entry point."""
    logger.info("Starting Year 5 CS/IT Telegram Supergroup Bot...")
    app = build_application()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
