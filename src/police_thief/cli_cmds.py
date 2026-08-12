"""Command implementations (kept out of cli.py for the 150-line rule)."""
from __future__ import annotations

import json
from pathlib import Path

BOOK_DEFAULTS = {"grid_size": 7, "cop_start": (0, 0), "thief_start": (3, 3)}

#: Constitution agreed with Team ahk-yosi — canonical-JSON SHA-256 of game.json.
AGREED_CONFIG_SHA256 = \
    "3835f6a137620d8d98ab3925b2d1ed397d2d20d23bb9ba857bcd104284aac443"


def cmd_interop(args) -> int:
    """Run the reference-dialect networked series (friendly by default).

    Counted mode is triple-gated: the flag itself, an explicit environment
    confirmation, and a friendly-gate file the launcher writes only after a
    fully verified friendly — so an official report can never go out by
    accident (Rules 30/51).
    """
    import os

    from police_thief.interop.refcrypto import digest
    from police_thief.interop.series import ReferenceSeriesPeer
    from police_thief.shared.config import Config

    private = args.config or f"config/{args.role}/game.toml"
    cfg = Config.load(private_path=private)
    actual = digest(cfg.shared)
    if actual != AGREED_CONFIG_SHA256:
        print(f"REFUSING TO PLAY: config/game.json canonical SHA-256 is {actual}, "
              f"agreed constitution is {AGREED_CONFIG_SHA256}")
        return 2
    if args.mode == "counted":
        if os.environ.get("P2P_CONFIRM_COUNTED") != "YES":
            print("counted mode requires explicit confirmation: "
                  "set P2P_CONFIRM_COUNTED=YES")
            return 2
        gate = Path(args.out).parent / "friendly_gate.json"
        if not gate.exists() or \
                not json.loads(gate.read_text(encoding="utf-8")).get("passed"):
            print(f"counted mode requires a passed friendly gate at {gate}")
            return 2
    my_port = args.my_port or (8801 if args.role == "police" else 8802)
    peer = ReferenceSeriesPeer(
        natural_role=args.role, config=cfg, opponent_url=args.opponent_url,
        my_port=my_port, num_games=args.games, mode=args.mode,
        alternate_roles=not args.no_alternate_roles,
        handshake_per_sub_game=not args.no_handshake_per_sub_game,
        turn_timeout=args.turn_timeout, out_dir=args.out, seed=args.seed,
        mcp_url=args.mcp_url)
    peer.start_server()
    result = peer.run_series()
    passed = result["all_audits_verified"] and \
        result["num_sub_games"] == args.games
    print(json.dumps({"mode": args.mode, "passed": passed,
                      "totals": result["totals"],
                      "series_winner": result["series_winner"],
                      "result_sha256": result["result_sha256"]}))
    return 0 if passed else 1


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
    from police_thief.domain import rules
    from police_thief.domain.belief import BeliefGrid
    from police_thief.domain.board import Board
    from police_thief.domain.own_state import OwnGameState
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


