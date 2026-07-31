"""Terminal claims — how a distributed game actually ends (task 6.4, Book Ch. 3).

With no referee, a game ends by AGREEMENT: one peer claims a terminal condition
and the other confirms or denies it against its own private truth. The book puts
a cryptographic duty of truth on the answer (Rules 21-22) — a denial ships the
denier's own position, so a false denial is provable at the final audit and
costs the match. Honest denial is free; lying about it is fatal.
"""
from __future__ import annotations

CAPTURE = "capture"
SURVIVAL = "survival"
TECHNICAL_LOSS = "technical_loss"


def judge_capture_claim(claimed_cell, my_position, step: int) -> dict:
    """Answer a cop's capture claim truthfully (Rule 21).

    The response carries our position either way: confirming proves the capture,
    and denying puts our claim on the record where the audit can check it.
    """
    confirmed = tuple(claimed_cell) == tuple(my_position)
    return {"type": CAPTURE, "step": step, "confirmed": confirmed,
            "position": list(my_position)}


def judge_survival_claim(claimed_step: int, threshold: int) -> dict:
    """Answer a thief's survival claim: the agreed step count must really be reached."""
    return {"type": SURVIVAL, "step": claimed_step,
            "confirmed": claimed_step >= threshold, "threshold": threshold}
