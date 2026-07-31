"""Strategy interface (Book Ch. 6; signatures per reference docs/STRATEGY.md).

The MOVE is ALWAYS pure Python (Rule 25). The LLM only writes bluff *text* — it
never selects a move. Subclass BrainBase and override _pick_move (thief) and/or
_decide_move (police, which also chooses barrier placement).

Public entry point used by the runtime is `decide(...)`, which internally routes to
_pick_move / _decide_move and attaches the verbal hint.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(Enum):
    THIEF = "thief"
    POLICE = "police"


class MoveType(Enum):
    MOVE = "move"
    HOLD = "hold"      # stay in place / never stall the loop
    BARRIER = "barrier"


class Direction(Enum):
    N = "N"
    S = "S"
    E = "E"
    W = "W"


@dataclass
class Decision:
    move_type: MoveType
    direction: Direction | None
    hint: str = ""           # free-text verbal hint (may be a bluff)
    bluff: bool = False      # intent flag, sealed as "truth"/"lie" (Ch. 5 commit)


class BrainBase:
    """Base strategy. Spatial reasoning stays here — deterministic, testable."""

    def decide(self, state, belief, opponent_hint, play_setting,
               barriers_max, deadline_seconds=0, short_threshold=0) -> Decision:
        """Public entry point the runtime calls. Routes to the role-specific override."""
        raise NotImplementedError

    def _pick_move(self, moves, state, belief):
        """THIEF. moves: list[(Direction, (row, col))] already filtered legal.
        state: OwnGameState (position, visited, barriers, board.distance(a, b)).
        belief: BeliefGrid; belief.most_likely() -> single most-likely opponent cell.
        Returns the (direction, cell) tuple to play.
        """
        raise NotImplementedError

    def _decide_move(self, state, belief, barriers_max):
        """POLICE. Returns the whole move: (MoveType, Direction | None)."""
        raise NotImplementedError
