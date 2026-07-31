"""Scoring table (Book Ch. 3, Table 2; Rule 48). Values come from the signed config.

The asymmetry is deliberate: capturing rewards the cop most (20), long survival rewards
the thief most (10), a technical loss zeroes BOTH sides.
"""
from __future__ import annotations

from police_thief.domain.rules import CAPTURE, SURVIVAL

TIE = "tie"
TECHNICAL_LOSS = "technical_loss"


def scores_for(outcome: str, scoring: dict) -> tuple[int, int]:
    """Return (cop_score, thief_score) for an outcome, reading the signed `scoring` block."""
    if outcome == CAPTURE:
        return scoring["capture_cop"], scoring["capture_thief"]
    if outcome == SURVIVAL:
        return scoring["survival_cop"], scoring["survival_thief"]
    if outcome == TIE:
        return scoring["tie_score"], scoring["tie_score"]
    if outcome == TECHNICAL_LOSS:
        return scoring["technical_loss"], scoring["technical_loss"]
    raise ValueError(f"Unknown outcome: {outcome}")
