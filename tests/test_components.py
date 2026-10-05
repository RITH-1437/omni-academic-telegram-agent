import asyncio
import unittest
from datetime import datetime, timezone

from config.settings import COURSES, settings
from database.db import DatabaseManager
from services.date_parser import parse_due_command_text, format_deadline_datetime
from services.document_parser import document_parser
from utils.rate_limiter import RateLimiter
from utils.telegram_helpers import markdown_to_telegram_html, chunk_message


class TestBotComponents(unittest.IsolatedAsyncioTestCase):
    def test_markdown_to_html(self):
        md = "### Heading\nThis is **bold** and *italic* and `code`.\n```python\nprint('hello')\n```"
        html_out = markdown_to_telegram_html(md)
        self.assertIn("<b>Heading</b>", html_out)
        self.assertIn("<b>bold</b>", html_out)
        self.assertIn("<i>italic</i>", html_out)
        self.assertIn("<code>code</code>", html_out)
        self.assertIn('<pre><code class="language-python">', html_out)

    def test_preexisting_html_preservation(self):
        mixed = "📑 <b>Academic Lecture & Handout Digest</b>\n📚 <b>Subject:</b> (<code>CS501</code>)"
        html_out = markdown_to_telegram_html(mixed)
        self.assertNotIn("&lt;b&gt;", html_out)
        self.assertNotIn("&lt;code&gt;", html_out)
        self.assertIn("<b>Academic Lecture &amp; Handout Digest</b>", html_out)
        self.assertIn("<code>CS501</code>", html_out)

    def test_chunking(self):
        long_text = "Line\n" * 1000
        chunks = chunk_message(long_text, max_chars=100)
        self.assertTrue(len(chunks) > 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)

    def test_date_parser(self):
        dt, desc = parse_due_command_text("2026-10-25 23:59 Final Project Milestone 1")
        self.assertIsNotNone(dt)
        self.assertEqual(desc, "Final Project Milestone 1")

        dt2, desc2 = parse_due_command_text("tomorrow 5pm Homework 2")
        self.assertIsNotNone(dt2)
        self.assertEqual(desc2, "Homework 2")

    def test_rate_limiter(self):
        limiter = RateLimiter(max_requests=2, window_seconds=10)
        user_id = 999999
        allowed1, _ = limiter.is_allowed(user_id)
        allowed2, _ = limiter.is_allowed(user_id)
        allowed3, retry_after = limiter.is_allowed(user_id)

        self.assertTrue(allowed1)
        self.assertTrue(allowed2)
        self.assertFalse(allowed3)
        self.assertGreaterEqual(retry_after, 1)

    def test_document_parser_text(self):
        raw_text = b"# Cloud Computing Lab\nAWS VPC configuration steps..."
        extracted, meta = document_parser.extract_text(raw_text, "lab.txt")
        self.assertIn("Cloud Computing Lab", extracted)
        self.assertIn("Text", meta["type"])

    async def test_database_operations(self):
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db_path = tmp.name

        try:
            db = DatabaseManager(tmp_db_path)
            await db.init_db()

            # Test dynamic binding
            await db.bind_topic(chat_id=1001, thread_id=55, course_key="AI")
            bound_course = await db.get_topic_binding(chat_id=1001, thread_id=55)
            self.assertEqual(bound_course, "AI")

            # Test deadline insertion
            due_dt = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
            dl = await db.add_deadline(
                chat_id=1001,
                thread_id=55,
                course_key="AI",
                title="A* Lab",
                description="Implement A* with Manhattan distance",
                due_date=due_dt,
                created_by_user_id=123,
                created_by_name="Alice",
            )
            self.assertIsNotNone(dl.id)

            upcoming = await db.get_upcoming_deadlines(chat_id=1001, thread_id=55)
            self.assertEqual(len(upcoming), 1)
            self.assertEqual(upcoming[0].title, "A* Lab")

            completed = await db.mark_deadline_completed(dl.id)
            self.assertTrue(completed)

            upcoming_after = await db.get_upcoming_deadlines(chat_id=1001, thread_id=55)
            self.assertEqual(len(upcoming_after), 0)
        finally:
            if os.path.exists(tmp_db_path):
                os.remove(tmp_db_path)


if __name__ == "__main__":
    unittest.main()
