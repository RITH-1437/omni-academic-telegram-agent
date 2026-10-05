import html
import logging
from datetime import datetime, timezone
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from config import COURSES, settings
from database import db_manager
from services.date_parser import format_deadline_datetime

logger = logging.getLogger(__name__)

# A later (more urgent) stage implies the earlier ones are moot: never send
# "24h left" after "1h left" when a deadline is created late or the bot was offline.
STAGES_SUPERSEDED_BY = {
    "1h": ("1h", "6h", "24h"),
    "6h": ("6h", "24h"),
    "24h": ("24h",),
}


async def deadline_checker_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Scheduled job callback executed every 15 minutes by JobQueue.
    Checks for pending deadlines and sends automated reminders into the corresponding
    course forum topic threads.
    """
    now = datetime.now(timezone.utc)
    try:
        pending_deadlines = await db_manager.get_pending_reminders(now)
    except Exception as e:
        logger.error("Error retrieving pending reminders from database: %s", e, exc_info=True)
        return

    if not pending_deadlines:
        return

    logger.debug("Checking %d pending deadlines for reminders...", len(pending_deadlines))

    for item in pending_deadlines:
        try:
            delta = item.due_date - now
            seconds_remaining = delta.total_seconds()

            if seconds_remaining <= 0:
                continue

            stage = None
            urgency_header = ""
            time_remaining_str = ""

            # 1-Hour Critical Alert
            if seconds_remaining <= 3600 and not item.reminded_1h:
                stage = "1h"
                urgency_header = "🚨 <b>CRITICAL DEADLINE ALERT (Less than 1 Hour Left!)</b>"
                mins = max(1, int(seconds_remaining // 60))
                time_remaining_str = f"⏳ <b>Time Remaining:</b> {mins} minutes"

            # 6-Hour Urgent Alert
            elif seconds_remaining <= 21600 and not item.reminded_6h:
                stage = "6h"
                urgency_header = "⚠️ <b>URGENT DEADLINE REMINDER (Under 6 Hours Left)</b>"
                hours = int(seconds_remaining // 3600)
                mins = int((seconds_remaining % 3600) // 60)
                time_remaining_str = f"⏳ <b>Time Remaining:</b> {hours}h {mins}m"

            # 24-Hour Notice
            elif seconds_remaining <= 86400 and not item.reminded_24h:
                stage = "24h"
                urgency_header = "⏰ <b>24-HOUR UPCOMING DEADLINE NOTICE</b>"
                hours = int(seconds_remaining // 3600)
                time_remaining_str = f"⏳ <b>Time Remaining:</b> approximately {hours} hours"

            if not stage:
                continue

            course_info = COURSES.get(item.course_key, COURSES["GENERAL"])
            due_formatted = format_deadline_datetime(item.due_date, settings.TIMEZONE)

            message_text = (
                f"{urgency_header}\n\n"
                f"{course_info.icon} <b>Course:</b> {course_info.name} (<code>{course_info.code}</code>)\n"
                f"📌 <b>Task #{item.id}:</b> {html.escape(item.title)}\n"
                f"📅 <b>Due Date:</b> {due_formatted}\n"
                f"{time_remaining_str}\n"
                f"👤 <b>Posted By:</b> {html.escape(item.created_by_name)}\n"
            )

            if item.description and item.description != item.title:
                message_text += f"\n📝 <b>Details:</b>\n{html.escape(item.description)}\n"

            message_text += "\n💡 <i>Mark as finished when done:</i> <code>/done " + str(item.id) + "</code>"

            # Send directly to the specific topic thread
            try:
                await context.bot.send_message(
                    chat_id=item.chat_id,
                    message_thread_id=item.thread_id,
                    text=message_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except BadRequest as e:
                # Topic deleted/closed, or a legacy row holding a reply-chain ID: fall back to the main chat
                if item.thread_id is None or "thread not found" not in str(e).lower():
                    raise
                logger.warning("Thread %s gone for deadline #%d; posting to main chat.", item.thread_id, item.id)
                await context.bot.send_message(
                    chat_id=item.chat_id,
                    text=message_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Forbidden as e:
                # Bot was removed from the chat: stop retrying this stage every 15 minutes
                logger.warning("Cannot deliver reminder for deadline #%d: %s", item.id, e)
                for done_stage in STAGES_SUPERSEDED_BY[stage]:
                    await db_manager.mark_reminder_sent(item.id, done_stage)
                continue

            # Record that this stage (and any less urgent ones it supersedes) was notified
            for done_stage in STAGES_SUPERSEDED_BY[stage]:
                await db_manager.mark_reminder_sent(item.id, done_stage)
            logger.info(
                "Sent %s reminder for deadline #%d (%s) to chat %d thread %s",
                stage,
                item.id,
                item.title,
                item.chat_id,
                item.thread_id,
            )

        except Exception as e:
            logger.error(
                "Failed to send reminder for deadline #%d: %s",
                item.id,
                e,
                exc_info=True,
            )
