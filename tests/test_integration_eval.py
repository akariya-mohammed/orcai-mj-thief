"""Task 4.11 — Stage-4 integration gate: FULL production path, scent-only.

Two real PeerRuntimes over a loopback transport (run_turn -> message ->
on_opponent_turn): decaying scent, belief fusion, template hints, lie
detection, forced-capture search. NO perfect-information shortcut anywhere.
Plan gate: scent-only cop captures the blind thief in >=60% of the batch.
"""
from police_thief.sdk.localsim import run_scent_match, run_batch


def test_scent_only_capture_from_standard_start():
    outcome = run_scent_match((0, 0), (3, 3), seed=1)
    assert outcome.result == "capture", outcome
    assert outcome.steps <= 35


def test_scent_only_batch_meets_capture_gate():
    stats = run_batch(starts=[(0, 0), (0, 6), (6, 0), (6, 6), (0, 3), (3, 0)],
                      seeds=(1, 2, 3))
    assert stats.games == 18
    assert stats.capture_rate >= 0.60, stats
    assert stats.avg_steps <= 35


def test_lie_detection_fires_against_a_chatty_opponent():
    # Our own peers are deliberately silent (P1-3: a parseable hint is free
    # localization for the opponent), so the detector is exercised against a
    # CHATTY opponent — which is what a league team will actually be.
    stats = run_batch(starts=[(0, 0), (6, 6)], seeds=(1, 2, 3), chatty_thief=True)
    assert stats.lies_caught + stats.truths_confirmed > 0


def test_our_peers_stay_silent_by_default():
    # Zero-information doctrine: nothing parseable leaves our thief unprompted.
    stats = run_batch(starts=[(0, 0)], seeds=(1, 2))
    assert stats.lies_caught == 0 and stats.truths_confirmed == 0
