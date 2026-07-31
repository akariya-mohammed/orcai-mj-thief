"""OwnGameState — a single peer's local truth (Book Ch. 2; interface per reference).

Exposes state.position, state.visited, state.barriers, state.board (with board.distance).
apply_move returns False for an illegal move so the runtime can fall back to HOLD and
"never stall the loop" — it never raises during a game.
"""
from __future__ import annotations

from police_thief.domain.board import Board, Cell
from police_thief.domain.brains import Direction, MoveType


class OwnGameState:
    def __init__(self, position: Cell, board: Board) -> None:
        self.position: Cell = position
        self.board = board
        self.visited: set[Cell] = {position}

    @property
    def barriers(self) -> set[Cell]:
        return self.board.barriers

    def apply_move(self, move_type: MoveType, direction: Direction | None,
                   barriers_max: int | None = None) -> bool:
        if move_type is MoveType.HOLD:
            return True

        if move_type is MoveType.MOVE:
            if direction is None:
                return False
            target = self.board.step(self.position, direction)
            if not self.board.passable(target):
                return False            # illegal → caller falls back to HOLD
            self.position = target
            self.visited.add(target)
            return True

        if move_type is MoveType.BARRIER:
            if barriers_max is None:
                return False
            if len(self.board.barriers) >= barriers_max:   # quota (Rule 12, max_barriers)
                return False
            # Barrier Law (Ch. 3): the cell the agent STANDS ON (direction=None)
            # or one of the four orthogonally adjacent cells.
            target = (self.position if direction is None
                      else self.board.step(self.position, direction))
            if not self.board.passable(target):             # can't wall an edge/existing barrier
                return False
            self.board.barriers.add(target)                 # barriers are irreversible (Ch. 3)
            return True

        return False
