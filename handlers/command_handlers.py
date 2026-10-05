import html
import logging
from datetime import datetime, timezone
from typing import Optional
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from config import COURSES, CourseInfo, settings
from database import db_manager
from services import (
    format_deadline_datetime,
    llm_engine,
    parse_due_command_text,
)
from utils import (
    get_reply_target,
    get_thread_id,
    rate_limiter,
    safe_reply_text,
    send_typing_action,
)

logger = logging.getLogger(__name__)


async def resolve_course(update: Update) -> CourseInfo:
    """Resolve current course from thread ID via DB or static settings."""
    chat_id = update.effective_chat.id if update.effective_chat else 0
    thread_id = get_thread_id(update.effective_message)

    if thread_id:
        db_course_key = await db_manager.get_topic_binding(chat_id, thread_id)
        if db_course_key and db_course_key in COURSES:
            return COURSES[db_course_key]

    return settings.get_course_by_thread_id(thread_id)


# ------------------------------------------------------------------------------
# Navigation & System Commands
# ------------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message and overview."""
    course = await resolve_course(update)
    welcome_text = (
        f"🎓 <b>Welcome to Year 5 CS/IT Academic Assistant Bot</b>\n\n"
        f"Currently Active Topic: {course.icon} <b>{course.name}</b> (<code>{course.code}</code>)\n\n"
        f"This bot is custom-built for final-year university students across 8 core disciplines. "
        f"In each forum topic, domain context and system instructions are automatically injected!\n\n"
        f"<b>Key Commands:</b>\n"
        f"• <code>/help</code> - Full command manual\n"
        f"• <code>/get_id</code> - Show Chat ID and Topic Thread ID\n"
        f"• <code>/courses</code> - List all 8 courses & thread bindings\n"
        f"• <code>/fix</code> - Reply to a draft message to refine academic prose\n"
        f"• <code>/debug</code> - Reply to code/error traces to debug\n"
        f"• <code>/translate [kh|en]</code> - Translate academic text preserving technical terms\n"
        f"• <code>/due &lt;date&gt; &lt;task&gt;</code> - Record assignment deadline\n"
        f"• <code>/deadlines</code> - List upcoming assignments for this course\n"
        f"• <code>/done &lt;id&gt;</code> - Mark assignment as complete\n"
        f"• 📁 <i>Upload PDF, Word, PowerPoint, Excel, or Jupyter Notebooks</i> - Instant lecture digest & data analysis!"
    )
    await safe_reply_text(update, context, welcome_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detailed command reference."""
    help_text = (
        f"📖 <b>Year 5 CS Bot - Command Reference Manual</b>\n\n"
        f"<b>1. Document Ingestion & Slide Summaries</b>\n"
        f"• Upload any <code>.pdf</code>, <code>.docx</code>, <code>.pptx</code>, <code>.xlsx</code>, <code>.ipynb</code>, <code>.csv</code>, or code file directly into any course topic.\n"
        f"• The bot extracts text in-memory and outputs executive takeaways, mathematical formulas, lab tasks, and sample exam questions.\n"
        f"• Add caption <code>/translate kh</code> or <code>/translate en</code> during upload for instant translation!\n\n"
        f"<b>2. Text Refactoring & Academic Tone</b>\n"
        f"• <code>/fix</code> or <code>/refactor</code> (Reply to message)\n"
        f"  Outputs 3 refined versions: Professor Inquiry, Group Project coordination, and Academic Presentation.\n\n"
        f"<b>3. Lab Code Debugger</b>\n"
        f"• <code>/debug</code> (Reply to code/error or type code after command)\n"
        f"  Pinpoints root cause, tensor dimension mismatches, network/system issues, and provides corrected, commented code.\n\n"
        f"<b>4. Academic Translation</b>\n"
        f"• <code>/translate kh</code> (Reply to text/doc) - Translate to Academic Khmer with English CS terms preserved.\n"
        f"• <code>/translate en</code> (Reply to text/doc) - Translate/polish to formal Academic English.\n\n"
        f"<b>5. Deadline & Task Tracking</b>\n"
        f"• <code>/due &lt;date/time&gt; &lt;description&gt;</code> - Add deadline\n"
        f"  <i>Examples:</i>\n"
        f"  <code>/due 2026-10-25 23:59 Final Project Milestone 1</code>\n"
        f"  <code>/due tomorrow 5pm Homework Lab 4</code>\n"
        f"  <code>/due in 3 days Research Paper Review</code>\n"
        f"• <code>/deadlines</code> - Show pending assignments for this topic\n"
        f"• <code>/done &lt;id&gt;</code> - Mark assignment complete\n"
        f"• <code>/delete_due &lt;id&gt;</code> - Remove assignment\n\n"
        f"<b>6. Forum Topic Administration</b>\n"
        f"• <code>/get_id</code> - View current Chat ID & Thread ID\n"
        f"• <code>/set_topic &lt;COURSE_KEY&gt;</code> - Bind current topic thread to course (Admin only)"
    )
    await safe_reply_text(update, context, help_text)


async def get_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Helper command to get chat_id and message_thread_id for forum topic configuration."""
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title or "Private Chat"
    thread_id = get_thread_id(update.effective_message)
    course = await resolve_course(update)

    response = (
        f"🔍 <b>Telegram Topic Thread Diagnostics</b>\n\n"
        f"• <b>Chat Title:</b> {html.escape(chat_title)}\n"
        f"• <b>Chat Type:</b> <code>{chat_type}</code>\n"
        f"• <b>Chat ID:</b> <code>{chat_id}</code>\n"
        f"• <b>Message Thread ID:</b> <code>{thread_id if thread_id is not None else 0}</code> "
        f"({'General/Root' if not thread_id else 'Sub-Topic Thread'})\n"
        f"• <b>Resolved Course:</b> {course.icon} <b>{course.name}</b> (<code>{course.key}</code>)\n\n"
        f"💡 <i>Tip for Admin:</i> You can paste this thread ID into your <code>.env</code> file "
        f"or run <code>/set_topic {course.key}</code> directly in this topic!"
    )
    await safe_reply_text(update, context, response)


async def set_topic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to bind the current forum topic to a specific course key."""
    if not update.effective_message or not update.effective_chat or not update.effective_user:
        return

    user_id = update.effective_user.id
    admins = settings.get_admin_ids()

    # Check if user is bot admin or chat administrator
    is_admin = user_id in admins
    if not is_admin and update.effective_chat.type in ("group", "supergroup"):
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        if member.status in ("creator", "administrator"):
            is_admin = True

    if not is_admin:
        await safe_reply_text(update, context, "⚠️ <i>Permission denied. Only group administrators can bind topics.</i>")
        return

    thread_id = get_thread_id(update.effective_message)
    if not thread_id:
        await safe_reply_text(
            update,
            context,
            "⚠️ <i>This command must be executed inside a specific forum topic thread, not General.</i>",
        )
        return

    if not context.args:
        valid_keys = ", ".join([f"<code>{k}</code>" for k in COURSES.keys()])
        await safe_reply_text(
            update,
            context,
            f"Usage: <code>/set_topic &lt;COURSE_KEY&gt;</code>\n\nValid keys:\n{valid_keys}",
        )
        return

    course_key = context.args[0].upper().strip()
    if course_key not in COURSES:
        valid_keys = ", ".join([f"<code>{k}</code>" for k in COURSES.keys()])
        await safe_reply_text(
            update,
            context,
            f"❌ Unknown course key <code>{course_key}</code>.\n\nAvailable keys:\n{valid_keys}",
        )
        return

    chat_id = update.effective_chat.id
    await db_manager.bind_topic(chat_id, thread_id, course_key)
    course_info = COURSES[course_key]

    await safe_reply_text(
        update,
        context,
        f"✅ <b>Topic Successfully Bound!</b>\n\n"
        f"This forum thread (ID: <code>{thread_id}</code>) is now officially mapped to:\n"
        f"{course_info.icon} <b>{course_info.name}</b> (<code>{course_info.code}</code>)\n\n"
        f"<i>All AI interactions, document parsing, and deadlines in this thread now inherit this course's domain context.</i>",
    )


async def courses_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all 8 courses and current thread mappings."""
    chat_id = update.effective_chat.id if update.effective_chat else 0
    db_bindings = await db_manager.get_all_topic_bindings(chat_id)

    lines = ["📚 <b>Year 5 Semester 1 - Curriculum Overview</b>\n"]
    for key, c in COURSES.items():
        thread_bound = None
        for tid, ckey in db_bindings.items():
            if ckey == key:
                thread_bound = tid
                break

        bound_info = f"Bound to Thread ID: <code>{thread_bound}</code>" if thread_bound else "Configured via .env or unassigned"
        lines.append(
            f"{c.icon} <b>{c.name}</b> [<code>{c.key}</code> - {c.code}]\n"
            f"   {c.description}\n"
            f"   📍 <i>Status:</i> {bound_info}\n"
        )

    await safe_reply_text(update, context, "\n".join(lines))


# ------------------------------------------------------------------------------
# Academic Intelligence Commands
# ------------------------------------------------------------------------------

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Polish message for professor, peers, or presentation."""
    if not update.effective_user or not update.effective_message:
        return

    # Check rate limit
    user_id = update.effective_user.id
    allowed, retry_after = rate_limiter.is_allowed(user_id)
    if not allowed:
        await safe_reply_text(
            update,
            context,
            f"⏳ <i>Rate limit reached. Please wait {retry_after} seconds before requesting another AI action.</i>",
        )
        return

    # Extract target text
    target_text = ""
    reply = get_reply_target(update.effective_message)
    if reply and (reply.text or reply.caption):
        target_text = reply.text or reply.caption
    elif context.args:
        target_text = " ".join(context.args)

    if not target_text.strip():
        await safe_reply_text(
            update,
            context,
            "💡 <i>Usage: Reply to any message with <code>/fix</code> or type <code>/fix &lt;your draft message&gt;</code> to polish academic prose.</i>",
        )
        return

    await send_typing_action(update, context, ChatAction.TYPING)
    course = await resolve_course(update)

    try:
        polished = await llm_engine.refactor_message(target_text, course.key)
        response = (
            f"✨ <b>Academic Message Polisher</b>\n"
            f"<i>Domain Context: {course.icon} {course.name}</i>\n\n"
            f"{polished}"
        )
        await safe_reply_text(update, context, response)
    except Exception as e:
        logger.error("Fix command error: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Error polishing message: {e}")


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analyze and debug code or runtime error traces."""
    if not update.effective_user or not update.effective_message:
        return

    user_id = update.effective_user.id
    allowed, retry_after = rate_limiter.is_allowed(user_id)
    if not allowed:
        await safe_reply_text(
            update,
            context,
            f"⏳ <i>Rate limit reached. Please wait {retry_after} seconds before debugging.</i>",
        )
        return

    # Extract snippet from reply or args
    snippet = ""
    reply = get_reply_target(update.effective_message)
    if reply and (reply.text or reply.caption):
        snippet = reply.text or reply.caption
    elif context.args:
        snippet = " ".join(context.args)

    if not snippet.strip():
        await safe_reply_text(
            update,
            context,
            "💡 <i>Usage: Reply to a code snippet or error trace with <code>/debug</code>, or provide code directly after the command.</i>",
        )
        return

    await send_typing_action(update, context, ChatAction.TYPING)
    course = await resolve_course(update)

    try:
        debug_output = await llm_engine.debug_code_or_problem(snippet, course.key)
        response = (
            f"🛠️ <b>Lab Code & Algorithm Debugger</b>\n"
            f"<i>Domain Context: {course.icon} {course.name}</i>\n\n"
            f"{debug_output}"
        )
        await safe_reply_text(update, context, response)
    except Exception as e:
        logger.error("Debug command error: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Debugger failed: {e}")


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Translate technical academic content into Academic Khmer or polished English."""
    if not update.effective_user or not update.effective_message:
        return

    user_id = update.effective_user.id
    allowed, retry_after = rate_limiter.is_allowed(user_id)
    if not allowed:
        await safe_reply_text(
            update,
            context,
            f"⏳ <i>Rate limit reached. Please wait {retry_after} seconds.</i>",
        )
        return

    # Determine target language: default 'kh', unless 'en' specified
    target_lang = "kh"
    args = list(context.args) if context.args else []

    if args and args[0].lower() in ("en", "english"):
        target_lang = "en"
        args = args[1:]
    elif args and args[0].lower() in ("kh", "khmer"):
        target_lang = "kh"
        args = args[1:]

    # Extract text from reply or remaining args
    text_to_translate = ""
    reply = get_reply_target(update.effective_message)
    if reply and (reply.text or reply.caption):
        text_to_translate = reply.text or reply.caption
    elif args:
        text_to_translate = " ".join(args)

    if not text_to_translate.strip():
        await safe_reply_text(
            update,
            context,
            "💡 <i>Usage: Reply to any message with <code>/translate</code> or <code>/translate en</code>, or type text after the command.</i>",
        )
        return

    await send_typing_action(update, context, ChatAction.TYPING)

    try:
        translated = await llm_engine.translate_text(text_to_translate, target_lang=target_lang)
        lang_label = "🇰🇭 <b>Academic Khmer (ភាសាខ្មែរបែបសិក្សាស្រាវជ្រាវ)</b>" if target_lang == "kh" else "🇬🇧 <b>Academic English</b>"
        response = f"{lang_label}\n\n{translated}"
        await safe_reply_text(update, context, response)
    except Exception as e:
        logger.error("Translate command error: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Translation failed: {e}")


# ------------------------------------------------------------------------------
# Deadline & Task Management Commands
# ------------------------------------------------------------------------------

async def due_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record a course assignment deadline."""
    if not update.effective_message or not update.effective_chat or not update.effective_user:
        return

    raw_args = " ".join(context.args) if context.args else ""
    if not raw_args.strip():
        usage = (
            "💡 <b>Deadline Command Usage:</b>\n"
            "<code>/due &lt;date/time&gt; &lt;task description&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/due 2026-10-25 23:59 Final Project Milestone 1</code>\n"
            "• <code>/due 25/10/2026 18:00 Cloud Architecture Proposal</code>\n"
            "• <code>/due tomorrow 5pm Homework Lab 3</code>\n"
            "• <code>/due in 3 days Research Paper Review</code>\n"
            "• <code>/due friday 23:59 Network Security Lab Report</code>"
        )
        await safe_reply_text(update, context, usage)
        return

    due_dt, description = parse_due_command_text(raw_args)
    if not due_dt or not description:
        await safe_reply_text(
            update,
            context,
            "❌ <i>Could not recognize the date/time format. Please use formats like:</i>\n"
            "<code>2026-10-25 23:59</code>, <code>25/10/2026 18:00</code>, <code>tomorrow 5pm</code>, or <code>in 3 days</code>.",
        )
        return

    if due_dt <= datetime.now(timezone.utc):
        due_formatted = format_deadline_datetime(due_dt, settings.TIMEZONE)
        await safe_reply_text(
            update,
            context,
            f"❌ <i>That deadline is already in the past ({due_formatted}). Please provide a future date/time.</i>",
        )
        return

    course = await resolve_course(update)
    chat_id = update.effective_chat.id
    thread_id = get_thread_id(update.effective_message)
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name or update.effective_user.username or "Student"

    # Split title from description if multiple words
    words = description.split()
    title = " ".join(words[:6])  # First few words as title
    if len(words) > 6:
        title += "..."

    try:
        deadline = await db_manager.add_deadline(
            chat_id=chat_id,
            thread_id=thread_id,
            course_key=course.key,
            title=title,
            description=description,
            due_date=due_dt,
            created_by_user_id=user_id,
            created_by_name=user_name,
        )

        due_formatted = format_deadline_datetime(due_dt, settings.TIMEZONE)
        card = (
            f"✅ <b>Assignment Deadline Recorded!</b>\n\n"
            f"🆔 <b>Task ID:</b> <code>#{deadline.id}</code>\n"
            f"{course.icon} <b>Course:</b> {course.name} (<code>{course.code}</code>)\n"
            f"📌 <b>Title:</b> {html.escape(deadline.title)}\n"
            f"📅 <b>Due Date:</b> {due_formatted}\n"
            f"👤 <b>Created By:</b> {html.escape(user_name)}\n"
            f"🔔 <i>Automated reminders will trigger 24h, 6h, and 1h prior to deadline in this topic!</i>\n\n"
            f"💡 <i>Mark as complete when finished:</i> <code>/done {deadline.id}</code>"
        )
        await safe_reply_text(update, context, card)

    except Exception as e:
        logger.error("Failed to add deadline: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Failed to record deadline: {e}")


async def deadlines_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending uncompleted deadlines for this thread/supergroup."""
    if not update.effective_chat or not update.effective_message:
        return

    chat_id = update.effective_chat.id
    thread_id = get_thread_id(update.effective_message)
    course = await resolve_course(update)

    try:
        deadlines = await db_manager.get_upcoming_deadlines(chat_id, thread_id)
        if not deadlines:
            await safe_reply_text(
                update,
                context,
                f"🎉 <b>No upcoming pending deadlines!</b>\n"
                f"<i>Currently viewed: {course.icon} {course.name}</i>\n"
                f"Add new assignments anytime using <code>/due &lt;date&gt; &lt;task&gt;</code>.",
            )
            return

        lines = [f"📋 <b>Upcoming Deadlines & Milestones</b>\n<i>Topic Context: {course.icon} {course.name}</i>\n"]
        for d in deadlines:
            c_info = COURSES.get(d.course_key, COURSES["GENERAL"])
            due_str = format_deadline_datetime(d.due_date, settings.TIMEZONE)
            lines.append(
                f"• <b>[#{d.id}]</b> {c_info.icon} <b>{html.escape(d.title)}</b>\n"
                f"  📅 <i>Due:</i> {due_str}\n"
                f"  👤 <i>By:</i> {html.escape(d.created_by_name)} | "
                f"<i>Complete:</i> <code>/done {d.id}</code>\n"
            )

        await safe_reply_text(update, context, "\n".join(lines))

    except Exception as e:
        logger.error("Failed to list deadlines: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Failed to fetch deadlines: {e}")


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark a deadline as completed."""
    if not context.args or not context.args[0].isdigit():
        await safe_reply_text(update, context, "💡 <i>Usage: <code>/done &lt;task_id&gt;</code> (e.g. <code>/done 1</code>)</i>")
        return

    task_id = int(context.args[0])
    try:
        deadline = await db_manager.get_deadline_by_id(task_id)
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not deadline or deadline.chat_id != chat_id:
            await safe_reply_text(update, context, f"❌ Deadline #{task_id} not found.")
            return

        if deadline.is_completed:
            await safe_reply_text(update, context, f"ℹ️ Task #{task_id} was already marked as completed!")
            return

        success = await db_manager.mark_deadline_completed(task_id)
        if success:
            await safe_reply_text(
                update,
                context,
                f"🎉 <b>Task #{task_id} Completed!</b>\n"
                f"Great job finishing <b>{html.escape(deadline.title)}</b>!",
            )
        else:
            await safe_reply_text(update, context, f"❌ Could not update task #{task_id}.")

    except Exception as e:
        logger.error("Done command error: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Error: {e}")


async def delete_due_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a deadline."""
    if not context.args or not context.args[0].isdigit():
        await safe_reply_text(update, context, "💡 <i>Usage: <code>/delete_due &lt;task_id&gt;</code></i>")
        return

    task_id = int(context.args[0])
    user_id = update.effective_user.id if update.effective_user else 0

    try:
        deadline = await db_manager.get_deadline_by_id(task_id)
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not deadline or deadline.chat_id != chat_id:
            await safe_reply_text(update, context, f"❌ Deadline #{task_id} not found.")
            return

        # Check permission: creator or bot admin
        is_admin = user_id in settings.get_admin_ids() or user_id == deadline.created_by_user_id
        if not is_admin:
            await safe_reply_text(
                update,
                context,
                "⚠️ <i>Permission denied. Only the task creator or bot administrator can delete this deadline.</i>",
            )
            return

        success = await db_manager.delete_deadline(task_id)
        if success:
            await safe_reply_text(update, context, f"🗑️ <b>Deadline #{task_id} deleted successfully.</b>")
        else:
            await safe_reply_text(update, context, f"❌ Could not delete task #{task_id}.")

    except Exception as e:
        logger.error("Delete deadline error: %s", e, exc_info=True)
        await safe_reply_text(update, context, f"❌ Error deleting deadline: {e}")
