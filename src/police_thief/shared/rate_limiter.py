"""RateLimiter — sliding-window limiter (Rule 28; reference shared/rate_limiter.py).

Blocks/queues when the window is full, so legitimate reports are delayed, not
dropped. seconds_until_slot() lets a caller sleep the EXACT remaining time once
instead of polling (debt D8). Injectable clock => fully testable without sleeping.
"""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Sliding-window limiter: refuses when the window is full (caller paces itself)."""

    WINDOW_SECONDS = 60.0

    def __init__(self, max_in_window: int, clock=time.monotonic) -> None:
        self.max_in_window = max_in_window
        self.clock = clock
        self._hits: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._hits and now - self._hits[0] >= self.WINDOW_SECONDS:
            self._hits.popleft()

    def try_acquire(self) -> bool:
        """Record and allow if the window has room, else refuse (caller waits)."""
        now = self.clock()
        self._prune(now)
        if len(self._hits) < self.max_in_window:
            self._hits.append(now)
            return True
        return False

    def seconds_until_slot(self) -> float:
        """0.0 if a slot is free now, else the exact wait until the oldest hit expires."""
        now = self.clock()
        self._prune(now)
        if len(self._hits) < self.max_in_window:
            return 0.0
        return max(0.0, self._hits[0] + self.WINDOW_SECONDS - now)
