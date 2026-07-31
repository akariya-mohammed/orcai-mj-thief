"""Stage-2 gate: protocol round-trip + a full legal phase cycle (Rules 3-5, 27)."""
from police_thief.domain.protocol import TurnMessage, build_turn_message
from police_thief.domain.board import Board
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.belief import BeliefGrid
from police_thief.domain.brains import BrainBase, Decision, Direction, MoveType, Role
from police_thief.peer.runtime import PeerRuntime


def test_turn_message_round_trip():
    # commit must be a real 64-hex digest: from_dict validates inbound envelopes
    # (P0 hardening), so a placeholder value is now correctly rejected.
    digest = "ab12" * 16
    msg = build_turn_message("thief", "heading downtown", {(3, 3): 0.9}, digest,
                             capture_claim=None)
    got = TurnMessage.from_dict(msg.to_dict())
    assert got.role == "thief"
    assert got.commit == digest
    assert got.hint == "heading downtown"
    assert got.scent[(3, 3)] == 0.9        # cell key survives JSON string encoding


class _FakeBrain(BrainBase):
    def decide(self, state, belief, hint, play_setting, barriers_max, **kw):
        return Decision(MoveType.MOVE, Direction.S, hint="heading downtown")


class _FakeTransport:
    def __init__(self):
        self.sent = None
        self.all_sent = []

    def send_turn(self, message: dict) -> dict:
        self.sent = message
        self.all_sent.append(message)
        return {"accepted": True}


class _RogueThiefBrain(BrainBase):
    """A misbehaving custom brain that tries the cop-only BARRIER action."""
    def decide(self, state, belief, hint, play_setting, barriers_max, **kw):
        return Decision(MoveType.BARRIER, Direction.N, hint="digging in")


def test_thief_barrier_degraded_to_hold():
    # Barrier placement is the cop's exclusive privilege (Book Ch. 3).
    state = OwnGameState((3, 3), Board(7))
    rt = PeerRuntime(Role.THIEF, _RogueThiefBrain(), _FakeTransport(), state,
                     BeliefGrid(7), config={})
    rt.run_turn()
    assert state.position == (3, 3)              # didn't move
    assert state.barriers == set()               # and placed nothing
    assert rt.records[0]["move"] == "HOLD"       # sealed record shows the degraded move


def test_peer_runtime_full_phase_cycle_and_decode():
    state = OwnGameState((3, 3), Board(7))
    transport = _FakeTransport()
    rt = PeerRuntime(Role.THIEF, _FakeBrain(), transport, state, BeliefGrid(7), config={})

    message = rt.run_turn(opponent_hint="")

    # cycled back to the start of the next turn through only legal transitions
    assert rt.phases.state == "WAITING_FOR_OPPONENT"
    # the move applied (south = row+1)
    assert state.position == (4, 3)
    # exactly one sealed record with a real SHA-256 commit
    assert len(rt.records) == 1 and len(rt.records[0]["commit"]) == 64
    # what the opponent receives decodes correctly ("B decodes A")
    assert transport.sent is not None
    assert TurnMessage.from_dict(transport.sent).hint == "heading downtown"
    assert message.role == "thief"
    # 4.3: the message carries a non-empty scent field
    assert len(TurnMessage.from_dict(transport.sent).scent) > 0


def test_scent_trail_decays_across_turns():
    # Thief marches south from (3,3): (4,3) -> (5,3) -> (6,3). The cell BEHIND the
    # start, (2,3), only receives scent from turn 1's field and then just decays —
    # its value must strictly decrease across the three sent messages.
    state = OwnGameState((3, 3), Board(7))
    transport = _FakeTransport()
    rt = PeerRuntime(Role.THIEF, _FakeBrain(), transport, state, BeliefGrid(7), config={})

    for _ in range(3):
        rt.run_turn()

    trails = [TurnMessage.from_dict(m).scent for m in transport.all_sent]
    behind = [t.get((2, 3), 0.0) for t in trails]
    assert behind[0] > behind[1] > behind[2] > 0     # aging, not frozen
    # the fresh post-move position is always near peak (deposited then decayed once)
    assert trails[-1][(6, 3)] > 0.8
