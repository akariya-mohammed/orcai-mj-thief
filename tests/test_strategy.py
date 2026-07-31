"""Stage-3 gate: the blind Manhattan+Bayes brains chase, flee, and find shortest paths."""
from police_thief.domain.board import Board, DELTAS
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.belief import BeliefGrid
from police_thief.domain.brains import Direction, MoveType
from police_thief.strategy.heuristic import ManhattanBayesThief, ManhattanBayesPolice


def _belief_on(cell, size=7):
    b = BeliefGrid(size)
    b.update_from_smell({cell: 5.0})   # concentrate belief on a known cell
    assert b.most_likely() == cell
    return b


def test_police_steps_toward_belief():
    state = OwnGameState((3, 3), Board(7))
    dec = ManhattanBayesPolice().decide(state, _belief_on((3, 6)), barriers_max=14)
    assert dec.move_type is MoveType.MOVE and dec.direction is Direction.E


def test_thief_steps_to_max_distance_cell():
    board = Board(7)
    state = OwnGameState((3, 3), board)
    target = (3, 6)                       # predicted cop
    dec = ManhattanBayesThief().decide(state, _belief_on(target), barriers_max=14)
    chosen = (3 + DELTAS[dec.direction][0], 3 + DELTAS[dec.direction][1])
    best = max(board.distance(c, target) for _, c in board.legal_moves((3, 3)))
    assert board.distance(chosen, target) == best   # moved as far away as legally possible


def test_police_reaches_target_in_shortest_number_of_steps():
    board = Board(7)
    state = OwnGameState((0, 0), board)
    belief = _belief_on((0, 3))
    brain = ManhattanBayesPolice()
    steps_needed = board.distance(state.position, (0, 3))   # 3
    for _ in range(steps_needed):
        dec = brain.decide(state, belief, barriers_max=14)
        state.apply_move(dec.move_type, dec.direction, 14)
    assert state.position == (0, 3)      # reached in exactly the Manhattan distance → shortest


def test_walled_in_agent_holds():
    board = Board(7, barriers={(2, 3), (4, 3), (3, 2), (3, 4)})
    state = OwnGameState((3, 3), board)
    dec = ManhattanBayesThief().decide(state, BeliefGrid(7), barriers_max=14)
    assert dec.move_type is MoveType.HOLD
