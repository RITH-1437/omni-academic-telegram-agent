import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import aiosqlite

from config import settings
from database.models import Deadline, TopicBinding

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Asynchronous SQLite Database Manager using aiosqlite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def init_db(self) -> None:
        """Initialize database schema, tables, and performance indexes."""
        # Ensure parent directory exists
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")

            # Table for course deadlines & assignments
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS deadlines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    course_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    due_date TEXT NOT NULL,
                    created_by_user_id INTEGER NOT NULL,
                    created_by_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_completed INTEGER DEFAULT 0,
                    reminded_24h INTEGER DEFAULT 0,
                    reminded_6h INTEGER DEFAULT 0,
                    reminded_1h INTEGER DEFAULT 0
                );
                """
            )

            # Table for dynamic forum topic thread to course bindings
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_bindings (
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    course_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, thread_id)
                );
                """
            )

            # Performance indexes
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deadlines_due 
                ON deadlines (is_completed, due_date);
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deadlines_chat_thread 
                ON deadlines (chat_id, thread_id, is_completed);
                """
            )

            await db.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    # --------------------------------------------------------------------------
    # Deadline Operations
    # --------------------------------------------------------------------------

    async def add_deadline(
        self,
        chat_id: int,
        thread_id: Optional[int],
        course_key: str,
        title: str,
        description: Optional[str],
        due_date: datetime,
        created_by_user_id: int,
        created_by_name: str,
    ) -> Deadline:
        """Insert a new deadline into the database."""
        now = datetime.now(timezone.utc)
        # Store UTC only: reminder queries compare these ISO strings lexicographically
        due_iso = due_date.astimezone(timezone.utc).isoformat()
        now_iso = now.isoformat()

        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO deadlines (
                        chat_id, thread_id, course_key, title, description,
                        due_date, created_by_user_id, created_by_name, created_at,
                        is_completed, reminded_24h, reminded_6h, reminded_1h
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
                    """,
                    (
                        chat_id,
                        thread_id,
                        course_key,
                        title,
                        description,
                        due_iso,
                        created_by_user_id,
                        created_by_name,
                        now_iso,
                    ),
                )
                await db.commit()
                deadline_id = cursor.lastrowid

        return Deadline(
            id=deadline_id,
            chat_id=chat_id,
            thread_id=thread_id,
            course_key=course_key,
            title=title,
            description=description,
            due_date=due_date,
            created_by_user_id=created_by_user_id,
            created_by_name=created_by_name,
            created_at=now,
            is_completed=False,
            reminded_24h=False,
            reminded_6h=False,
            reminded_1h=False,
        )

    async def get_deadline_by_id(self, deadline_id: int) -> Optional[Deadline]:
        """Fetch a specific deadline by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM deadlines WHERE id = ?", (deadline_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return self._row_to_deadline(row)

    async def get_upcoming_deadlines(
        self,
        chat_id: int,
        thread_id: Optional[int] = None,
        limit: int = 15,
    ) -> List[Deadline]:
        """Fetch upcoming uncompleted deadlines for a specific topic thread or entire supergroup."""
        query = """
            SELECT * FROM deadlines
            WHERE chat_id = ? AND is_completed = 0
        """
        params: List[object] = [chat_id]

        # If thread_id is specified and not general, filter by thread
        if thread_id is not None and thread_id > 1:
            query += " AND thread_id = ?"
            params.append(thread_id)

        query += " ORDER BY due_date ASC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_deadline(row) for row in rows]

    async def get_pending_reminders(self, now: datetime) -> List[Deadline]:
        """Fetch uncompleted deadlines needing a 24h, 6h, or 1h reminder."""
        now_iso = now.isoformat()
        query = """
            SELECT * FROM deadlines
            WHERE is_completed = 0 AND due_date >= ?
            AND (reminded_24h = 0 OR reminded_6h = 0 OR reminded_1h = 0)
            ORDER BY due_date ASC
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (now_iso,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_deadline(row) for row in rows]

    async def mark_reminder_sent(self, deadline_id: int, stage: str) -> None:
        """Mark a specific reminder stage as sent (e.g. '24h', '6h', '1h')."""
        column_map = {
            "24h": "reminded_24h",
            "6h": "reminded_6h",
            "1h": "reminded_1h",
        }
        column = column_map.get(stage)
        if not column:
            return

        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    f"UPDATE deadlines SET {column} = 1 WHERE id = ?",
                    (deadline_id,),
                )
                await db.commit()

    async def mark_deadline_completed(self, deadline_id: int) -> bool:
        """Mark a deadline as completed."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "UPDATE deadlines SET is_completed = 1 WHERE id = ?",
                    (deadline_id,),
                )
                await db.commit()
                return cursor.rowcount > 0

    async def delete_deadline(self, deadline_id: int) -> bool:
        """Permanently delete a deadline."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM deadlines WHERE id = ?",
                    (deadline_id,),
                )
                await db.commit()
                return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Dynamic Topic Binding Operations
    # --------------------------------------------------------------------------

    async def bind_topic(self, chat_id: int, thread_id: int, course_key: str) -> None:
        """Bind a forum thread ID to a specific course key."""
        now_iso = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO topic_bindings (chat_id, thread_id, course_key, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id, thread_id) DO UPDATE SET
                        course_key = excluded.course_key,
                        created_at = excluded.created_at
                    """,
                    (chat_id, thread_id, course_key, now_iso),
                )
                await db.commit()
        logger.info("Bound chat %s thread %s to course %s", chat_id, thread_id, course_key)

    async def get_topic_binding(self, chat_id: int, thread_id: int) -> Optional[str]:
        """Retrieve dynamic course key for a given chat and thread ID."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT course_key FROM topic_bindings WHERE chat_id = ? AND thread_id = ?",
                (chat_id, thread_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_all_topic_bindings(self, chat_id: int) -> Dict[int, str]:
        """Retrieve all dynamic thread mappings for a chat."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT thread_id, course_key FROM topic_bindings WHERE chat_id = ?",
                (chat_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return {row[0]: row[1] for row in rows}

    # --------------------------------------------------------------------------
    # Helper Serialization
    # --------------------------------------------------------------------------

    @staticmethod
    def _row_to_deadline(row: aiosqlite.Row) -> Deadline:
        return Deadline(
            id=row["id"],
            chat_id=row["chat_id"],
            thread_id=row["thread_id"],
            course_key=row["course_key"],
            title=row["title"],
            description=row["description"],
            due_date=datetime.fromisoformat(row["due_date"]),
            created_by_user_id=row["created_by_user_id"],
            created_by_name=row["created_by_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_completed=bool(row["is_completed"]),
            reminded_24h=bool(row["reminded_24h"]),
            reminded_6h=bool(row["reminded_6h"]),
            reminded_1h=bool(row["reminded_1h"]),
        )


db_manager = DatabaseManager(settings.DATABASE_PATH)
