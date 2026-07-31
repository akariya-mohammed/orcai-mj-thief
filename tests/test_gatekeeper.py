"""Task 7.2 (hardening): computed-sleep pacing (no busy-wait), DOS lock, call log."""
import pytest

from police_thief.exceptions import GatekeeperLocked
from police_thief.shared.gatekeeper import ApiGatekeeper
from police_thief.shared.rate_limiter import RateLimiter


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_reports_seconds_until_slot():
    clock = _Clock()
    limiter = RateLimiter(max_in_window=1, clock=clock)
    assert limiter.seconds_until_slot() == 0.0
    assert limiter.try_acquire()
    assert limiter.seconds_until_slot() == pytest.approx(60.0)
    clock.now += 45
    assert limiter.seconds_until_slot() == pytest.approx(15.0)


def test_execute_sleeps_once_computed_not_polling():
    clock = _Clock()
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        clock.now += seconds                       # sleeping advances the fake clock

    gk = ApiGatekeeper(requests_per_minute=1, queue_depth=10,
                       clock=clock, sleeper=sleeper)
    assert gk.execute(lambda: "a") == "a"
    assert gk.execute(lambda: "b") == "b"          # window full: one computed sleep
    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(60.0)


def test_dos_burst_locks_the_pipe():
    clock = _Clock()
    gk = ApiGatekeeper(requests_per_minute=2, queue_depth=100,
                       clock=clock, sleeper=lambda s: None, dos_factor=3)
    with pytest.raises(GatekeeperLocked):
        for _ in range(20):                        # runaway loop: >3x rpm attempts
            gk.execute(lambda: "x")
    with pytest.raises(GatekeeperLocked):          # stays locked — protect the account
        gk.execute(lambda: "y")


def test_retry_then_success_and_call_log():
    clock = _Clock()
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    gk = ApiGatekeeper(requests_per_minute=30, queue_depth=10,
                       clock=clock, sleeper=lambda s: None)
    assert gk.execute(flaky, label="send_report") == "ok"
    assert attempts["n"] == 3
    assert gk.calls[-1]["label"] == "send_report" and gk.calls[-1]["ok"] is True


def test_permanent_failure_propagates_after_retries():
    gk = ApiGatekeeper(requests_per_minute=30, queue_depth=10,
                       clock=_Clock(), sleeper=lambda s: None)
    with pytest.raises(RuntimeError):
        gk.execute(lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
                   max_retries=2)
    assert gk.calls[-1]["ok"] is False
