"""Stage-1 milestone gate: board, movement, barriers, capture, scoring (Rules 13-16, 46-48)."""
import json
from pathlib import Path

import pytest

from police_thief.domain.board import Board
from police_thief.domain.brains import Direction, MoveType
from police_thief.domain.own_state import OwnGameState
from police_thief.domain import rules, scoring

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "config" / "game.json").read_text())


def test_config_defaults_match_book():
    b = CONFIG["board_and_agents"]
    assert b["grid_size"] == 7 and b["thief_start"] == [3, 3] and b["cop_start"] == [0, 0]
    assert CONFIG["movement_and_barriers"]["max_barriers"] == 14


def test_corner_has_two_legal_moves():
    board = Board(7)
    moves = board.legal_moves((0, 0))          # top-left corner
    assert len(moves) == 2                       # only S and E are on-board
    assert set(d for d, _ in moves) == {Direction.S, Direction.E}


def test_barrier_blocks_a_move():
    board = Board(7, barriers={(2, 3)})
    st = OwnGameState((3, 3), board)
    assert st.apply_move(MoveType.MOVE, Direction.N) is False   # (2,3) is walled
    assert st.position == (3, 3)                                # didn't move
    assert st.apply_move(MoveType.MOVE, Direction.E) is True    # (3,4) is open


def test_no_diagonal_move_exists():
    # Diagonals are simply not representable — Direction has only N/S/E/W (Rule 14).
    assert set(Direction) == {Direction.N, Direction.S, Direction.E, Direction.W}


def test_barrier_quota_enforced():
    board = Board(7)
    st = OwnGameState((3, 3), board)
    # place the max, then one more must be rejected
    for i in range(CONFIG["movement_and_barriers"]["max_barriers"]):
        board.barriers.add((i // 7, i % 7))  # 14 distinct cells across rows 0-1
    assert len(board.barriers) == 14
    assert st.apply_move(MoveType.BARRIER, Direction.N, barriers_max=14) is False


def test_barrier_on_own_cell_is_legal():
    # Barrier Law (Ch. 3): "the cell he stands on OR one of the four adjacent cells".
    board = Board(7)
    st = OwnGameState((3, 3), board)
    assert st.apply_move(MoveType.BARRIER, None, barriers_max=14) is True
    assert (3, 3) in board.barriers
    assert st.position == (3, 3)                 # placing a barrier never moves the agent
    # standing on the barrier, the agent can still step OFF it
    assert st.apply_move(MoveType.MOVE, Direction.E) is True
    # ...but can never re-place on an existing barrier
    st2 = OwnGameState((3, 3), Board(7, barriers={(3, 3)}))
    assert st2.apply_move(MoveType.BARRIER, None, barriers_max=14) is False


def test_own_cell_barrier_respects_quota():
    board = Board(7)
    st = OwnGameState((3, 3), board)
    for i in range(14):
        board.barriers.add((i // 7, i % 7))
    assert st.apply_move(MoveType.BARRIER, None, barriers_max=14) is False


def test_overlap_is_capture():
    board = Board(7)
    assert rules.resolve((3, 3), (3, 3), board, steps=5, survival_threshold=35) == rules.CAPTURE


def test_barrier_on_thief_is_capture():   # Rule 46
    board = Board(7, barriers={(3, 3)})
    assert rules.resolve((0, 0), (3, 3), board, steps=5, survival_threshold=35) == rules.CAPTURE


def test_walled_in_thief_is_capture():    # Rule 47
    board = Board(7, barriers={(2, 2), (4, 2), (3, 1), (3, 3)})
    assert rules.thief_trapped((3, 2), board) is True
    assert rules.resolve((0, 0), (3, 2), board, steps=1, survival_threshold=35) == rules.CAPTURE


def test_survival_after_threshold():
    board = Board(7)
    assert rules.resolve((0, 0), (6, 6), board, steps=35, survival_threshold=35) == rules.SURVIVAL


def test_scoring_table():                 # Rule 48
    s = CONFIG["scoring"]
    assert scoring.scores_for(rules.CAPTURE, s) == (20, 5)
    assert scoring.scores_for(rules.SURVIVAL, s) == (5, 10)
    assert scoring.scores_for(scoring.TIE, s) == (2, 2)
    assert scoring.scores_for(scoring.TECHNICAL_LOSS, s) == (0, 0)
