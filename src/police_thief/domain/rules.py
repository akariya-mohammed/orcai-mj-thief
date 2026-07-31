"""Win-condition resolution (Book Ch. 3; Rules 46-48).

Three ways the cop wins a capture:
  1. cop and thief occupy the same cell,
  2. a barrier is placed on the thief's cell (Rule 46),
  3. the thief has no legal move — fully walled in (Rule 47).
Otherwise, if the thief survives the survival threshold, the thief wins.
"""
from __future__ import annotations

from police_thief.domain.board import Board, Cell

# Outcome constants — map straight to the scoring table.
CAPTURE = "capture"
SURVIVAL = "survival"
ONGOING = "ongoing"


def is_overlap_capture(cop_pos: Cell, thief_pos: Cell) -> bool:
    return cop_pos == thief_pos


def barrier_captures_thief(thief_pos: Cell, barriers: set[Cell]) -> bool:
    """Rule 46 — a barrier dropped on the thief's own cell counts as capture."""
    return thief_pos in barriers


def thief_trapped(thief_pos: Cell, board: Board) -> bool:
    """Rule 47 — no legal orthogonal move (surrounded by barriers/edges) = captured."""
    return len(board.legal_moves(thief_pos)) == 0


def resolve(cop_pos: Cell, thief_pos: Cell, board: Board, steps: int,
            survival_threshold: int) -> str:
    """Return CAPTURE, SURVIVAL, or ONGOING for the current board state."""
    if (is_overlap_capture(cop_pos, thief_pos)
            or barrier_captures_thief(thief_pos, board.barriers)
            or thief_trapped(thief_pos, board)):
        return CAPTURE
    if steps >= survival_threshold:
        return SURVIVAL
    return ONGOING
