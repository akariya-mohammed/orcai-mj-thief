"""ApiGatekeeper — one guarded chokepoint for ALL outgoing calls (Rules 28-29, Ch. 9).

Every LLM / email / network call goes through execute(): sliding-window rate
limiting with a SINGLE computed sleep (no busy-wait — debt D8 closed), a DOS
detector that LOCKS the pipe on runaway bursts (fail fast, protect the account),
retry with backoff on transient errors, and a bounded call log for the audit.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, TypeVar

from police_thief.exceptions import GatekeeperLocked
from police_thief.shared.rate_limiter import RateLimiter

T = TypeVar("T")


class ApiGatekeeper:
    """Centralized API call manager: pace, guard, retry, log."""

    def __init__(self, requests_per_minute: int, queue_depth: int = 100,
                 clock=time.monotonic, sleeper: Callable[[float], None] = time.sleep,
                 dos_factor: int = 3) -> None:
        self.limiter = RateLimiter(max_in_window=requests_per_minute, clock=clock)
        self.clock = clock
        self.sleeper = sleeper
        self.queue_depth = queue_depth
        self.dos_threshold = dos_factor * requests_per_minute
        self._attempts: deque[float] = deque()      # ALL attempts, incl. paced ones
        self._locked = False
        self.calls: deque[dict] = deque(maxlen=1000)

    def _check_dos(self) -> None:
        now = self.clock()
        while self._attempts and now - self._attempts[0] >= RateLimiter.WINDOW_SECONDS:
            self._attempts.popleft()
        self._attempts.append(now)
        if len(self._attempts) > self.dos_threshold:
            self._locked = True
        if self._locked:
            raise GatekeeperLocked(
                f"outbound pipe locked: {len(self._attempts)} attempts/window "
                f"(threshold {self.dos_threshold}) — probable runaway loop")

    def execute(self, call: Callable[[], T], *, label: str = "",
                max_retries: int = 3, backoff_sec: float = 5.0) -> T:
        """Run `call` through the guard. Raises GatekeeperLocked on DOS lock;
        re-raises the last error after max_retries transient failures."""
        self._check_dos()
        wait = self.limiter.seconds_until_slot()
        if wait > 0:
            self.sleeper(wait)                      # one computed sleep, not a poll
        self.limiter.try_acquire()
        last: Exception | None = None
        for attempt in range(max_retries):
            try:
                result = call()
                self.calls.append({"label": label, "t": self.clock(), "ok": True})
                return result
            except Exception as exc:                # transient provider/network error
                last = exc
                if attempt < max_retries - 1:
                    self.sleeper(backoff_sec)
        self.calls.append({"label": label, "t": self.clock(), "ok": False,
                           "error": str(last)})
        raise last
