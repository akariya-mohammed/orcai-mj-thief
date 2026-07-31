"""Pheromone scent field (Book Ch. 4; plan tasks 4.1-4.2).

Every agent involuntarily emits a radial scent field around its position each turn;
the opponent reads it as the only unfakeable evidence of presence. Emission follows
the book's Figure-4 grid: center 0.9, falling off radially to 0.04 at the window
corners. Cell values are clamped to the center intensity, so continuous presence
plateaus (Figure 5) instead of accumulating.

Zero third-party imports (domain layer invariant).
"""
from __future__ import annotations

import math

Cell = tuple[int, int]


def emission_at(dist_sq: float, center: float = 0.9) -> float:
    """Gaussian falloff fitted to Book Figure 4: dtau = center * exp(-3*d^2/8).

    Reproduces the figure's values (0.90/0.62/0.42/0.20/0.14/0.04) within 0.01.
    Isolated here so a differing reference formula (Intel I2) is a one-line swap.
    """
    return center * math.exp(-0.375 * dist_sq)


class ScentGrid:
    """Sparse scent intensities for ONE agent's own trail on an NxN board."""

    PRUNE_EPS = 1e-3   # below this a cell is indistinguishable from "no information"

    def __init__(self, size: int, center_intensity: float = 0.9,
                 decay_rate: float = 0.10, field_size: int = 5) -> None:
        self.size = size
        self.center = center_intensity      # signed config: pheromone_center_intensity
        self.decay_rate = decay_rate        # signed config: pheromone_decay (rho)
        self.radius = field_size // 2       # signed config: pheromone_grid_size (5 -> 2)
        self._tau: dict[Cell, float] = {}

    def deposit(self, pos: Cell) -> None:
        """Emit the radial field around pos, clipped at board edges, clamped at center."""
        r0, c0 = pos
        for dr in range(-self.radius, self.radius + 1):
            for dc in range(-self.radius, self.radius + 1):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < self.size and 0 <= c < self.size:
                    add = emission_at(dr * dr + dc * dc, self.center)
                    self._tau[(r, c)] = min(self.center,
                                            self._tau.get((r, c), 0.0) + add)

    def decay_all(self) -> None:
        """Book decay rule: tau <- (1 - rho) * tau each full turn; prune the noise floor."""
        factor = 1.0 - self.decay_rate
        self._tau = {cell: tau * factor for cell, tau in self._tau.items()
                     if tau * factor >= self.PRUNE_EPS}

    def snapshot(self) -> dict[Cell, float]:
        """Detached sparse copy — safe to hand to the wire protocol."""
        return dict(self._tau)
