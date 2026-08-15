"""Command implementations (kept out of cli.py for the 150-line rule)."""
from __future__ import annotations

import json
from pathlib import Path

BOOK_DEFAULTS = {"grid_size": 7, "cop_start": (0, 0), "thief_start": (3, 3)}

#: Constitution agreed with Team ahk-yosi — canonical-JSON SHA-256 of game.json.
AGREED_CONFIG_SHA256 = \
    "fef1fe3a229b0c7daece9f1e3ebe7a097a7207e6ac0628b6c67050595a6101be"

#: Constitution for Team amireman (config/game.amireman.json — Haifa, spec App. A).
AMIREMAN_CONFIG_SHA256 = \
    "32e86f85c47920c4a567df403bd1f263f1bbea5f59c7db0b7aeb640f30d15812"


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

    spec_profile = getattr(args, "spec_profile", "ahk-yosi")
    shared_json = getattr(args, "config_json", None) or "config/game.json"
    private = args.config or f"config/{args.role}/game.toml"
    cfg = Config.load(shared_path=shared_json, private_path=private)
    # The expected constitution depends on the opponent profile; --agreed-sha
    # overrides it explicitly. ahk-yosi and amireman sign DIFFERENT constitutions
    # (New York vs Haifa), so each has its own canonical SHA-256.
    default_sha = (AMIREMAN_CONFIG_SHA256 if spec_profile == "amireman"
                   else AGREED_CONFIG_SHA256)
    expected_sha = getattr(args, "agreed_sha", None) or default_sha
    actual = digest(cfg.shared)
    if actual != expected_sha:
        print(f"REFUSING TO PLAY: {shared_json} canonical SHA-256 is {actual}, "
              f"agreed constitution ({spec_profile}) is {expected_sha}")
        return 2
    if args.mode == "counted":
        if os.environ.get("P2P_CONFIRM_COUNTED") != "YES":
            print("counted mode requires explicit confirmation: "
                  "set P2P_CONFIRM_COUNTED=YES")
            return 2
        # Opponent-isolated gate: an ahk-yosi friendly gate must NOT authorize an
        # amireman counted match (and vice-versa).
        gate_name = ("friendly_gate.json" if spec_profile == "ahk-yosi"
                     else f"friendly_gate_{spec_profile}.json")
        gate = Path(args.out).parent / gate_name
        if not gate.exists() or \
                not json.loads(gate.read_text(encoding="utf-8")).get("passed"):
            print(f"counted mode requires a passed friendly gate at {gate}")
            return 2
        if not Path("credentials.json").exists():
            print("counted mode requires credentials.json — download from Google "
                  "Cloud Console and run: police-thief authorize")
            return 2
        if not Path("token.json").exists():
            print("counted mode requires token.json — run: police-thief authorize")
            return 2
    my_port = args.my_port or (8801 if args.role == "police" else 8802)
    peer = ReferenceSeriesPeer(
        natural_role=args.role, config=cfg, opponent_url=args.opponent_url,
        my_port=my_port, num_games=args.games, mode=args.mode,
        alternate_roles=not args.no_alternate_roles,
        handshake_per_sub_game=not args.no_handshake_per_sub_game,
        turn_timeout=args.turn_timeout, out_dir=args.out, seed=args.seed,
        mcp_url=args.mcp_url, spec_profile=spec_profile,
        git_commit_hash=getattr(args, "git_commit", ""),
        game_id_override=getattr(args, "game_id", None))
    peer.start_server()
    import time as _time
    while True:
        try:
            result = peer.run_series()
        except Exception as exc:
            print(json.dumps({"mode": args.mode, "error": str(exc), "passed": False}),
                  flush=True)
            if args.mode != "friendly":
                return 1
            _time.sleep(5)
            peer.reset_for_next_series()
            continue
        passed = result["all_audits_verified"] and result["num_sub_games"] == args.games
        if args.mode == "counted":
            rpt = result.get("report_status", {})
            rpt_status = rpt.get("status", "unknown")
            if rpt_status != "sent":
                print(json.dumps({"mode": args.mode, "passed": False,
                                  "report_status": rpt_status,
                                  "error": rpt.get("error") or "email not sent",
                                  "totals": result["totals"],
                                  "series_winner": result["series_winner"]}))
                return 1
        print(json.dumps({"mode": args.mode, "passed": passed,
                          "totals": result["totals"],
                          "series_winner": result["series_winner"],
                          "result_sha256": result["result_sha256"]}), flush=True)
        if args.mode != "friendly":
            return 0 if passed else 1
        _time.sleep(5)
        peer.reset_for_next_series()


def cmd_authorize(credentials_path: str = "credentials.json",
                  token_path: str = "token.json") -> int:
    """Interactive OAuth consent — run once to create token.json for counted matches."""
    cpath = Path(credentials_path)
    if not cpath.exists():
        print(f"credentials.json not found at {cpath.resolve()}")
        print("Get it from: Google Cloud Console → APIs & Services → Credentials "
              "→ Create OAuth 2.0 Client ID (Desktop App) → Download JSON")
        return 1
    from police_thief.infra.email_sender import SCOPES
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("google-auth-oauthlib not installed — run: uv sync")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(cpath), SCOPES)
    creds = flow.run_local_server(
        port=0, open_browser=True,
        authorization_prompt_message="Open this URL to authorize Gmail send:\n{url}")
    Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    print(f"token.json written — Gmail gmail.send scope authorized")
    return 0


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


