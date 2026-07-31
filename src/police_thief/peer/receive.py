"""Receive-side adjudication: applying what the opponent declares (Rule 15).

Kept out of the runtime so the turn loop stays orchestration rather than
rule-keeping, and so each rule is unit-testable without a live peer.
"""
from __future__ import annotations


def accept_barrier(state, cell, quota: int) -> str | None:
    """Apply a wall the opponent declared, or return why we refuse it.

    Adjacency cannot be checked live — we do not know their position — so quota
    is the guard here and placement legality is settled at the final audit.
    """
    if cell not in state.barriers and len(state.barriers) >= quota:
        return f"declared barrier {list(cell)} exceeds the barrier quota of {quota}"
    state.board.barriers.add(cell)
    return None
