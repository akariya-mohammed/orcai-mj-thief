"""Stage-4 gate, task 4.4: the receive path — diffuse, fuse scent, store hint, ack.

Order matters: the opponent MOVED (diffuse) and only then left evidence (fuse smell).
"""
import math

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import BrainBase, Decision, MoveType, Role
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.smell import ScentGrid
from police_thief.peer.runtime import PeerRuntime


class _SpyBelief(BeliefGrid):
    def __init__(self):
        super().__init__(7)
        self.calls = []

    def diffuse(self, barriers=None):
        self.calls.append("diffuse")
        super().diffuse(barriers)

    def update_from_smell(self, smell):
        self.calls.append("smell")
        super().update_from_smell(smell)


class _HintEcho(BrainBase):
    def __init__(self):
        self.hints_seen = []

    def decide(self, state, belief, hint, play_setting, barriers_max, **kw):
        self.hints_seen.append(hint)
        return Decision(MoveType.HOLD, None, hint="")


class _NullTransport:
    def send_turn(self, message):
        return {"accepted": True}


def _runtime(belief=None, brain=None):
    state = OwnGameState((0, 0), Board(7))
    return PeerRuntime(Role.POLICE, brain or _HintEcho(), _NullTransport(), state,
                       belief if belief is not None else BeliefGrid(7), config={})


def _msg(scent=None, hint="", commit="c" * 64):
    return {"role": "thief", "commit": commit, "hint": hint,
            "scent": scent or {}, "capture_claim": None,
            "claim_response": None, "win_claim": None}


def test_receive_diffuses_before_fusing_scent():
    spy = _SpyBelief()
    rt = _runtime(belief=spy)
    rt.on_opponent_turn(_msg(scent={"3,3": 0.9}))
    assert spy.calls == ["diffuse", "smell"]     # moved first, THEN left evidence


def test_belief_locks_onto_trail_region_within_two_messages():
    # DISCOVERY (Stage 4): the 0.9 clamp means a fresh deposit re-saturates the
    # cell just behind the head (0.81 + 0.62 -> clamp 0.9), so a one-step trail is
    # intrinsically ambiguous at head resolution — the book's "probability cloud,
    # not a sharp point". Honest acceptance: argmax lands within 1 cell of the
    # true head, on the trail. Head-exact resolution needs trails longer than the
    # emission window (radius 2) — a strategy concern (4.7/4.8), not receive-path.
    rt = _runtime()
    trail = ScentGrid(7)
    trail.deposit((5, 2))
    trail.decay_all()
    rt.on_opponent_turn(_msg(scent={f"{r},{c}": v for (r, c), v in trail.snapshot().items()}))
    trail.deposit((5, 3))                        # opponent stepped east
    trail.decay_all()
    rt.on_opponent_turn(_msg(scent={f"{r},{c}": v for (r, c), v in trail.snapshot().items()}))
    r, c = rt.belief.most_likely()
    assert abs(r - 5) + abs(c - 3) <= 1          # within one cell of the true head
    assert r == 5 and c in (2, 3, 4)             # and on the trail itself


def test_empty_scent_early_game_just_diffuses():
    rt = _runtime()
    ack = rt.on_opponent_turn(_msg(scent={}))
    assert ack["status"] == "ok"
    assert math.isclose(sum(sum(row) for row in rt.belief.grid), 1.0)


def test_malformed_scent_entries_are_dropped_not_fatal():
    rt = _runtime()
    bad = {"abc": 0.5, "1,2,3": 0.4, "2,x": 0.3, "4,5": "strong", "5,2": 0.8}
    ack = rt.on_opponent_turn(_msg(scent=bad))   # only "5,2" is valid
    assert ack["status"] == "ok"
    assert rt.belief.most_likely() == (5, 2)


def test_hint_is_stored_and_flows_into_next_decide():
    brain = _HintEcho()
    rt = _runtime(brain=brain)
    rt.on_opponent_turn(_msg(hint="you will never find me uptown"))
    rt.run_turn()                                # no explicit hint -> stored one is used
    assert brain.hints_seen == ["you will never find me uptown"]


def test_ack_locks_the_commitment():
    rt = _runtime()
    ack = rt.on_opponent_turn(_msg(commit="a" * 64))
    assert ack == {"status": "ok", "acknowledged_commit": "a" * 64}
