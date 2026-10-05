import asyncio
import html
import io
import logging
from typing import Optional, Tuple
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config import settings
from handlers.command_handlers import resolve_course
from services import (
    DocumentParseError,
    document_parser,
    llm_engine,
)
from utils import get_thread_id, rate_limiter, safe_reply_text, send_typing_action

logger = logging.getLogger(__name__)


def parse_caption_action(caption: str) -> Tuple[str, Optional[str]]:
    """
    Map an upload caption to (action, target_lang).
    '/translate', '/translate kh' -> ('translate', 'kh'); '/translate en' -> ('translate', 'en');
    '/debug' -> ('debug', None); anything else -> ('summarize', None).
    Accepts the '/command@BotName' form used in groups.
    """
    tokens = caption.strip().split()
    if not tokens or not tokens[0].startswith("/"):
        return "summarize", None

    command = tokens[0][1:].split("@", 1)[0].lower()
    first_arg = tokens[1].lower() if len(tokens) > 1 else ""

    if command in ("translate", "khmer", "english"):
        if command == "english" or first_arg in ("en", "english"):
            return "translate", "en"
        return "translate", "kh"
    if command in ("debug", "solve"):
        return "debug", None
    return "summarize", None


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle document uploads (.pdf, .docx, .pptx, .txt).
    Extracts text in-memory and executes summarization or translation based on caption.
    """
    if not update.effective_message or not update.effective_message.document:
        return

    doc = update.effective_message.document
    filename = doc.file_name or "document.txt"
    safe_filename = html.escape(filename)
    file_size = doc.file_size or 0
    caption = (update.effective_message.caption or "").strip()
    is_private = bool(update.effective_chat and update.effective_chat.type == "private")

    # 0. Skip media/archives/binaries: stay silent in groups instead of replying to every shared file
    if not document_parser.is_supported_upload(filename, doc.mime_type):
        if is_private:
            await safe_reply_text(
                update,
                context,
                f"⚠️ <b>Unsupported file type:</b> <code>{safe_filename}</code>\n"
                f"Supported: PDF, Word, PowerPoint, Excel, OpenDocument, Jupyter, CSV, and code/text files.",
            )
        return

    # 1. Validate file size
    if file_size > settings.MAX_FILE_SIZE_BYTES:
        mb = settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)
        await safe_reply_text(
            update,
            context,
            f"⚠️ <b>File too large:</b> File size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed limit ({mb} MB).",
        )
        return

    # 2. Check rate limit
    user_id = update.effective_user.id if update.effective_user else 0
    allowed, retry_after = rate_limiter.is_allowed(user_id)
    if not allowed:
        await safe_reply_text(
            update,
            context,
            f"⏳ <i>Rate limit reached. Please wait {retry_after} seconds before analyzing another document.</i>",
        )
        return

    course = await resolve_course(update)
    status_msg = await update.effective_message.reply_text(
        f"📥 <i>Downloading and parsing <b>{safe_filename}</b> in-memory...</i>",
        parse_mode="HTML",
        message_thread_id=get_thread_id(update.effective_message),
    )

    try:
        await send_typing_action(update, context, ChatAction.UPLOAD_DOCUMENT)

        # 3. Download in-memory
        tg_file = await context.bot.get_file(doc.file_id)
        buffer = io.BytesIO()
        await tg_file.download_to_memory(buffer)
        file_bytes = buffer.getvalue()

        # 4. Extract text in-memory on a worker thread (parsing large PDFs would block the event loop)
        extracted_text, metadata = await asyncio.to_thread(
            document_parser.extract_text, file_bytes, filename
        )

        await status_msg.edit_text(
            f"🧠 <i>Analyzing content with domain expertise: {course.icon} <b>{course.name}</b>...</i>",
            parse_mode="HTML",
        )
        await send_typing_action(update, context, ChatAction.TYPING)

        # 5. Determine action: Summarize vs Translate vs Debug
        action, target_lang = parse_caption_action(caption)

        if action == "translate" and target_lang == "kh":
            result = await llm_engine.translate_text(extracted_text, target_lang="kh")
            header = (
                f"🇰🇭 <b>Document Translation (Academic Khmer)</b>\n"
                f"📄 <b>File:</b> <code>{safe_filename}</code> | <i>{course.icon} {course.name}</i>\n\n"
            )
        elif action == "translate":
            result = await llm_engine.translate_text(extracted_text, target_lang="en")
            header = (
                f"🇬🇧 <b>Document Translation (Academic English)</b>\n"
                f"📄 <b>File:</b> <code>{safe_filename}</code> | <i>{course.icon} {course.name}</i>\n\n"
            )
        elif action == "debug":
            result = await llm_engine.debug_code_or_problem(extracted_text, course.key)
            header = (
                f"🛠️ <b>Document Code & Trace Analysis</b>\n"
                f"📄 <b>File:</b> <code>{safe_filename}</code> | <i>{course.icon} {course.name}</i>\n\n"
            )
        else:
            # Default: In-depth academic lecture & slide digest
            result = await llm_engine.summarize_document(extracted_text, course.key, metadata)
            if "total_pages" in metadata:
                meta_str = f"Pages: {metadata['total_pages']}"
            elif "total_slides" in metadata:
                meta_str = f"Slides: {metadata['total_slides']}"
            elif "sheet_count" in metadata:
                sheets_preview = html.escape(", ".join(metadata.get('sheet_names', [])[:3]))
                meta_str = f"Excel Sheets: {metadata['sheet_count']} [{sheets_preview}]"
            elif "code_cells" in metadata:
                meta_str = f"Jupyter Notebook: {metadata['code_cells']} Code / {metadata.get('markdown_cells', 0)} Markdown cells"
            elif "total_rows" in metadata:
                meta_str = f"Rows: {metadata['total_rows']}"
            else:
                meta_str = f"Type: {metadata.get('type', 'Doc')}"

            header = (
                f"📑 <b>Academic Lecture & Handout Digest</b>\n"
                f"📚 <b>Subject:</b> {course.icon} <b>{course.name}</b> (<code>{course.code}</code>)\n"
                f"📄 <b>Document:</b> <code>{safe_filename}</code> ({meta_str})\n\n"
            )

        # Remove temporary status message
        try:
            await status_msg.delete()
        except Exception:
            pass

        full_output = f"{header}{result}"
        await safe_reply_text(update, context, full_output)

    except DocumentParseError as pe:
        logger.warning("Document parsing failed for %s: %s", filename, pe)
        await status_msg.edit_text(f"⚠️ <b>Document Parse Error:</b> {html.escape(str(pe))}", parse_mode="HTML")
    except Exception as e:
        logger.error("Failed to process document %s: %s", filename, e, exc_info=True)
        await status_msg.edit_text(f"❌ <b>Error processing document:</b> {html.escape(str(e))}", parse_mode="HTML")
