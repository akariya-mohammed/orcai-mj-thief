"""6.3: a live game ends by protocol consensus, not by running out of turns.

Rule 22 is the sharp edge here: a capture claim that turns out false is an
immediate disqualification with no appeal, so the cop may only ever claim in
good faith — when it genuinely believes it has landed on the thief.
"""
from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import BrainBase, Decision, Direction, MoveType, Role
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.protocol import TurnMessage
from police_thief.domain.termination import CAPTURE, SURVIVAL
from police_thief.peer.claims import answer_claims, good_faith_capture_claim
from police_thief.peer.runtime import PeerRuntime


class _Fixed(BrainBase):
    def __init__(self, d=Direction.S, t=MoveType.MOVE):
        self.d, self.t = d, t

    def decide(self, state, belief, hint, play_setting, barriers_max, **kw):
        return Decision(self.t, self.d, hint="")


class _Link:
    def __init__(self):
        self.sent = []

    def send_turn(self, m):
        self.sent.append(m)
        return {}


def _belief_on(cell):
    b = BeliefGrid(7)
    b.update_from_smell({cell: 5.0})
    return b


def _rt(role, brain=None, pos=(0, 0), belief=None):
    return PeerRuntime(role, brain or _Fixed(), _Link(), OwnGameState(pos, Board(7)),
                       belief or BeliefGrid(7), config={})


# ── Rule 22: good-faith claims only ──────────────────────────────────────────

def test_cop_claims_only_when_it_believes_it_landed_on_the_thief():
    assert good_faith_capture_claim(Role.POLICE, (3, 3), _belief_on((3, 3)),
                                    MoveType.MOVE) == [3, 3]


def test_cop_stays_silent_when_it_does_not_believe_it_captured():
    # The old behaviour claimed on EVERY move — ~19 false claims a match.
    assert good_faith_capture_claim(Role.POLICE, (3, 3), _belief_on((6, 6)),
                                    MoveType.MOVE) is None


def test_thief_never_claims_capture():
    assert good_faith_capture_claim(Role.THIEF, (3, 3), _belief_on((3, 3)),
                                    MoveType.MOVE) is None


def test_live_cop_does_not_spam_claims_across_a_match():
    cop = _rt(Role.POLICE, _Fixed(Direction.S), (0, 0), _belief_on((6, 6)))
    for _ in range(4):
        cop.run_turn()
    claims = [TurnMessage.from_dict(m).capture_claim for m in cop.transport.sent]
    assert all(c is None for c in claims), f"false capture claims sent: {claims}"


# ── consensus: capture ───────────────────────────────────────────────────────

def _msg(**over):
    base = {"role": "police", "commit": "a" * 64, "hint": "", "scent": {},
            "barrier": None, "capture_claim": None, "claim_response": None,
            "win_claim": None}
    base.update(over)
    return TurnMessage.from_dict(base)


def test_true_claim_is_confirmed_and_ends_the_game_for_the_thief():
    response, outcome = answer_claims(_msg(capture_claim=[3, 3]), (3, 3), step=6,
                                      threshold=35)
    assert response["confirmed"] is True
    assert outcome == {"type": CAPTURE, "winner": "police", "step": 6}


def test_false_claim_is_denied_and_play_continues():
    response, outcome = answer_claims(_msg(capture_claim=[3, 3]), (5, 5), step=6,
                                      threshold=35)
    assert response["confirmed"] is False and response["position"] == [5, 5]
    assert outcome is None


def test_confirmation_coming_back_ends_the_game_for_the_cop():
    reply = _msg(claim_response={"type": CAPTURE, "confirmed": True, "step": 6})
    _, outcome = answer_claims(reply, (3, 3), step=7, threshold=35)
    assert outcome["type"] == CAPTURE and outcome["winner"] == "police"


# ── consensus: survival ──────────────────────────────────────────────────────

def test_survival_claim_at_threshold_is_confirmed():
    response, outcome = answer_claims(_msg(win_claim={"type": SURVIVAL, "step": 35}),
                                      (6, 6), step=35, threshold=35)
    assert response["confirmed"] is True
    assert outcome == {"type": SURVIVAL, "winner": "thief", "step": 35}


def test_premature_survival_claim_is_refused():
    response, outcome = answer_claims(_msg(win_claim={"type": SURVIVAL, "step": 20}),
                                      (6, 6), step=20, threshold=35)
    assert response["confirmed"] is False and outcome is None


# ── the runtime actually stops ───────────────────────────────────────────────

def test_runtime_records_the_outcome_and_reports_terminal():
    thief = _rt(Role.THIEF, pos=(3, 3))
    assert thief.outcome is None and not thief.is_over
    thief.on_opponent_turn(_msg(capture_claim=[3, 3]).to_dict())
    assert thief.is_over and thief.outcome["type"] == CAPTURE


def test_denial_is_carried_back_on_the_next_message():
    thief = _rt(Role.THIEF, pos=(5, 5))
    thief.on_opponent_turn(_msg(capture_claim=[3, 3]).to_dict())
    thief.run_turn()
    carried = TurnMessage.from_dict(thief.transport.sent[-1]).claim_response
    assert carried["confirmed"] is False and carried["position"] == [5, 5]


def test_confirming_peer_answers_before_leaving_the_table():
    # Observed live: the cop confirmed survival at step 35 and exited without
    # telling the thief, who waited on a verdict that never came.
    from police_thief.peer.finish import deliver_verdict
    thief = _rt(Role.THIEF, pos=(3, 3))
    thief.on_opponent_turn(_msg(capture_claim=[3, 3]).to_dict())
    assert thief.is_over
    assert deliver_verdict(thief) is True
    answer = TurnMessage.from_dict(thief.transport.sent[-1]).claim_response
    assert answer["confirmed"] is True
    assert deliver_verdict(thief) is False          # nothing owed twice
