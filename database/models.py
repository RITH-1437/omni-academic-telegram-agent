from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Deadline:
    id: int
    chat_id: int
    thread_id: Optional[int]
    course_key: str
    title: str
    description: Optional[str]
    due_date: datetime
    created_by_user_id: int
    created_by_name: str
    created_at: datetime
    is_completed: bool = False
    reminded_24h: bool = False
    reminded_6h: bool = False
    reminded_1h: bool = False


@dataclass
class TopicBinding:
    chat_id: int
    thread_id: int
    course_key: str
    created_at: datetime
