"""Terminal-claim handling for the live loop (task 6.3, Rules 21-22).

Rule 22 makes a FALSE capture claim an immediate disqualification with no
appeal, so the cop may only claim when it genuinely believes it has landed on
the thief — never as a routine probe. The thief's answer is equally binding
(Rule 21) and ships its own position, so a false denial is provable at audit.
"""
from __future__ import annotations

from police_thief.domain.brains import MoveType, Role
from police_thief.domain.termination import (CAPTURE, SURVIVAL, judge_capture_claim,
                                             judge_survival_claim)


def good_faith_capture_claim(role, position, belief, move_type) -> list | None:
    """Claim ONLY when our own belief says the thief is on the cell we just took."""
    if role is not Role.POLICE or move_type is not MoveType.MOVE:
        return None
    return list(position) if tuple(position) == tuple(belief.most_likely()) else None


def survival_claim(role, step: int, threshold: int) -> dict | None:
    """The thief asserts the win once the agreed step count is genuinely reached."""
    if role is Role.THIEF and step >= threshold:
        return {"type": SURVIVAL, "step": step}
    return None


def answer_claims(msg, my_position, step: int, threshold: int):
    """(claim_response to send back, outcome or None) for one incoming message."""
    response = outcome = None
    if msg.capture_claim is not None:
        response = judge_capture_claim(msg.capture_claim, my_position, step)
        if response["confirmed"]:
            outcome = {"type": CAPTURE, "winner": "police", "step": step}
    elif msg.win_claim and msg.win_claim.get("type") == SURVIVAL:
        response = judge_survival_claim(msg.win_claim.get("step", 0), threshold)
        if response["confirmed"]:
            outcome = {"type": SURVIVAL, "winner": "thief", "step": response["step"]}
    if isinstance(msg.claim_response, dict) and msg.claim_response.get("confirmed"):
        kind = msg.claim_response.get("type")
        outcome = {"type": kind, "step": msg.claim_response.get("step", step),
                   "winner": "police" if kind == CAPTURE else "thief"}
    return response, outcome
