"""Rule 15: every barrier placement must be declared truthfully on the wire.

Without this the two peers' boards silently DIVERGE — the thief plans through
walls the cop has already built — and the match becomes incoherent. Local
simulation hides the bug by sharing one Board object; a real two-process game
does not.
"""
import pytest

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import (BrainBase, Decision, Direction, MoveType, Role)
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.protocol import TurnMessage
from police_thief.exceptions import ProtocolViolation
from police_thief.peer.runtime import PeerRuntime

GOOD_COMMIT = "a" * 64


class _Wall(BrainBase):
    """A cop that immediately walls the cell to its north."""
    def decide(self, state, belief, hint, play_setting, barriers_max, **kw):
        return Decision(MoveType.BARRIER, Direction.N, hint="")


class _Capture:
    def __init__(self):
        self.sent = []

    def send_turn(self, message):
        self.sent.append(message)
        return {}


def _rt(role, brain, pos, board=None):
    return PeerRuntime(role, brain, _Capture(), OwnGameState(pos, board or Board(7)),
                       BeliefGrid(7), config={})


def test_placing_a_barrier_declares_it_on_the_wire():
    cop = _rt(Role.POLICE, _Wall(), (3, 3))
    cop.run_turn()
    declared = TurnMessage.from_dict(cop.transport.sent[0]).barrier
    assert declared == [2, 3]                     # the cell it actually walled
    assert (2, 3) in cop.state.barriers


def test_opponent_applies_the_declared_barrier_to_its_own_board():
    thief = _rt(Role.THIEF, None, (3, 3))
    assert (2, 3) not in thief.state.barriers
    thief.on_opponent_turn({"role": "police", "commit": GOOD_COMMIT, "hint": "",
                            "scent": {}, "barrier": [2, 3]})
    assert (2, 3) in thief.state.barriers          # wall is now known to both


def test_two_independent_boards_converge_over_a_match():
    # The real defect: separate Board objects, as in live play.
    cop = _rt(Role.POLICE, _Wall(), (3, 3), Board(7))
    thief = _rt(Role.THIEF, None, (6, 6), Board(7))
    for _ in range(3):
        cop.run_turn()
        thief.on_opponent_turn(cop.transport.sent[-1])
    assert cop.state.barriers == thief.state.barriers
    assert len(cop.state.barriers) >= 1


def test_declared_barrier_beyond_quota_is_a_violation():
    board = Board(7, barriers={(0, c) for c in range(7)} | {(1, c) for c in range(7)})
    thief = _rt(Role.THIEF, None, (6, 6), board)
    assert len(board.barriers) == 14               # opponent's quota is already spent
    ack = thief.on_opponent_turn({"role": "police", "commit": GOOD_COMMIT, "hint": "",
                                  "scent": {}, "barrier": [3, 3]})
    assert ack["status"] == "rejected" and "quota" in ack["reason"].lower()
    assert (3, 3) not in thief.state.barriers      # refused, not applied


@pytest.mark.parametrize("bad", [[1], [1, 2, 3], ["a", "b"], [99, 0], "3,3", {}])
def test_malformed_barrier_field_is_a_named_violation(bad):
    with pytest.raises(ProtocolViolation):
        TurnMessage.from_dict({"role": "police", "commit": GOOD_COMMIT, "barrier": bad})


def test_absent_barrier_field_is_fine():
    assert TurnMessage.from_dict(
        {"role": "police", "commit": GOOD_COMMIT}).barrier is None
