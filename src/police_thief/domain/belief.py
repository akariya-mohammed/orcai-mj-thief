"""BeliefGrid — probability distribution over the board for the opponent's cell (Book Ch. 6).

Nobody sees the opponent's true position. Each peer maintains a probability grid, updated
from the received (decaying) smell grids and the opponent's (possibly lying) verbal hints,
and diffused each turn because the opponent moved one step. Shown in the GUI as the heatmap.

`smell_trust_weight` (reference default 4.0) is a PRIVATE tuning parameter — how strongly to
trust the scent evidence. It lives in each side's game.toml, is not shared and not signed.
"""
from __future__ import annotations

import math

Cell = tuple[int, int]


class BeliefGrid:
    """Probability distribution over an NxN board for the opponent's cell."""

    def __init__(self, size: int, smell_trust_weight: float = 4.0) -> None:
        self.size = size
        self.trust = smell_trust_weight
        n = size * size
        self.grid = [[1.0 / n for _ in range(size)] for _ in range(size)]

    # ── queries ──────────────────────────────────────────────────────────────
    def most_likely(self) -> Cell:
        """The single cell the opponent is most likely on (argmax b(s))."""
        best, best_p = (0, 0), -1.0
        for r in range(self.size):
            for c in range(self.size):
                if self.grid[r][c] > best_p:
                    best, best_p = (r, c), self.grid[r][c]
        return best

    # ── updates ──────────────────────────────────────────────────────────────
    def diffuse(self, barriers: set[Cell] | None = None) -> None:
        """Spread each cell's mass to its von-Neumann neighbors + itself (stay).

        The opponent moved one orthogonal step or held — this game has no diagonal
        moves, so the tight 5-cell transition model gives a sharper posterior than
        the reference's 3x3 king-step (deliberate deviation; belief is fully
        private, so there is no interop risk). Barriers are impassable: mass never
        flows into one, mass stranded ON one relocates to its passable neighbors,
        and a fully walled-in cell keeps its mass (walled-in opponents are real).
        """
        blocked = barriers or set()
        new = [[0.0] * self.size for _ in range(self.size)]
        for r in range(self.size):
            for c in range(self.size):
                p = self.grid[r][c]
                if p <= 0:
                    continue
                cells = [] if (r, c) in blocked else [(r, c)]      # stay
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):  # N/S/W/E
                    nr, nc = r + dr, c + dc
                    if (0 <= nr < self.size and 0 <= nc < self.size
                            and (nr, nc) not in blocked):
                        cells.append((nr, nc))
                if not cells:      # mass on a barrier with no passable neighbor:
                    continue       # drop it — renormalization absorbs the loss
                share = p / len(cells)
                for nr, nc in cells:
                    new[nr][nc] += share
        self.grid = new
        self._normalize()

    def update_from_smell(self, smell: dict[Cell, float]) -> None:
        """Fuse a received scent map: posterior ∝ prior · exp(trust · intensity)."""
        for (r, c), intensity in smell.items():
            if 0 <= r < self.size and 0 <= c < self.size:
                self.grid[r][c] *= math.exp(self.trust * intensity)
        self._normalize()

    def penalize(self, cells: list[Cell], factor: float = 0.1) -> None:
        """Down-weight cells a (verbal) hint claims are empty — the lie-detection lever.

        If the opponent says 'went north' but their scent is south-east, penalize the north
        cells: a lie collapses their own belief mass toward the true location (Ch. 4 example).
        """
        for r, c in cells:
            if 0 <= r < self.size and 0 <= c < self.size:
                self.grid[r][c] *= factor
        self._normalize()

    def _normalize(self) -> None:
        total = sum(sum(row) for row in self.grid)
        if total > 0:
            self.grid = [[v / total for v in row] for row in self.grid]
