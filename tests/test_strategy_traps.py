"""Task 4.8 gate: the trap-aware police brain — pounce, seal, guards, and the
empirical proof that barriers turn a 0%-capture chase into real captures."""
from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Direction, MoveType
from police_thief.domain.own_state import OwnGameState
from police_thief.domain import rules
from police_thief.strategy.heuristic import ManhattanBayesThief
from police_thief.strategy.trapping import TrapperPolice


def _delta(cell, size=7):
    b = BeliefGrid(size)
    b.update_from_smell({cell: 5.0})
    return b


def test_pounce_places_barrier_on_adjacent_thief_cell():
    # R46: a barrier dropped on the thief's own cell IS the capture — when the
    # thief is adjacent, nothing outscores it.
    state = OwnGameState((3, 3), Board(7))
    dec = TrapperPolice().decide(state, _delta((3, 4)), barriers_max=14)
    assert dec.move_type is MoveType.BARRIER and dec.direction is Direction.E


def test_cornered_thief_triggers_a_barrier_capture_line():
    # Thief cornered at (6,6), cop at (5,5): the search must open a BARRIER line
    # (not plain chase) and convert it to capture within 3 turns. Which wall is
    # laid first is the search's choice — sealing an escape (S/E) and walling the
    # cop's own cell both force 2-step captures (the latter was discovered by the
    # search itself: forced (6,6)->(5,6), then overlap).
    board = Board(7)
    cop, thief = OwnGameState((5, 5), board), OwnGameState((6, 6), board)
    cop_brain, thief_brain = TrapperPolice(), ManhattanBayesThief()
    first = cop_brain.decide(cop, _delta(thief.position), barriers_max=14)
    assert first.move_type is MoveType.BARRIER          # trap initiated, not chase
    captured = False
    dec = first
    for step in range(1, 4):
        if not cop.apply_move(dec.move_type, dec.direction, 14):
            cop.apply_move(MoveType.HOLD, None)
        if rules.resolve(cop.position, thief.position, board, step, 99) == rules.CAPTURE:
            captured = True
            break
        d = thief_brain.decide(thief, _delta(cop.position), barriers_max=14)
        thief.apply_move(d.move_type, d.direction, 14)
        if rules.resolve(cop.position, thief.position, board, step, 99) == rules.CAPTURE:
            captured = True
            break
        dec = cop_brain.decide(cop, _delta(thief.position), barriers_max=14)
    assert captured, "barrier line did not convert to capture within 3 turns"


def test_never_self_walls():
    # Cop pocketed at (0,0) with (1,0) already walled: walling E=(0,1) would
    # leave the cop with zero moves — must never be chosen.
    board = Board(7, barriers={(1, 0)})
    state = OwnGameState((0, 0), board)
    dec = TrapperPolice().decide(state, _delta((6, 6)), barriers_max=14)
    assert not (dec.move_type is MoveType.BARRIER and dec.direction is Direction.E)


def test_search_reports_the_line_depth():
    # The guard needs to know how deep a capture line is before spending a wall.
    board = Board(7)
    line = TrapperPolice()._search(board, (5, 5), (6, 6), quota=14)
    assert line is not None
    act, depth = line
    assert isinstance(depth, int) and depth >= 1


def test_deep_barrier_lines_are_refused_as_bait():
    # An adaptive thief dancing at range can trigger long "capture lines" that it
    # simply walks out of, draining our 14-barrier quota one bait at a time.
    # Anything deeper than BARRIER_MAX_DEPTH must fall back to the chase.
    strict = TrapperPolice()
    strict.barrier_max_depth = 0            # nothing qualifies -> never spend
    state = OwnGameState((5, 5), Board(7))
    dec = strict.decide(state, _delta((6, 6)), barriers_max=14)
    assert dec.move_type is MoveType.MOVE   # chased instead of taking the bait


def test_reserve_floor_tightens_the_guard_when_walls_run_low():
    # Below the reserve, only a near-certain line (<= RESERVE_MAX_DEPTH) may spend.
    board = Board(7, barriers={(0, c) for c in range(7)} | {(1, c) for c in range(4)})
    assert 14 - len(board.barriers) == 3          # under the reserve floor of 4
    cop = TrapperPolice()
    state = OwnGameState((5, 5), board)
    line = cop._search(board, (5, 5), (6, 6), quota=3)
    if line and line[0][0] is MoveType.BARRIER and line[1] > cop.reserve_max_depth:
        dec = cop.decide(state, _delta((6, 6)), barriers_max=14)
        assert dec.move_type is MoveType.MOVE


def test_adjacent_pounce_survives_every_guard():
    # The R46 kill is the capture itself — no guard may ever veto it, even with
    # the quota down to a single wall.
    board = Board(7, barriers={(0, c) for c in range(7)} | {(1, c) for c in range(6)})
    assert 14 - len(board.barriers) == 1
    state = OwnGameState((3, 3), board)
    dec = TrapperPolice().decide(state, _delta((3, 4)), barriers_max=14)
    assert dec.move_type is MoveType.BARRIER and dec.direction is Direction.E


def test_quota_exhausted_means_no_barrier():
    board = Board(7, barriers={(0, c) for c in range(7)} | {(1, c) for c in range(7)})
    state = OwnGameState((3, 3), board)
    dec = TrapperPolice().decide(state, _delta((5, 5)), barriers_max=14)
    assert dec.move_type is not MoveType.BARRIER


# ── empirical gate: captures actually happen now ─────────────────────────────

def _run_match(cop_start, thief_start=(3, 3), max_steps=35):
    board = Board(7)
    cop, thief = OwnGameState(cop_start, board), OwnGameState(thief_start, board)
    cop_brain, thief_brain = TrapperPolice(), ManhattanBayesThief()
    for step in range(1, max_steps + 1):
        d = thief_brain.decide(thief, _delta(cop.position), barriers_max=14)
        thief.apply_move(d.move_type, d.direction, 14)
        if rules.resolve(cop.position, thief.position, board, step, 99) == rules.CAPTURE:
            return step
        d = cop_brain.decide(cop, _delta(thief.position), barriers_max=14)
        if not cop.apply_move(d.move_type, d.direction, 14):
            cop.apply_move(MoveType.HOLD, None)
        if rules.resolve(cop.position, thief.position, board, step, 99) == rules.CAPTURE:
            return step
    return None


def test_trapper_captures_from_standard_start():
    # The Stage-3 baseline provably NEVER captures (distance-6 plateau).
    assert _run_match((0, 0)) is not None


def test_trapper_captures_from_most_starts():
    starts = [(0, 0), (0, 6), (6, 0), (6, 6), (0, 3), (3, 0)]
    captures = sum(1 for s in starts if _run_match(s) is not None)
    assert captures >= 5, f"captured only {captures}/6"
