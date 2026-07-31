"""P0 hardening: the receive path must survive hostile input, and the SIGNED
clock must govern how long we wait (a lenient private clock is exploitable).

Inbound messages are opponent-controlled data, never trusted input: a crash in
the handler forfeits the match to whoever sent the bad bytes.
"""
import json

import pytest

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Role
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.protocol import TurnMessage
from police_thief.exceptions import ProtocolViolation
from police_thief.peer.runner import PeerProcess
from police_thief.peer.runtime import PeerRuntime
from police_thief.shared.config import Config

GOOD_COMMIT = "a" * 64
SHARED = json.loads(open("config/game.json", encoding="utf-8").read())


class _T:
    def send_turn(self, m):
        return {}


def _rt():
    return PeerRuntime(Role.POLICE, None, _T(), OwnGameState((0, 0), Board(7)),
                       BeliefGrid(7), config={})


def _good(**over):
    msg = {"role": "thief", "commit": GOOD_COMMIT, "hint": "", "scent": {},
           "capture_claim": None, "claim_response": None, "win_claim": None}
    msg.update(over)
    return msg


# ── parse layer: every hostile shape is a named violation, never an exception ──

HOSTILE = [
    ({}, "missing"),                                     # empty envelope
    (None, "expected"),                                  # not an object at all
    ([1, 2, 3], "expected"),                             # wrong container type
    ("not-a-dict", "expected"),
    ({"role": "thief"}, "missing"),                      # no commit
    ({"commit": GOOD_COMMIT}, "missing"),                # no role
    ({"role": "banker", "commit": GOOD_COMMIT}, "role"),  # unknown role
    ({"role": "thief", "commit": "short"}, "commit"),    # not a digest
    ({"role": "thief", "commit": 12345}, "commit"),      # wrong type
    ({"role": "thief", "commit": "z" * 64}, "commit"),   # non-hex
]


@pytest.mark.parametrize("payload,fragment", HOSTILE)
def test_hostile_envelopes_raise_named_violations(payload, fragment):
    with pytest.raises(ProtocolViolation) as exc:
        TurnMessage.from_dict(payload)
    assert fragment in str(exc.value).lower()


def test_hint_type_and_flood_guards():
    with pytest.raises(ProtocolViolation):
        TurnMessage.from_dict(_good(hint={"nested": "object"}))
    with pytest.raises(ProtocolViolation):
        TurnMessage.from_dict(_good(hint="word " * 5000))     # resource flood


def test_scent_flood_guard():
    flood = {f"{r},{c}": 0.5 for r in range(200) for c in range(200)}
    with pytest.raises(ProtocolViolation):
        TurnMessage.from_dict(_good(scent=flood))


def test_valid_message_still_parses():
    msg = TurnMessage.from_dict(_good(hint="drifting north", scent={"3,3": 0.9}))
    assert msg.role == "thief" and msg.scent[(3, 3)] == 0.9


# ── runtime layer: reject, strike, and finally declare — but never crash ──────

def test_malformed_message_is_rejected_not_fatal():
    rt = _rt()
    ack = rt.on_opponent_turn({})                    # must not raise
    assert ack["status"] == "rejected" and "reason" in ack
    assert ack["strike"] == 1 and ack["strikes_remaining"] == 2
    assert rt.phases.state != "TECHNICAL_LOSS"       # one strike is not fatal


def test_three_strikes_declare_opponent_technical_loss():
    rt = _rt()
    for expected in (1, 2, 3):
        ack = rt.on_opponent_turn({"garbage": expected})
        assert ack["strike"] == expected
    assert ack["opponent_technical_loss"] is True
    assert rt.phases.state == "TECHNICAL_LOSS"
    assert rt.violations.exhausted


def test_strikes_preserve_raw_evidence():
    rt = _rt()
    rt.on_opponent_turn({"role": "thief", "commit": "tampered"})
    evidence = rt.violations.evidence()
    assert evidence["violation_count"] == 1
    assert "tampered" in evidence["violations"][0]["raw"]
    assert evidence["violations"][0]["reason"]


def test_good_messages_after_strikes_still_work():
    rt = _rt()
    rt.on_opponent_turn({})                          # 2 strikes, not yet fatal
    rt.on_opponent_turn(None)
    ack = rt.on_opponent_turn(_good(hint="still running north"))
    assert ack["status"] == "ok" and ack["acknowledged_commit"] == GOOD_COMMIT
    assert rt.phases.state != "TECHNICAL_LOSS"


def test_violation_can_be_declared_from_any_live_phase():
    # A hostile message can land while we are mid-turn on the game thread.
    rt = _rt()
    for phase in ("COMPUTING_MOVE", "COMMITTING"):
        rt.phases.state = phase
        rt.phases.transition("TECHNICAL_LOSS")       # must be legal from anywhere live
        rt.phases.state = "WAITING_FOR_OPPONENT"


# ── the signed clock governs, not the private one ────────────────────────────

def test_signed_response_timeout_overrides_lenient_private_value():
    private = {"game": {"group_id": "x"},
               "network": {"my_port": 8801, "opponent_url": "http://127.0.0.1:8802/mcp",
                           "turn_timeout_seconds": 180}}    # lenient private value
    process = PeerProcess("police", Config(SHARED, private))
    signed = SHARED["network_and_league"]["response_timeout_sec"]
    assert signed == 30
    assert process.turn_timeout == signed            # the contract wins, not the 180


def test_technical_loss_records_fault_and_violations(tmp_path):
    process = PeerProcess("police", Config(SHARED, {"game": {"group_id": "x"}}))
    process.runtime.on_opponent_turn({})             # one recorded violation
    process._technical_loss("opponent silent", out_dir=tmp_path, at_fault="opponent")
    saved = json.loads((tmp_path / "technical_loss_police.json").read_text())
    assert saved["at_fault"] == "opponent"
    assert saved["violations"]["violation_count"] == 1
