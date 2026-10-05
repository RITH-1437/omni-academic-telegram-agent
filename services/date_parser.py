import re
from datetime import datetime, time, timezone
from typing import Optional, Tuple
import dateparser
import pytz

from config import settings

# Detects an explicit time of day or a sub-day offset ("23:59", "5pm", "noon", "in 2 hours")
EXPLICIT_TIME_PATTERN = re.compile(
    r"\d:\d|\d\s*(?:am|pm)\b|\b(?:noon|midnight|now)\b|\b(?:hours?|hrs?|minutes?|mins?)\b|\b\d{1,2}h\d{0,2}\b",
    re.IGNORECASE,
)

# dateparser cannot parse "next friday" / "this friday"; the bare weekday with
# PREFER_DATES_FROM=future resolves to the same upcoming day
RELATIVE_WEEKDAY_PATTERN = re.compile(
    r"\b(?:next|this|coming)\s+(?=(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b)",
    re.IGNORECASE,
)


def parse_due_command_text(raw_args: str) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse a deadline command string (e.g. '2026-10-25 23:59 Final Project Submission')
    into (due_datetime, description).

    Tries candidate date prefixes of length 1, 2, 3, or 4 tokens to reliably extract
    both simple dates ('2026-10-25'), combined date-times ('2026-10-25 23:59'),
    and natural language phrases ('tomorrow 5pm', 'in 3 days', 'next friday 18:00').
    """
    raw_args = raw_args.strip()
    if not raw_args:
        return None, None

    tokens = raw_args.split()
    if not tokens:
        return None, None

    tz_str = settings.TIMEZONE
    try:
        local_tz = pytz.timezone(tz_str)
    except Exception:
        local_tz = pytz.UTC

    dateparser_settings = {
        "TIMEZONE": tz_str,
        "TO_TIMEZONE": "UTC",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
    }

    # Try matching date prefix from longest candidate (4 tokens) down to 1 token
    max_prefix_len = min(4, len(tokens) - 1)
    if max_prefix_len < 1:
        max_prefix_len = 1

    best_dt: Optional[datetime] = None
    best_split_index: int = 1

    for prefix_len in range(max_prefix_len, 0, -1):
        candidate_date_str = " ".join(tokens[:prefix_len])
        normalized_candidate = RELATIVE_WEEKDAY_PATTERN.sub("", candidate_date_str)
        parsed = dateparser.parse(normalized_candidate, settings=dateparser_settings)
        if parsed:
            # If the user only gave a date without an explicit time, default to 23:59 local time
            has_time = bool(EXPLICIT_TIME_PATTERN.search(candidate_date_str))
            if not has_time:
                # Localize to end of that day
                local_dt = parsed.astimezone(local_tz)
                local_dt = local_dt.replace(hour=23, minute=59, second=0, microsecond=0)
                parsed = local_dt.astimezone(timezone.utc)

            best_dt = parsed
            best_split_index = prefix_len
            break

    if not best_dt:
        return None, None

    description = " ".join(tokens[best_split_index:]).strip()
    if not description:
        description = "Course Assignment / Submission"

    return best_dt, description


def format_deadline_datetime(dt: datetime, tz_str: str = settings.TIMEZONE) -> str:
    """Format UTC datetime into user-friendly localized string."""
    try:
        local_tz = pytz.timezone(tz_str)
        local_dt = dt.astimezone(local_tz)
    except Exception:
        local_dt = dt

    return local_dt.strftime("%A, %d %b %Y at %I:%M %p (%Z)")
