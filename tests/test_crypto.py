"""Smoke tests for commit-reveal — proves the toolchain and the core seal."""
from police_thief.domain.crypto import commit, verify
from police_thief.domain.state_machine import GamePhaseMachine

import pytest


def test_commit_verify_roundtrip():
    h, nonce = commit(state="s0", move="N", intent="truth")
    assert verify("s0", "N", "truth", nonce, h) is True


def test_tampered_move_is_caught():
    h, nonce = commit(state="s0", move="N", intent="truth")
    # Opponent tries to reveal a different move than they committed.
    assert verify("s0", "S", "truth", nonce, h) is False


def test_state_machine_rejects_illegal_transition():
    m = GamePhaseMachine()
    m.transition("COMPUTING_MOVE")
    with pytest.raises(ValueError):
        m.transition("VERIFYING")  # not a legal successor of COMPUTING_MOVE
