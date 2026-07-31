"""Sealing a turn into an auditable record (task 6.1, Book Ch. 5).

The hash preimage is canonical JSON over {state, move, intent, nonce} — see
domain/crypto.py. The record additionally carries plain metadata (step,
position, hint) that the FINAL mutual audit needs to replay the match: it is
not part of the digest, so adding it can never change a commitment.

Interop note: the reference implementation's exact serialization was never
obtainable (its published samples are internally inconsistent and elide the
fields needed to recompute a digest), so this scheme is ours and is declared
explicitly at handshake. See docs/PRD-6-security.md.
"""
from __future__ import annotations

import json

from police_thief.domain.brains import MoveType
from police_thief.domain.crypto import commit

SEALING_SCHEME = "canonical-json-v1"


def state_str(grid_size: int, position, barriers) -> str:
    return f"grid={grid_size}x{grid_size};self={list(position)};barriers={sorted(barriers)}"


def move_str(decision) -> str:
    if decision.move_type is MoveType.MOVE and decision.direction:
        return f"MOVE:{decision.direction.value}"
    if decision.move_type is MoveType.BARRIER and decision.direction:
        return f"BARRIER:{decision.direction.value}"
    if decision.move_type is MoveType.BARRIER:
        return "BARRIER:SELF"
    return "HOLD"


def step_zero_record(group_name: str, model: str, sub_game_number: int = 1) -> dict:
    """Seal the pre-game declaration: machine, model and the exact playing commit.

    Sealing it before turn 1 is the point — the hardware and code version a team
    competed on cannot be revised afterwards to flatter a fairness normalisation
    (Rules 24/53). The payload doubles as the artifact's step-0 record.
    """
    from police_thief.shared.sysinfo import code_commit, hardware_spec

    payload = {"step": 0, "type": "system_spec", "spec": hardware_spec(),
               "model": model, "code_version": code_commit(),
               "group_name": group_name, "sub_game_number": sub_game_number}
    snapshot = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest, nonce = commit(snapshot, "STEP0", "truth")
    return {"commit": digest, "nonce": nonce, "state": snapshot, "move": "STEP0",
            "intent": "truth", "hint": "", "step": 0, "payload": payload}


def sealed_record(state, decision, step: int) -> dict:
    """Seal one turn. The nonce stays local until the end-of-game audit."""
    snapshot = state_str(state.board.grid_size, state.position, state.barriers)
    action = move_str(decision)
    intent = "lie" if getattr(decision, "bluff", False) else "truth"
    digest, nonce = commit(snapshot, action, intent)
    return {"commit": digest, "nonce": nonce, "state": snapshot, "move": action,
            "intent": intent, "hint": decision.hint, "step": step,
            "position": list(state.position)}
