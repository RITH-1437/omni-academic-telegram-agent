import logging
import re
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from handlers.command_handlers import resolve_course
from services import llm_engine
from utils import get_reply_target, rate_limiter, safe_reply_text, send_typing_action

logger = logging.getLogger(__name__)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle natural language questions in forum topic threads or private chats.
    In supergroups, responds if mentioned (@bot_name) or when replying to bot's message.
    """
    if not update.effective_message or not update.effective_message.text:
        return

    text = update.effective_message.text.strip()
    # Ignore slash commands (they are routed by CommandHandler)
    if text.startswith("/"):
        return

    chat = update.effective_chat
    bot_username = (context.bot.username or "").lower()
    is_private = chat and chat.type == "private"

    # Check if bot is mentioned or replied to
    is_reply_to_bot = False
    reply = get_reply_target(update.effective_message)
    if reply and reply.from_user:
        is_reply_to_bot = reply.from_user.id == context.bot.id

    is_mentioned = False
    if bot_username and f"@{bot_username}" in text.lower():
        is_mentioned = True
        # Clean mention from prompt (usernames are case-insensitive: "@MyBot" == "@mybot")
        text = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip()

    # If in a group and not mentioned/replied, do not interrupt student conversations
    if not is_private and not is_reply_to_bot and not is_mentioned:
        return

    if not text:
        return

    # Check rate limit
    user_id = update.effective_user.id if update.effective_user else 0
    allowed, retry_after = rate_limiter.is_allowed(user_id)
    if not allowed:
        await safe_reply_text(
            update,
            context,
            f"⏳ <i>Rate limit reached. Please wait {retry_after} seconds before asking another question.</i>",
        )
        return

    course = await resolve_course(update)
    await send_typing_action(update, context, ChatAction.TYPING)

    try:
        response = await llm_engine.answer_academic_query(text, course.key)
        formatted_response = (
            f"{course.icon} <b>[{course.name}]</b>\n\n"
            f"{response}"
        )
        await safe_reply_text(update, context, formatted_response)
    except Exception as e:
        logger.error("Failed to answer text query: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Failed to process query: {e}")
