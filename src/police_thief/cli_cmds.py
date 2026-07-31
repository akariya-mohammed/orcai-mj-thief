"""Command implementations (kept out of cli.py for the 150-line rule)."""
from __future__ import annotations

import json
from pathlib import Path


BOOK_DEFAULTS = {"grid_size": 7, "cop_start": (0, 0), "thief_start": (3, 3)}


def _load_board_config() -> dict:
    """Read the signed config if present (cwd), else fall back to the book defaults."""
    path = Path("config/game.json")
    if path.exists():
        board = json.loads(path.read_text(encoding="utf-8"))["board_and_agents"]
        return {
            "grid_size": board["grid_size"],
            "cop_start": tuple(board["cop_start"]),
            "thief_start": tuple(board["thief_start"]),
        }
    return dict(BOOK_DEFAULTS)


def cmd_selftest_scent(games: int, seed: int) -> int:
    """Full production-path eval: scent-only belief, hints, lie detection, traps.
    These are the reproducible numbers cited in the RESEARCH-REPORT."""
    from police_thief.sdk.localsim import run_batch

    starts = [(0, 0), (0, 6), (6, 0), (6, 6), (0, 3), (3, 0)]
    seeds = tuple(range(seed, seed + max(1, games // len(starts))))
    print("=== selftest --scent: DEV TOOL — full path, partial observability ===")
    s = run_batch(starts=starts, seeds=seeds)
    print(f"games={s.games} captures={s.captures} rate={s.capture_rate:.0%} "
          f"avg_steps={s.avg_steps:.1f} lies_caught={s.lies_caught} "
          f"truths_confirmed={s.truths_confirmed}")
    return 0


def cmd_selftest(steps: int) -> int:
    # Local imports keep `--help` fast and dependency-free.
    from police_thief.domain.belief import BeliefGrid
    from police_thief.domain.board import Board
    from police_thief.domain.own_state import OwnGameState
    from police_thief.domain import rules
    from police_thief.strategy.heuristic import ManhattanBayesPolice, ManhattanBayesThief

    cfg = _load_board_config()
    size = cfg["grid_size"]
    # One shared Board is fine for a single-process dev sim (both sides see the same
    # physics); real peers each hold their own copy, synced by declared placements.
    board = Board(size)
    cop = OwnGameState(cfg["cop_start"], board)
    thief = OwnGameState(cfg["thief_start"], board)
    cop_brain, thief_brain = ManhattanBayesPolice(), ManhattanBayesThief()

    print("=== selftest: DEV TOOL — local self-play, not a league mode ===")
    print(f"start: cop={cop.position} thief={thief.position}")
    for step in range(1, steps + 1):
        # Perfect-info belief stand-in: scent-driven belief arrives in Stage 4.
        cop_belief = BeliefGrid(size)
        cop_belief.update_from_smell({thief.position: 5.0})
        thief_belief = BeliefGrid(size)
        thief_belief.update_from_smell({cop.position: 5.0})

        d = thief_brain.decide(thief, thief_belief, barriers_max=14)
        thief.apply_move(d.move_type, d.direction, 14)
        d = cop_brain.decide(cop, cop_belief, barriers_max=14)
        cop.apply_move(d.move_type, d.direction, 14)

        outcome = rules.resolve(cop.position, thief.position, board, step, 35)
        print(f"step {step:2}: cop={cop.position} thief={thief.position} "
              f"dist={board.distance(cop.position, thief.position)}")
        if outcome == rules.CAPTURE:
            print(f">>> CAPTURE at step {step}")
            break
    print("=== selftest complete ===")
    return 0


