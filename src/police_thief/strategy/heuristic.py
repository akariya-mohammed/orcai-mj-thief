"""Shipped heuristic brains (Book Ch. 6). Move decision is pure Python (Rule 25).

Both sides reason over the Bayesian belief map's single most-likely opponent cell and act on
Manhattan distance — the cop minimizes it (chase), the thief maximizes it (flee). Deterministic
and fully testable; the LLM never touches the move. Students may subclass BrainBase to replace
these via game.toml [strategy] thief_class / police_class.
"""
from __future__ import annotations

from police_thief.domain.brains import BrainBase, Decision, Direction, MoveType


class ManhattanBayesThief(BrainBase):
    """Flee: pick the legal move that maximizes distance from the predicted cop cell."""

    def decide(self, state, belief, opponent_hint="", play_setting=None,
               barriers_max=0, **kw) -> Decision:
        picked = self._pick_move(state.board.legal_moves(state.position), state, belief)
        if picked is None:
            return Decision(MoveType.HOLD, None, hint="")
        direction, _cell = picked
        return Decision(MoveType.MOVE, direction, hint="")

    def _pick_move(self, moves, state, belief):
        if not moves:
            return None
        target = belief.most_likely()          # predicted cop position
        best, best_key = None, None
        for direction, cell in moves:
            # primary: farther is better; tie-break: prefer unvisited, then N/S/E/W order
            key = (state.board.distance(cell, target), 0 if cell in state.visited else 1)
            if best_key is None or key > best_key:
                best, best_key = (direction, cell), key
        return best


class ManhattanBayesPolice(BrainBase):
    """Chase: pick the legal move that minimizes distance to the predicted thief cell."""

    def decide(self, state, belief, opponent_hint="", play_setting=None,
               barriers_max=0, **kw) -> Decision:
        move_type, direction = self._decide_move(state, belief, barriers_max)
        return Decision(move_type, direction, hint="")

    def _decide_move(self, state, belief, barriers_max):
        moves = state.board.legal_moves(state.position)
        if not moves:
            return (MoveType.HOLD, None)
        target = belief.most_likely()          # predicted thief position
        best, best_dist = None, None
        for direction, cell in moves:
            dist = state.board.distance(cell, target)
            if best_dist is None or dist < best_dist:   # ties keep first (N/S/E/W order)
                best, best_dist = direction, dist
        # TODO(edge e3): barrier-trap — when adjacent, wall an escape cell instead of stepping.
        return (MoveType.MOVE, best)


class RingRunnerThief(BrainBase):
    """Evasion that actually survives (red-team result, replaces plain flee in play).

    Plain max-distance flight loses 0/6 against our own cop: fleeing directly away
    is predictable, and it walks into edges and corners where the cop's capture
    lines close. Running the ring ONE CELL INSIDE the border keeps four escape
    routes at all times (a border cell has three, a corner two) and turns the
    board into a loop the cop cannot close alone — measured 18/18 survival across
    a search cop, a chase cop, and a board pre-seeded with six walls.

    The ring term dominates distance on purpose: position quality outlives any
    single turn's separation.
    """

    RING_WEIGHT = 3          # pull toward the one-inside-the-border loop
    DISTANCE_WEIGHT = 1      # break ties by getting away

    def decide(self, state, belief, opponent_hint="", play_setting=None,
               barriers_max=0, **kw) -> Decision:
        picked = self._pick_move(state.board.legal_moves(state.position), state, belief)
        if picked is None:
            return Decision(MoveType.HOLD, None, hint="")
        return Decision(MoveType.MOVE, picked[0], hint="")

    def _pick_move(self, moves, state, belief):
        if not moves:
            return None
        board, hunter = state.board, belief.most_likely()
        edge = board.grid_size - 1
        best, best_score = None, None
        for direction, cell in moves:
            ring = min(cell[0], cell[1], edge - cell[0], edge - cell[1])
            score = (self.DISTANCE_WEIGHT * board.distance(cell, hunter)
                     - self.RING_WEIGHT * abs(ring - 1))
            if best_score is None or score > best_score:
                best, best_score = (direction, cell), score
        return best
