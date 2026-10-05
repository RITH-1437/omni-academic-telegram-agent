import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from telegram.error import BadRequest

from database.db import DatabaseManager
from handlers.document_handlers import parse_caption_action
from services import reminder_service
from services.date_parser import parse_due_command_text
from services.document_parser import DocumentParseError, document_parser
from utils.telegram_helpers import get_reply_target, get_thread_id, markdown_to_telegram_html


class TestHtmlFormatting(unittest.TestCase):
    def test_existing_entities_not_double_escaped(self):
        out = markdown_to_telegram_html("<code>/due &lt;date&gt;</code> by Tom &amp; Jerry & co")
        self.assertEqual(out, "<code>/due &lt;date&gt;</code> by Tom &amp; Jerry &amp; co")

    def test_raw_angle_brackets_still_escaped(self):
        out = markdown_to_telegram_html("if a < b and c > d")
        self.assertIn("a &lt; b and c &gt; d", out)

    def test_blockquote_converted(self):
        self.assertEqual(markdown_to_telegram_html("> quoted line"), "<blockquote>quoted line</blockquote>")


class TestThreadHelpers(unittest.TestCase):
    def test_reply_chain_thread_ignored_outside_forums(self):
        msg = SimpleNamespace(is_topic_message=False, message_thread_id=555)
        self.assertIsNone(get_thread_id(msg))

    def test_forum_topic_thread_used(self):
        msg = SimpleNamespace(is_topic_message=True, message_thread_id=7)
        self.assertEqual(get_thread_id(msg), 7)

    def test_topic_creation_message_is_not_a_reply(self):
        topic_root = SimpleNamespace(forum_topic_created=object(), text=None, caption=None)
        msg = SimpleNamespace(reply_to_message=topic_root)
        self.assertIsNone(get_reply_target(msg))

    def test_real_reply_is_returned(self):
        target = SimpleNamespace(forum_topic_created=None, text="print(x)", caption=None)
        msg = SimpleNamespace(reply_to_message=target)
        self.assertIs(get_reply_target(msg), target)


class TestDateParser(unittest.TestCase):
    def _local_hm(self, dt):
        local = dt.astimezone(timezone(timedelta(hours=7)))
        return local.hour, local.minute

    def test_weekday_without_time_defaults_to_end_of_day(self):
        for text in ("thursday Lab report", "march 3 Midterm"):
            dt, _ = parse_due_command_text(text)
            self.assertEqual(self._local_hm(dt), (23, 59), text)

    def test_explicit_time_kept(self):
        dt, desc = parse_due_command_text("friday 18:00 Lab")
        self.assertEqual(self._local_hm(dt), (18, 0))
        self.assertEqual(desc, "Lab")

    def test_next_weekday_parsed(self):
        dt, desc = parse_due_command_text("next monday Essay draft")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.astimezone(timezone(timedelta(hours=7))).weekday(), 0)
        self.assertEqual(desc, "Essay draft")


class TestDocumentParser(unittest.TestCase):
    def test_binary_files_rejected(self):
        with self.assertRaises(DocumentParseError):
            document_parser.extract_text(b"PK\x03\x04\x00\x00binary\x00" * 10, "archive.zip")
        with self.assertRaises(DocumentParseError):
            document_parser.extract_text(b"\x7fELF\x00\x01\x02" * 10, "a.out")

    def test_unknown_text_extension_accepted(self):
        text, _ = document_parser.extract_text(b"all:\n\tgcc main.c\n", "Makefile")
        self.assertIn("gcc", text)

    def test_upload_precheck(self):
        self.assertFalse(document_parser.is_supported_upload("photo.jpg", "image/jpeg"))
        self.assertFalse(document_parser.is_supported_upload("scan", "image/png"))
        self.assertTrue(document_parser.is_supported_upload("lecture.pdf", "application/pdf"))
        self.assertTrue(document_parser.is_supported_upload("Dockerfile", None))

    def test_notebook_with_bom(self):
        nb = json.dumps({"cells": [{"cell_type": "code", "source": ["print(1)"], "outputs": []}]})
        text, meta = document_parser.extract_text(b"\xef\xbb\xbf" + nb.encode(), "nb.ipynb")
        self.assertEqual(meta["code_cells"], 1)

    def test_markup_entities_unescaped(self):
        text, _ = document_parser.extract_text(b"<p>R&amp;D &lt;3</p>", "page.html")
        self.assertEqual(text, "R&D <3")


class TestCaptionParsing(unittest.TestCase):
    def test_caption_actions(self):
        self.assertEqual(parse_caption_action(""), ("summarize", None))
        self.assertEqual(parse_caption_action("Week 3 slides"), ("summarize", None))
        self.assertEqual(parse_caption_action("/translate"), ("translate", "kh"))
        self.assertEqual(parse_caption_action("/translate the content please"), ("translate", "kh"))
        self.assertEqual(parse_caption_action("/translate en"), ("translate", "en"))
        self.assertEqual(parse_caption_action("/translate@Year5Bot english"), ("translate", "en"))
        self.assertEqual(parse_caption_action("/debug"), ("debug", None))


class _FakeBot:
    def __init__(self, fail_thread=False):
        self.sent = []
        self.fail_thread = fail_thread

    async def send_message(self, **kwargs):
        if self.fail_thread and kwargs.get("message_thread_id"):
            raise BadRequest("Message thread not found")
        self.sent.append(kwargs)


class TestReminderService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, "test.db"))
        await self.db.init_db()
        self.patcher = mock.patch.object(reminder_service, "db_manager", self.db)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        self.tmpdir.cleanup()

    async def _add(self, minutes_from_now, title="Lab <4> & report", thread_id=7):
        return await self.db.add_deadline(
            chat_id=-100123,
            thread_id=thread_id,
            course_key="AI",
            title=title,
            description=title,
            due_date=datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now),
            created_by_user_id=1,
            created_by_name="Tom & Jerry",
        )

    async def test_late_deadline_gets_single_reminder_with_escaped_html(self):
        await self._add(30)
        bot = _FakeBot()
        ctx = SimpleNamespace(bot=bot)

        await reminder_service.deadline_checker_job(ctx)
        await reminder_service.deadline_checker_job(ctx)
        await reminder_service.deadline_checker_job(ctx)

        self.assertEqual(len(bot.sent), 1, "1h alert must not be followed by 6h/24h notices")
        self.assertIn("CRITICAL", bot.sent[0]["text"])
        self.assertIn("Lab &lt;4&gt; &amp; report", bot.sent[0]["text"])
        self.assertIn("Tom &amp; Jerry", bot.sent[0]["text"])

    async def test_missing_thread_falls_back_to_main_chat(self):
        deadline = await self._add(120)
        bot = _FakeBot(fail_thread=True)

        await reminder_service.deadline_checker_job(SimpleNamespace(bot=bot))

        self.assertEqual(len(bot.sent), 1)
        self.assertNotIn("message_thread_id", bot.sent[0])
        stored = await self.db.get_deadline_by_id(deadline.id)
        self.assertTrue(stored.reminded_6h and stored.reminded_24h)


if __name__ == "__main__":
    unittest.main()
