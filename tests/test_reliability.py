"""Task 5.5: deadline tracking + watchdog + the TECHNICAL_LOSS pathway (Rules 6-7)."""
import json

from police_thief.domain.state_machine import GamePhaseMachine
from police_thief.peer.watchdog import DeadlineTracker, Watchdog
from police_thief.shared.config import Config
from police_thief.peer.runner import PeerProcess


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_deadline_tracker_beats_and_expires():
    clock = _Clock()
    t = DeadlineTracker(timeout_sec=30, clock=clock)
    assert not t.expired()
    clock.now += 29
    assert not t.expired()
    t.beat()                                   # a response arrived: window resets
    clock.now += 29
    assert not t.expired()
    clock.now += 2
    assert t.expired()


def test_watchdog_fires_once_on_freeze():
    clock = _Clock()
    fired = []
    w = Watchdog(timeout_sec=60, on_freeze=lambda: fired.append(1), clock=clock)
    w.check_once()
    assert fired == []
    clock.now += 61                            # main loop stopped beating
    w.check_once()
    w.check_once()                             # must not fire twice
    assert fired == [1]
    w.beat()                                   # recovery resets the fuse
    clock.now += 30
    w.check_once()
    assert fired == [1]


def test_waiting_phase_may_transition_to_technical_loss():
    # A silent opponent strands us in WAITING_FOR_OPPONENT — that IS a
    # communication phase, so the error edge must be legal (book Fig. 11).
    m = GamePhaseMachine()
    assert m.transition("TECHNICAL_LOSS") == "TECHNICAL_LOSS"


SHARED = {
    "board_and_agents": {"grid_size": 7, "thief_start": [3, 3], "cop_start": [0, 0]},
    "movement_and_barriers": {"max_barriers": 14, "max_moves": 35, "survival_threshold": 35},
    "pheromones": {"pheromone_center_intensity": 0.9, "pheromone_decay": 0.10,
                   "pheromone_grid_size": 5},
}


def test_runner_timeout_declares_technical_loss_and_persists(tmp_path):
    p = PeerProcess("police", Config(SHARED, {"game": {"group_id": "team-x"}}))
    p._technical_loss("opponent silent", out_dir=tmp_path)
    assert p.runtime.phases.state == "TECHNICAL_LOSS"
    saved = json.loads((tmp_path / "technical_loss_police.json").read_text())
    assert saved["role"] == "police" and saved["reason"] == "opponent silent"
    assert "records" in saved and "position" in saved
