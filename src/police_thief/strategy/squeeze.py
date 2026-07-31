"""Stalemate breaker: spend a wall to shrink the thief's world (P1-4 / red-team).

Red-team finding: against an edge-hugging thief our cop found capture lines
6-10 plies deep whose FIRST action was always a step, so it never placed a
single wall, and by step 8 it mirror-locked at distance 4 for the rest of the
match — 0% capture. Barriers are the only capture mechanism on this grid, so a
cop that never spends one cannot win against a competent opponent.

The earlier "guarding pathology" came from making area reduction the PRIMARY
objective — the cop then contained forever instead of closing. Here it is only
a fallback, reached when the capture search is dry AND the chase has provably
stalled, which is exactly the position where containment is progress.
"""
from __future__ import annotations

from collections import deque

from police_thief.domain.board import DELTAS, Board
from police_thief.domain.brains import MoveType


def reachable_area(board: Board, start, depth: int) -> int:
    """How many cells the thief could still reach within `depth` steps."""
    seen, queue = {start}, deque([(start, 0)])
    while queue:
        cell, d = queue.popleft()
        if d == depth:
            continue
        for _, nxt in board.legal_moves(cell):
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, d + 1))
    return len(seen)


def best_squeeze(board: Board, cop, thief, horizon: int = 6):
    """The wall that most shrinks the thief's reachable area, or None.

    Never self-walls (the cop must keep a legal move) and never bothers when the
    gain is nil — a wall spent for nothing is a wall unavailable for the kill.
    """
    base = reachable_area(board, thief, horizon)
    best, best_gain = None, 0
    for direction in (None, *DELTAS):
        target = cop if direction is None else board.step(cop, direction)
        if not board.passable(target) or target == thief:
            continue                      # a wall ON the thief is the pounce, not a squeeze
        sim = Board(board.grid_size, set(board.barriers) | {target})
        if not sim.legal_moves(cop if direction is not None else target):
            continue                      # would seal ourselves in
        gain = base - reachable_area(sim, thief, horizon)
        if gain > best_gain:
            best, best_gain = direction, gain
    return (MoveType.BARRIER, best) if best_gain > 0 else None


class StallDetector:
    """Remembers recent (my cell, target cell) pairs; a repeat means we are looping."""

    def __init__(self, memory: int = 8) -> None:
        self.seen: deque = deque(maxlen=memory)

    def stalled(self, cop, thief) -> bool:
        key = (tuple(cop), tuple(thief))
        repeat = key in self.seen
        self.seen.append(key)
        return repeat
