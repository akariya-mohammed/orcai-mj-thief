"""The discrete arena (Book Ch. 3). Orthogonal moves only; barriers are impassable.

Coordinates are (row, col), 0-indexed, origin top-left (per config axis_origin_corner).
The row axis grows downward, so N decreases row and S increases it.
"""
from __future__ import annotations

from police_thief.domain.brains import Direction

# Orthogonal deltas — NO diagonals (Rule 14). STAY is modeled as MoveType.HOLD, not here.
DELTAS: dict[Direction, tuple[int, int]] = {
    Direction.N: (-1, 0),
    Direction.S: (1, 0),
    Direction.E: (0, 1),
    Direction.W: (0, -1),
}

Cell = tuple[int, int]


class Board:
    def __init__(self, grid_size: int, barriers: set[Cell] | None = None) -> None:
        self.grid_size = grid_size
        self.barriers: set[Cell] = set(barriers or set())

    def in_bounds(self, cell: Cell) -> bool:
        r, c = cell
        return 0 <= r < self.grid_size and 0 <= c < self.grid_size

    def passable(self, cell: Cell) -> bool:
        """On the board and not a barrier — a barrier is impassable to BOTH players (Ch. 3)."""
        return self.in_bounds(cell) and cell not in self.barriers

    def step(self, cell: Cell, direction: Direction) -> Cell:
        dr, dc = DELTAS[direction]
        return (cell[0] + dr, cell[1] + dc)

    def legal_moves(self, pos: Cell) -> list[tuple[Direction, Cell]]:
        """Orthogonal neighbors that are on-board and unblocked, as (Direction, cell)."""
        out = []
        for d in DELTAS:
            target = self.step(pos, d)
            if self.passable(target):
                out.append((d, target))
        return out

    def distance(self, a: Cell, b: Cell) -> int:
        """Manhattan distance — admissible for orthogonal movement (Ch. 6)."""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])
