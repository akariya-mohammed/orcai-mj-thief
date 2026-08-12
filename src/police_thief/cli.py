"""Command-line interface. No network/LLM imports at module level — bare-install safe.

Commands:
  peer     — run one live peer process (handshake + turn loop; --gui for the window)
  replay   — verify a match log: "Verified OK" (exit 0) or "TAMPERED" (exit 1)
  series   — local self-play series -> the 4 mandatory artifacts (Table 20)
  selftest — DEV TOOL: local sims (--scent = full production path). Never league modes.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="police-thief",
                                     description="Distributed Cops-and-Robbers peer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_peer = sub.add_parser("peer", help="run one live peer process")
    p_peer.add_argument("--role", required=True, choices=["police", "thief"])
    p_peer.add_argument("--config", default=None,
                        help="private toml (default: config/<role>/game.toml)")
    p_peer.add_argument("--turns", type=int, default=None)
    p_peer.add_argument("--gui", action="store_true",
                        help="live local-truth window (belief heatmap + banner)")

    p_replay = sub.add_parser("replay", help="replay + verify a match log (Stage 7)")
    p_replay.add_argument("--log", required=True)

    p_self = sub.add_parser("selftest", help="DEV TOOL: local self-play simulation")
    p_self.add_argument("--steps", type=int, default=15)
    p_self.add_argument("--scent", action="store_true",
                        help="full production path: scent-only belief + hints + traps")
    p_self.add_argument("--games", type=int, default=18)
    p_self.add_argument("--seed", type=int, default=1)

    p_interop = sub.add_parser(
        "interop", help="reference-dialect networked series (six sub-games)")
    p_interop.add_argument("--role", required=True, choices=["police", "thief"],
                           help="this peer's NATURAL role (alternates per sub-game)")
    p_interop.add_argument("--opponent-url", required=True,
                           help="the opponent's /mcp endpoint")
    p_interop.add_argument("--my-port", type=int, default=None)
    p_interop.add_argument("--games", type=int, default=6)
    p_interop.add_argument("--mode", choices=["friendly", "counted"],
                           default="friendly")
    p_interop.add_argument("--out", default="artifacts/interop")
    p_interop.add_argument("--seed", type=int, default=0)
    p_interop.add_argument("--turn-timeout", type=float, default=180.0)
    p_interop.add_argument("--no-alternate-roles", action="store_true")
    p_interop.add_argument("--no-handshake-per-sub-game", action="store_true")
    p_interop.add_argument("--config", default=None,
                           help="private toml (default: config/<role>/game.toml)")
    p_interop.add_argument("--mcp-url", default=None,
                           help="our public /mcp URL, for the identity block")

    p_series = sub.add_parser("series", help="run a local self-play series -> 4 artifacts")
    p_series.add_argument("--games", type=int, default=None)
    p_series.add_argument("--seed", type=int, default=1)
    p_series.add_argument("--out", default="artifacts")
    p_series.add_argument("--email", action="store_true",
                          help="dispatch the report per [email] config (draft by default)")

    args = parser.parse_args(argv)

    if args.command == "selftest":
        from police_thief.cli_cmds import cmd_selftest, cmd_selftest_scent
        if args.scent:
            return cmd_selftest_scent(args.games, args.seed)
        return cmd_selftest(args.steps)
    if args.command == "series":
        from police_thief.sdk.series import SeriesRunner
        from police_thief.shared.config import Config
        cfg = Config.load(private_path="config/police/game.toml")
        summary = SeriesRunner(cfg, out_dir=args.out).run(num_games=args.games,
                                                          seed=args.seed)
        print(f"series {summary['game_id']}: totals={summary['totals']} "
              f"winner={summary['winner']} -> artifacts in {summary['out_dir']}")
        if args.email:
            from pathlib import Path

            from police_thief.domain.game_ids import artifact_filenames
            from police_thief.infra.email_sender import GmailSender
            names = artifact_filenames(summary["game_id"], 1)
            paths = {k: Path(summary["out_dir"]) / v for k, v in names.items()}
            print(f"email: {GmailSender(cfg).send_series_report(paths, summary)}")
        return 0
    if args.command == "interop":
        from police_thief.cli_cmds import cmd_interop
        return cmd_interop(args)
    if args.command == "peer":
        from police_thief.peer.runner import PeerProcess
        from police_thief.shared.config import Config
        private = args.config or f"config/{args.role}/game.toml"
        process = PeerProcess(args.role, Config.load(private_path=private))
        try:
            if args.gui:
                __import__("fastmcp")            # fail fast BEFORE opening a window
                from police_thief.gui.window import launch_live
                launch_live(process, args.turns)
                return 0
            process.run(max_turns=args.turns)
        except ImportError:
            print("fastmcp is not installed — run 'uv sync' first.", file=sys.stderr)
            return 2
        except (TimeoutError, Exception) as exc:
            print(f"peer aborted: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "replay":
        from police_thief.gui.replay_data import VERIFIED, load_log, verify_log
        verdict, detail = verify_log(load_log(args.log))
        print(f"{verdict} — {detail}")
        return 0 if verdict == VERIFIED else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
