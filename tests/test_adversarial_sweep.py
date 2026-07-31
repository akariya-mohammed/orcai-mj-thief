"""6.6: the adversarial sweep — every row of the violation matrix, end to end.

Each case drives a real PeerRuntime, injects one specific cheat, and asserts we
CATCH it, name it, and can hand a grader the evidence. The final case is the
mirror image and matters just as much: an honest opponent must survive the
entire sweep untouched, because a false accusation costs us the match.
"""
import json

import pytest

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import BrainBase, Decision, Direction, MoveType, Role
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.smell import ScentGrid
from police_thief.peer.finish import disclosure, finalize
from police_thief.peer.runtime import PeerRuntime

CFG = {"rules.barriers_max": 14, "rules.survival_threshold": 35,
       "pheromones": {"pheromone_center_intensity": 0.9, "pheromone_decay": 0.10,
                      "pheromone_grid_size": 5},
       "board.size": 7}
GOOD = "a" * 64


class _Walker(BrainBase):
    def decide(self, state, belief, hint, play_setting, barriers_max, **kw):
        return Decision(MoveType.MOVE, Direction.S, hint="")


class _Link:
    def __init__(self):
        self.sent = []

    def send_turn(self, m):
        self.sent.append(m)
        return {}


def _peer(role=Role.THIEF, pos=(0, 3)):
    return PeerRuntime(role, _Walker(), _Link(), OwnGameState(pos, Board(7)),
                       BeliefGrid(7), config=CFG)


def _honest_match(turns=4):
    """A clean thief history plus the disclosure it would hand over."""
    peer = _peer()
    for _ in range(turns):
        peer.run_turn()
    return peer, disclosure(peer, "them")


# ── live wire: malformed input and floods ────────────────────────────────────

MALFORMED = [
    ({}, "missing"), (None, "expected"), ([1, 2], "expected"),
    ({"role": "thief"}, "missing"), ({"role": "x", "commit": GOOD}, "role"),
    ({"role": "thief", "commit": "nope"}, "commit"),
    ({"role": "thief", "commit": GOOD, "hint": ["not", "a", "string"]}, "hint"),
    ({"role": "thief", "commit": GOOD, "hint": "w " * 900}, "flood"),
    ({"role": "thief", "commit": GOOD, "barrier": [99, 99]}, "barrier"),
]


@pytest.mark.parametrize("payload,fragment", MALFORMED)
def test_malformed_traffic_is_caught_named_and_never_fatal(payload, fragment):
    peer = _peer()
    ack = peer.on_opponent_turn(payload)          # must not raise
    assert ack["status"] == "rejected"
    assert fragment in ack["reason"].lower()
    assert peer.violations.evidence()["violation_count"] == 1


def test_persistent_abuse_ends_in_technical_loss_with_evidence():
    peer = _peer()
    for _ in range(3):
        peer.on_opponent_turn({"junk": True})
    assert peer.phases.state == "TECHNICAL_LOSS"
    evidence = peer.violations.evidence()
    assert evidence["violation_count"] == 3
    assert all(v["raw"] for v in evidence["violations"])   # raw payloads preserved


def test_barrier_quota_breach_on_the_wire_is_refused():
    board = Board(7, barriers={(0, c) for c in range(7)} | {(1, c) for c in range(7)})
    peer = PeerRuntime(Role.THIEF, _Walker(), _Link(), OwnGameState((5, 5), board),
                       BeliefGrid(7), config=CFG)
    ack = peer.on_opponent_turn({"role": "police", "commit": GOOD, "barrier": [3, 3]})
    assert ack["status"] == "rejected" and "quota" in ack["reason"].lower()


# ── post-game audit: forged histories ────────────────────────────────────────

def _audit(their, tmp_path):
    peer = _peer()
    peer.outcome = {"type": "capture", "winner": "police", "step": 4}
    return finalize(peer, their, config=CFG, out_dir=tmp_path, game_uid="uid")


def test_hash_mismatch_is_caught_and_attributed(tmp_path):
    _, their = _honest_match()
    their["records"][1]["move"] = "MOVE:N"        # rewritten after sealing
    verdict = _audit(their, tmp_path)
    assert verdict["audit"]["passed"] is False
    assert any(f["rule"] == "hash" for f in verdict["audit"]["failures"])
    assert verdict["at_fault"] == "them"


@pytest.mark.parametrize("mutate,rule", [
    (lambda r: r[1].update(position=[9, 9]), "move"),      # teleport / 2-step jump
    (lambda r: r[1].update(move="BARRIER:N"), "move"),     # thief placing a wall
    (lambda r: r[1].update(move="HOLD"), "move"),          # HOLD that secretly moved
])
def test_illegal_move_histories_are_caught(mutate, rule, tmp_path):
    _, their = _honest_match()
    mutate(their["records"])
    verdict = _audit(their, tmp_path)
    assert verdict["audit"]["passed"] is False
    assert any(f["rule"] == rule for f in verdict["audit"]["failures"])


def test_teleported_scent_trail_is_caught(tmp_path):
    _, their = _honest_match()
    decoy = ScentGrid(7)
    decoy.deposit((6, 6))                          # nowhere the revealed walk went
    decoy.decay_all()
    their["scent_broadcasts"][2] = decoy.snapshot()
    verdict = _audit(their, tmp_path)
    assert verdict["audit"]["passed"] is False
    assert any(f["rule"] == "scent" for f in verdict["audit"]["failures"])


def test_every_verdict_ships_an_evidence_artifact(tmp_path):
    _, their = _honest_match()
    their["records"][0]["nonce"] = "0" * 32
    verdict = _audit(their, tmp_path)
    saved = json.loads(open(verdict["evidence_path"], encoding="utf-8").read())
    assert saved["audit"]["failures"] and saved["at_fault"] == "them"
    assert saved["outcome"]["type"] == "capture"


# ── the mirror image: honesty must survive the whole sweep ───────────────────

def test_an_honest_opponent_is_never_accused(tmp_path):
    _, their = _honest_match(turns=6)
    verdict = _audit(their, tmp_path)
    assert verdict["audit"]["passed"] is True, verdict["audit"]["failures"]
    assert verdict["at_fault"] is None
