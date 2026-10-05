import html
import logging
import traceback
from telegram import Update
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global uncaught error handler for python-telegram-bot."""
    err = context.error

    if isinstance(err, Conflict):
        logger.critical(
            "Conflict error: Another instance of this bot is running with the same token! "
            "Terminating duplicate polling."
        )
        return

    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning("Telegram network timeout / connection glitch: %s", err)
        return

    # Log full traceback for unexpected runtime exceptions
    tb_list = traceback.format_exception(None, err, err.__traceback__)
    tb_string = "".join(tb_list)
    logger.error("Uncaught exception while processing update: %s\n%s", err, tb_string)

    # Inform the user if possible
    if isinstance(update, Update) and update.effective_message:
        try:
            error_notice = (
                "⚠️ <b>An unexpected processing error occurred.</b>\n\n"
                "The error has been logged to system telemetry. "
                "Please verify your inputs or retry in a few moments."
            )
            await update.effective_message.reply_text(
                error_notice,
                parse_mode="HTML",
                message_thread_id=update.effective_message.message_thread_id,
            )
        except Exception as e:
            logger.debug("Failed to send error notification to user: %s", e)
