"""Trap-aware police brain (task 4.8). Honest label: NOT reinforcement learning —
forward search for forced capture lines over a deterministic opponent model,
with pure interception chase as fallback (the book's minimax/own-algorithm track).

Why search: a lone cop on a Cartesian grid is robber-win (the grid is not
dismantlable — Nowakowski-Winkler, cited by the book), so chasing never captures
(distance plateaus at 6). Two failed designs proved that 1-ply "containment"
scores teach the cop to GUARD a cornered thief forever instead of capturing.
Capture is only forced by SEQUENCES: approach + wall the escape lane + pounce
(R46) or full enclosure (R47). An A*-style search over cop actions — thief
replies simulated with our own thief heuristic as the model — finds those
sequences; barriers are only ever spent inside a found capture line, so quota
thrift is emergent rather than hand-tuned.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

from police_thief.domain.board import Board, DELTAS
from police_thief.domain.brains import BrainBase, Decision, MoveType
from police_thief.strategy.heuristic import ManhattanBayesThief
from police_thief.strategy.squeeze import StallDetector, best_squeeze

Cell = tuple[int, int]


@dataclass
class _Ghost:
    """Minimal OwnGameState stand-in for the opponent model."""
    position: Cell
    board: Board
    visited: frozenset = frozenset()


class _Point:
    """Minimal BeliefGrid stand-in: the model thief 'knows' the cop's cell."""
    def __init__(self, cell: Cell) -> None:
        self.cell = cell

    def most_likely(self) -> Cell:
        return self.cell


class TrapperPolice(BrainBase):
    # Barrier-bait resistance: an adaptive thief can dance just outside reach,
    # trigger a long "capture line" it simply walks out of, and drain our 14 walls
    # one bait at a time — so a wall is only ever spent on a SHORT line. 6 is the
    # measured knee (identical capture rate to an uncapped search; a cap of 3 cost
    # 17 points), and we spend ~5 walls a match, so the reserve is real protection.
    BARRIER_MAX_DEPTH = 6      # normal ceiling for spending a wall
    RESERVE_FLOOR = 4          # at or below this many walls left...
    RESERVE_MAX_DEPTH = 2      # ...only a near-certain line may spend one

    def __init__(self, max_nodes: int = 800, max_depth: int = 10,
                 forbid_barrier_on_thief: bool = False) -> None:
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.barrier_max_depth = self.BARRIER_MAX_DEPTH
        self.reserve_max_depth = self.RESERVE_MAX_DEPTH
        # NajAmjad Barrier Law: a barrier NEVER goes on the cell the thief
        # occupies, so the R46 pounce is not a legal action and a
        # barrier-onto-thief node is not a capture. Capture then comes only
        # from overlap or full enclosure (R47). Default False: the ahk-yosi
        # and amireman profiles keep the book's R46 pounce untouched.
        self.forbid_barrier_on_thief = forbid_barrier_on_thief
        self._model = ManhattanBayesThief()
        self._stall = StallDetector()

    def decide(self, state, belief, opponent_hint="", play_setting=None,
               barriers_max=0, **kw) -> Decision:
        return Decision(*self._decide_move(state, belief, barriers_max), hint="")

    def _decide_move(self, state, belief, barriers_max):
        board, me = state.board, state.position
        thief = belief.most_likely()
        quota = barriers_max - len(board.barriers)
        # R46 pounce: a barrier ON the adjacent thief cell is the capture itself.
        if quota > 0 and not self.forbid_barrier_on_thief:
            for d, cell in board.legal_moves(me):
                if cell == thief:
                    return (MoveType.BARRIER, d)
        line = self._search(board, me, thief, quota)
        if line is not None and self._may_commit(line, quota):
            return line[0]
        # No short line and the chase is going in circles: shrink their world.
        # Barriers are the ONLY capture mechanism here, so a cop that never
        # spends one cannot beat a competent evader (red-team: 0% vs edge-hugger).
        if quota > self.RESERVE_FLOOR and self._stall.stalled(me, thief):
            squeeze = best_squeeze(board, me, thief)
            if squeeze:
                return squeeze
        return self._chase(board, me, thief)

    def _may_commit(self, line, quota: int) -> bool:
        """Moves are always free; spending a WALL demands a short, credible line."""
        (move_type, _), depth = line
        if move_type is not MoveType.BARRIER:
            return True
        ceiling = (self.reserve_max_depth if quota <= self.RESERVE_FLOOR
                   else self.barrier_max_depth)
        return depth <= ceiling

    # ── forced-capture search (A* over cop actions; thief reply deterministic) ──
    def _actions(self, sim: Board, cop: Cell, quota_used: int, quota: int):
        for d, cell in sim.legal_moves(cop):
            yield (MoveType.MOVE, d, cell)
        if quota - quota_used > 0:
            for d in (None, *DELTAS):
                target = cop if d is None else sim.step(cop, d)
                if sim.passable(target):
                    yield (MoveType.BARRIER, d, target)

    def _reply(self, sim: Board, thief: Cell, cop: Cell):
        """Deterministic opponent model: our own flee heuristic. None = walled in."""
        moves = sim.legal_moves(thief)
        if not moves:
            return None
        picked = self._model._pick_move(moves, _Ghost(thief, sim), _Point(cop))
        return picked[1] if picked else thief

    def _search(self, board: Board, me: Cell, thief: Cell, quota: int):
        """Return ((move_type, direction), plies) for the shortest capture line, or None.
        The ply count is what the bait guard weighs before spending a wall."""
        start = (me, thief, frozenset(board.barriers))
        best_depth = {start: 0}
        heap = [(board.distance(me, thief), 0, 0, start, None)]
        tie, nodes = 0, 0
        while heap and nodes < self.max_nodes:
            _, _, depth, (cop, th, walls), first = heapq.heappop(heap)
            nodes += 1
            if depth >= self.max_depth:
                continue
            sim_base = Board(board.grid_size, set(walls))
            for move_type, d, target in self._actions(sim_base, cop, len(walls) - len(board.barriers), quota):
                if (self.forbid_barrier_on_thief
                        and move_type is MoveType.BARRIER and target == th):
                    continue          # NajAmjad: never wall the thief's cell
                walls2, cop2 = set(walls), cop
                if move_type is MoveType.MOVE:
                    cop2 = target
                else:
                    walls2.add(target)
                act = first or (move_type, d)
                if (move_type is MoveType.BARRIER and target == th) or cop2 == th:
                    return act, depth + 1                        # R46 / overlap
                sim = Board(board.grid_size, walls2)
                th2 = self._reply(sim, th, cop2)
                if th2 is None or th2 == cop2:
                    return act, depth + 1                        # R47 / walked in
                key = (cop2, th2, frozenset(walls2))
                if best_depth.get(key, 99) <= depth + 1:
                    continue
                best_depth[key] = depth + 1
                tie += 1
                heapq.heappush(heap, (depth + 1 + sim.distance(cop2, th2),
                                      tie, depth + 1, key, act))
        return None

    def _chase(self, board: Board, me: Cell, thief: Cell):
        """Fallback: pure interception — minimize distance to the PREDICTED reply."""
        best, best_key = (MoveType.HOLD, None), None
        for d, cell in board.legal_moves(me):
            th2 = self._reply(board, thief, cell) or thief
            key = board.distance(cell, th2)
            if best_key is None or key < best_key:
                best, best_key = (MoveType.MOVE, d), key
        return best
