"""Reliability patterns (task 5.5, Book Ch. 8, Rules 6-7).

DeadlineTracker — guards a single wait: "a request past its deadline is a
FAILURE, not an invitation to keep waiting" (the book's iron rule).
Watchdog — guards the whole process: an independent monitor that notices the
main loop itself froze (crash inside the search, deadlocked send) and fires a
controlled-shutdown callback exactly once. Injectable clock => fully testable
without sleeping; `check_once` is the pure heart, the optional thread just
calls it periodically.
"""
from __future__ import annotations

import threading
import time


class DeadlineTracker:
    def __init__(self, timeout_sec: float, clock=time.monotonic) -> None:
        self.timeout = timeout_sec
        self.clock = clock
        self.last = clock()

    def beat(self) -> None:
        self.last = self.clock()

    def expired(self) -> bool:
        return self.clock() - self.last > self.timeout


class Watchdog:
    """Fires on_freeze exactly once if no beat arrives within timeout_sec."""

    def __init__(self, timeout_sec: float, on_freeze, clock=time.monotonic,
                 interval: float = 5.0) -> None:
        self._tracker = DeadlineTracker(timeout_sec, clock)
        self._on_freeze = on_freeze
        self._fired = False
        self._interval = interval
        self._stop = threading.Event()

    def beat(self) -> None:
        self._tracker.beat()
        self._fired = False                      # recovery re-arms the fuse

    def check_once(self) -> None:
        if not self._fired and self._tracker.expired():
            self._fired = True
            self._on_freeze()

    # ── optional background thread (live process only) ───────────────────────
    def start(self) -> None:
        def _loop() -> None:
            while not self._stop.wait(self._interval):
                self.check_once()
        threading.Thread(target=_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
