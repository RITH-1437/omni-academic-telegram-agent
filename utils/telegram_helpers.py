import asyncio
import html
import logging
import re
from typing import List, Optional, Tuple
from telegram import Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Telegram's absolute maximum text length per message
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
# Target safe chunk size allowing overhead for auto-closed/re-opened tags
SAFE_CHUNK_SIZE = 3600

# Regex matching valid Telegram HTML tags
TELEGRAM_VALID_TAG_PATTERN = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|blockquote|tg-spoiler)(?:\s+[^>]*)?>|"
    r'<a\s+href="[^"]*">|</a>|'
    r'<span\s+class="tg-spoiler">|</span>',
    re.IGNORECASE,
)

# Entities Telegram's HTML parser understands; already-escaped input must not be escaped twice
DOUBLE_ESCAPED_ENTITY_PATTERN = re.compile(r"&amp;(lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);")


def get_thread_id(message: Optional[Message]) -> Optional[int]:
    """
    Return the forum topic thread ID of a message, or None.
    In non-forum supergroups message_thread_id is the root of a reply chain, which
    Telegram rejects as a send target ("message thread not found").
    """
    if message is None or not message.is_topic_message:
        return None
    return message.message_thread_id


def get_reply_target(message: Optional[Message]) -> Optional[Message]:
    """
    Return the message the user actually replied to, or None.
    Inside forum topics, non-reply messages carry the topic's creation service
    message as reply_to_message, which must not be treated as a real reply.
    """
    if message is None or message.reply_to_message is None:
        return None
    reply = message.reply_to_message
    if reply.forum_topic_created is not None:
        return None
    return reply


def format_markdown_table_to_ascii(table_text: str) -> str:
    """Convert a Markdown table into an aligned plain text table for <pre> blocks."""
    lines = [line.strip() for line in table_text.strip().splitlines() if line.strip()]
    if not lines:
        return ""

    rows: List[List[str]] = []
    for line in lines:
        # Ignore horizontal separator lines (e.g. |---|---|)
        if re.match(r"^\|?\s*[-:]+[-| :]*\|?$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells:
            rows.append(cells)

    if not rows:
        return table_text

    # Compute column widths
    max_cols = max(len(r) for r in rows)
    col_widths = [0] * max_cols
    for row in rows:
        for i in range(max_cols):
            val = row[i] if i < len(row) else ""
            col_widths[i] = max(col_widths[i], len(val))

    formatted_lines = []
    for idx, row in enumerate(rows):
        padded_cells = []
        for i in range(max_cols):
            val = row[i] if i < len(row) else ""
            padded_cells.append(val.ljust(col_widths[i]))
        formatted_lines.append(" | ".join(padded_cells))
        if idx == 0 and len(rows) > 1:
            # Separator under header
            sep = "-+-".join(["-" * w for w in col_widths])
            formatted_lines.append(sep)

    return "\n".join(formatted_lines)


def markdown_to_telegram_html(text: str) -> str:
    """
    Intelligently convert Markdown and mixed HTML into Telegram-compliant HTML.
    - Preserves pre-existing valid Telegram HTML tags (<b>, <code>, <pre>, <i>, etc.)
    - Safely escapes raw HTML special chars (<, >, &) in student/LLM text
    - Converts Markdown headers, bold, italic, code, quotes, and math to Telegram HTML
    - Converts Markdown tables to aligned <pre> blocks
    """
    if not text:
        return ""

    # Strip reasoning/think tags output by some models (Qwen, DeepSeek)
    processed = re.sub(r"<(think|thought)>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # 1. Protect existing valid Telegram HTML tags
    valid_tags: List[str] = []

    def _preserve_valid_tag(match: re.Match) -> str:
        idx = len(valid_tags)
        valid_tags.append(match.group(0))
        return f"@@TG_SAVED_TAG_{idx}@@"

    processed = TELEGRAM_VALID_TAG_PATTERN.sub(_preserve_valid_tag, processed)

    # 2. Protect fenced code blocks (```language\ncode\n```)
    code_blocks: List[str] = []

    def _preserve_code_block(match: re.Match) -> str:
        lang = (match.group(1) or "").strip().lower()
        code = match.group(2)
        escaped_code = html.escape(code)
        idx = len(code_blocks)
        if lang:
            tag = f'<pre><code class="language-{html.escape(lang)}">{escaped_code}</code></pre>'
        else:
            tag = f"<pre><code>{escaped_code}</code></pre>"
        code_blocks.append(tag)
        return f"@@TG_CODE_BLOCK_{idx}@@"

    pattern_code_block = re.compile(r"```([a-zA-Z0-9_\-\+]*)\n(.*?)```", re.DOTALL)
    processed = pattern_code_block.sub(_preserve_code_block, processed)

    # 3. Protect inline code (`code`)
    inline_codes: List[str] = []

    def _preserve_inline_code(match: re.Match) -> str:
        code = match.group(1)
        escaped_code = html.escape(code)
        idx = len(inline_codes)
        inline_codes.append(f"<code>{escaped_code}</code>")
        return f"@@TG_INLINE_CODE_{idx}@@"

    pattern_inline_code = re.compile(r"`([^`\n]+)`")
    processed = pattern_inline_code.sub(_preserve_inline_code, processed)

    # 4. Protect and format Markdown tables (| col1 | col2 |)
    tables: List[str] = []

    def _preserve_table(match: re.Match) -> str:
        table_raw = match.group(0)
        formatted = format_markdown_table_to_ascii(table_raw)
        idx = len(tables)
        tables.append(f"<pre>{html.escape(formatted)}</pre>")
        return f"@@TG_TABLE_{idx}@@"

    pattern_table = re.compile(r"(?:^[ \t]*\|.+?\|[ \t]*$\n?){2,}", re.MULTILINE)
    processed = pattern_table.sub(_preserve_table, processed)

    # 5. Format LaTeX & Math expressions ($$formula$$ and $x$)
    def _preserve_display_math(match: re.Match) -> str:
        math_content = match.group(1).strip()
        idx = len(code_blocks)
        code_blocks.append(f"<pre><code>{html.escape(math_content)}</code></pre>")
        return f"@@TG_CODE_BLOCK_{idx}@@"

    processed = re.sub(r"\$\$([^$]+)\$\$", _preserve_display_math, processed)

    def _preserve_inline_math(match: re.Match) -> str:
        math_content = match.group(1).strip()
        idx = len(inline_codes)
        inline_codes.append(f"<code>{html.escape(math_content)}</code>")
        return f"@@TG_INLINE_CODE_{idx}@@"

    processed = re.sub(r"(?<!\$)\$([^$\n]+)\$(?!\$)", _preserve_inline_math, processed)

    # 6. Escape all remaining raw HTML special characters in the text
    processed = html.escape(processed)
    processed = DOUBLE_ESCAPED_ENTITY_PATTERN.sub(r"&\1;", processed)

    # 7. Convert Markdown Headings (# Title, ## Subtitle, ### Section)
    processed = re.sub(r"^###\s+(.+)$", r"<b>\1</b>", processed, flags=re.MULTILINE)
    processed = re.sub(r"^##\s+(.+)$", r"<b>\1</b>", processed, flags=re.MULTILINE)
    processed = re.sub(r"^#\s+(.+)$", r"<b>\1</b>", processed, flags=re.MULTILINE)

    # 8. Convert **bold** or __bold__ to <b>...</b>
    processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed)
    processed = re.sub(r"__(.+?)__", r"<b>\1</b>", processed)

    # 9. Convert *italic* or _italic_ to <i>...</i>
    processed = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", processed)
    processed = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", processed)

    # 10. Convert ~~strikethrough~~ to <s>...</s>
    processed = re.sub(r"~~(.+?)~~", r"<s>\1</s>", processed)

    # 11. Convert Blockquotes (> quote) to <blockquote>...</blockquote>
    def _format_quote(match: re.Match) -> str:
        quote_text = match.group(1).strip()
        return f"<blockquote>{quote_text}</blockquote>"

    # '>' was already escaped to '&gt;' in step 6
    processed = re.sub(r"^&gt;\s+(.+)$", _format_quote, processed, flags=re.MULTILINE)

    # 12. Convert Markdown Links [text](url) to <a href="url">text</a>
    processed = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r'<a href="\2">\1</a>', processed)

    # 13. Convert list markers (- or * or +) to clean bullet points (•)
    processed = re.sub(r"^[ \t]*[-*+][ \t]+", "• ", processed, flags=re.MULTILINE)

    # 14. Restore Tables
    for idx, table_html in enumerate(tables):
        processed = processed.replace(f"@@TG_TABLE_{idx}@@", table_html)

    # 15. Restore Inline Code
    for idx, code_html in enumerate(inline_codes):
        processed = processed.replace(f"@@TG_INLINE_CODE_{idx}@@", code_html)

    # 16. Restore Fenced Code Blocks
    for idx, block_html in enumerate(code_blocks):
        processed = processed.replace(f"@@TG_CODE_BLOCK_{idx}@@", block_html)

    # 17. Restore pre-existing valid Telegram HTML tags
    for idx, tag_html in enumerate(valid_tags):
        processed = processed.replace(f"@@TG_SAVED_TAG_{idx}@@", tag_html)

    return processed


def get_open_tags(html_chunk: str) -> List[str]:
    """Find currently unclosed HTML tags in a text chunk."""
    tag_pattern = re.compile(r"<(/)?([a-zA-Z0-9_\-]+)(?:\s+[^>]*)?>")
    open_tags: List[str] = []

    for match in tag_pattern.finditer(html_chunk):
        is_closing = bool(match.group(1))
        tag_name = match.group(2).lower()

        # Self-closing or void tags don't need tracking
        if tag_name in ("br", "hr", "img"):
            continue

        if is_closing:
            if open_tags and open_tags[-1] == tag_name:
                open_tags.pop()
            elif tag_name in open_tags:
                # Remove nearest matching
                open_tags.reverse()
                open_tags.remove(tag_name)
                open_tags.reverse()
        else:
            open_tags.append(tag_name)

    return open_tags


def chunk_message(text: str, max_chars: int = SAFE_CHUNK_SIZE) -> List[str]:
    """
    Split text into chunks smaller than max_chars.
    Guarantees tag balance across chunk boundaries: closes open tags at chunk end,
    and re-opens them at the start of the next chunk.
    """
    if len(text) <= max_chars:
        unclosed = get_open_tags(text)
        if unclosed:
            text = text + "".join([f"</{t}>" for t in reversed(unclosed)])
        return [text]

    raw_chunks: List[str] = []
    lines = text.split("\n")
    current_lines: List[str] = []
    current_length = 0

    for line in lines:
        line_len = len(line) + 1
        if current_length + line_len > max_chars:
            if current_lines:
                raw_chunks.append("\n".join(current_lines))
                current_lines = []
                current_length = 0

            # Single massive line handling
            if line_len > max_chars:
                for i in range(0, len(line), max_chars):
                    raw_chunks.append(line[i : i + max_chars])
                continue

        current_lines.append(line)
        current_length += line_len

    if current_lines:
        raw_chunks.append("\n".join(current_lines))

    # Balance HTML tags across chunks
    balanced_chunks: List[str] = []
    active_tags_from_previous: List[str] = []

    for chunk in raw_chunks:
        # Prepend opening tags from previous chunk
        prefix = "".join([f"<{t}>" for t in active_tags_from_previous])
        current_content = prefix + chunk

        # Determine tags left open at the end of this chunk
        unclosed = get_open_tags(current_content)

        # Append closing tags in reverse order
        suffix = "".join([f"</{t}>" for t in reversed(unclosed)])
        balanced_chunks.append(current_content + suffix)

        # Carry forward open tags to next chunk
        active_tags_from_previous = unclosed

    return balanced_chunks


async def safe_reply_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: Optional[str] = ParseMode.HTML,
    reply_to_message: bool = True,
) -> List[Message]:
    """
    Safely reply to the user's message in the current forum topic thread.
    - Handles HTML formatting conversion without double-escaping pre-existing tags.
    - Balances HTML tags across chunk boundaries.
    - Falls back to clean plain text if Telegram API raises BadRequest.
    """
    if not update.effective_message:
        return []

    target_chat_id = update.effective_chat.id
    target_thread_id = get_thread_id(update.effective_message)
    reply_to_id = update.effective_message.message_id if reply_to_message else None

    # Format text to clean Telegram HTML
    formatted_text = markdown_to_telegram_html(text) if parse_mode == ParseMode.HTML else text
    chunks = chunk_message(formatted_text)

    sent_messages: List[Message] = []

    for idx, chunk in enumerate(chunks):
        try:
            msg = await context.bot.send_message(
                chat_id=target_chat_id,
                message_thread_id=target_thread_id,
                text=chunk,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_id if idx == 0 else None,
                allow_sending_without_reply=True,
                disable_web_page_preview=True,
            )
            sent_messages.append(msg)
        except BadRequest as e:
            logger.warning(
                "Failed to send HTML formatted chunk (%d/%d): %s. Falling back to plain text.",
                idx + 1,
                len(chunks),
                e,
            )
            # Fallback: Strip HTML tags and send as clean plain text
            plain_chunk = html.unescape(re.sub(r"<[^>]+>", "", chunk))
            msg = await context.bot.send_message(
                chat_id=target_chat_id,
                message_thread_id=target_thread_id,
                text=plain_chunk,
                parse_mode=None,
                reply_to_message_id=reply_to_id if idx == 0 else None,
                allow_sending_without_reply=True,
                disable_web_page_preview=True,
            )
            sent_messages.append(msg)

        if len(chunks) > 1:
            await asyncio.sleep(0.08)

    return sent_messages


async def send_typing_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str = ChatAction.TYPING,
) -> None:
    """Send a chat action indicator (e.g. typing or uploading document) to the forum topic."""
    try:
        if update.effective_chat and update.effective_message:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=action,
                message_thread_id=get_thread_id(update.effective_message),
            )
    except Exception as e:
        logger.debug("Failed to send chat action: %s", e)
