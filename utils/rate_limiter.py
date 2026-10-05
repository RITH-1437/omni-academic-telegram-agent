import time
from collections import defaultdict
from typing import Dict, List, Tuple
from config import settings


class RateLimiter:
    """Sliding-window rate limiter per user."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._user_requests: Dict[int, List[float]] = defaultdict(list)
        self._admin_ids = set(settings.get_admin_ids())

    def is_allowed(self, user_id: int) -> Tuple[bool, int]:
        """
        Check if user is allowed to make another request.
        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        # Admins bypass rate limits
        if user_id in self._admin_ids:
            return True, 0

        now = time.time()
        cutoff = now - self.window_seconds
        timestamps = self._user_requests[user_id]

        # Prune timestamps older than window
        self._user_requests[user_id] = [ts for ts in timestamps if ts > cutoff]
        timestamps = self._user_requests[user_id]

        if len(timestamps) >= self.max_requests:
            oldest_ts = timestamps[0]
            retry_after = int(oldest_ts + self.window_seconds - now) + 1
            return False, max(retry_after, 1)

        self._user_requests[user_id].append(now)
        return True, 0


# Global singleton instance
rate_limiter = RateLimiter(
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)
