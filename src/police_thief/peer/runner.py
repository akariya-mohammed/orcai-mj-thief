"""PeerProcess — assembles Config -> server -> runtime -> link into one living peer
(task 5.3). This is the process a student launches in each terminal.

Turn order is structural (Intel I3, provisional): the THIEF acts first; the
POLICE waits for the first incoming TurnMessage. Game termination protocol
(capture claims / win handling, task 6.4) is available in domain/termination.py.
"""
from __future__ import annotations

import random
import threading
from pathlib import Path

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Role
from police_thief.domain.game_ids import make_game_id, make_game_uid
from police_thief.domain.negotiation import FIRST_MOVER, build_payload, evaluate
from police_thief.domain.own_state import OwnGameState
from police_thief.infra.mcp_client import OpponentLink
from police_thief.peer.finish import deliver_verdict
from police_thief.peer.handshake import perform_handshake
from police_thief.peer.runtime import PeerRuntime
from police_thief.peer.sealing import SEALING_SCHEME, step_zero_record
from police_thief.strategy.heuristic import RingRunnerThief
from police_thief.strategy.trapping import TrapperPolice
from police_thief.strategy.trash_talk import TemplateProvider


class PeerProcess:
    def __init__(self, role: str, config) -> None:
        self.role_name = role
        self.config = config
        size = config.get("board.size", 7)
        start = tuple(config.get(f"positions.{'cop' if role == 'police' else 'thief'}_start",
                                 (0, 0) if role == "police" else (3, 3)))
        brain = TrapperPolice() if role == "police" else RingRunnerThief()
        belief = BeliefGrid(size, config.get("belief.smell_trust_weight", 4.0))
        self.link = OpponentLink(config.get("network.opponent_url"))
        self.runtime = PeerRuntime(
            Role.POLICE if role == "police" else Role.THIEF, brain, self.link,
            OwnGameState(start, Board(size)), belief, config,
            talker=TemplateProvider(size, random.Random(config.get("game.seed", 0))))
        self.my_port = config.get("network.my_port", 8801 if role == "police" else 8802)
        # The SIGNED contract governs the wait (Rule 11): lenient invites stalling,
        # stricter risks a false accusation. Neither is ours to choose.
        self.turn_timeout = config.get("network_and_league.response_timeout_sec", 30)
        self.group_id = config.get("game.group_id", f"unknown-{role}")
        self.turn_ready = threading.Event()
        self.step_zero = step_zero_record(   # Rule 24/53: sealed BEFORE turn 1
            config.get("game.group_name", self.group_id),
            config.get("trash_talk.provider", "template"))
        self.runtime.records.append(self.step_zero)
        self.peer_identity: dict | None = None
        self.game_uid: str | None = None

    # ── protocol surface ─────────────────────────────────────────────────────
    @property
    def acts_first(self) -> bool:
        return self.role_name == FIRST_MOVER

    def handshake_payload(self) -> dict:
        return build_payload(self.config.config_sha256(), self.group_id, self.role_name,
                             code_version=self.step_zero["payload"]["code_version"],
                             step0_commit=self.step_zero["commit"],
                             sealing_scheme=SEALING_SCHEME)

    def on_handshake(self, payload: dict) -> dict:
        accepted, reason = evaluate(self.handshake_payload(), payload)
        if accepted:
            self._bind_peer(payload)
        return {**self.handshake_payload(), "accepted": accepted, "reason": reason}

    def _bind_peer(self, payload: dict) -> None:
        self.peer_identity = payload
        self.game_uid = make_game_uid(self.group_id, payload["group_id"],
                                      self.config.config_sha256())

    def _on_turn(self, message: dict) -> dict:
        """Server-thread entry point: this must NEVER raise into the MCP layer."""
        try:
            ack = self.runtime.on_opponent_turn(message)
        except Exception as exc:                       # last-resort net (never crash)
            ack = self.runtime.violations.reject(f"handler error: {exc}", message,
                                                 self.runtime.phases)
        self.turn_ready.set()
        return ack

    def _technical_loss(self, reason: str, out_dir="logs", at_fault="opponent") -> None:
        from police_thief.peer.finish import declare_technical_loss
        declare_technical_loss(self, reason, out_dir, at_fault)

    # ── live process (manual two-terminal gate; threads + network) ───────────
    def run(self, max_turns: int | None = None) -> None:
        from police_thief.infra.mcp_server import build_server   # lazy fastmcp

        _, serve = build_server(f"police_thief_{self.role_name}", self._on_turn,
                                self.on_handshake, host="0.0.0.0", port=self.my_port)
        threading.Thread(target=serve, daemon=True).start()
        print(f"[{self.role_name}] serving on port {self.my_port}; "
              f"contract {self.config.config_sha256()[:12]}…")

        reply = perform_handshake(self.link, self.handshake_payload())
        self._bind_peer(reply)
        game_id = make_game_id(self.group_id, reply["group_id"])
        print(f"[{self.role_name}] handshake OK with {reply['group_id']} — "
              f"game {game_id} uid {self.game_uid} — thief moves first")

        from police_thief.peer.watchdog import Watchdog
        watchdog = Watchdog(
            timeout_sec=self.config.get("network_and_league.watchdog_timeout_sec", 60),
            on_freeze=lambda: print(f"[{self.role_name}] WATCHDOG: main loop frozen"))
        watchdog.start()

        turns = max_turns or self.config.get("rules.max_steps", 35)
        if self.acts_first:
            self.runtime.run_turn()
            print(f"[{self.role_name}] turn 1 sent")
        for turn in range(1, turns + 1):
            watchdog.beat()
            if not self.turn_ready.wait(timeout=self.turn_timeout):
                self._technical_loss(
                    f"opponent exceeded the signed {self.turn_timeout}s response window")
                watchdog.stop()
                return
            self.turn_ready.clear()
            if self.runtime.violations.exhausted:      # strike limit hit on the wire
                self._technical_loss(
                    f"opponent sent {self.runtime.violations.limit} malformed messages")
                watchdog.stop()
                return
            if self.runtime.is_over:               # consensus reached while we waited
                deliver_verdict(self.runtime)      # answer them before leaving
                break
            self.runtime.run_turn()
            print(f"[{self.role_name}] turn exchanged "
                  f"(pos={self.runtime.state.position}, trust={self.runtime.trust_ema:.2f})")
            if self.runtime.is_over:
                break
        watchdog.stop()
        self._conclude(turns)

    def _conclude(self, turns: int) -> None:
        """End by protocol consensus where we have it; never claim more than we know."""
        outcome = self.runtime.outcome
        if outcome:
            print(f"[{self.role_name}] GAME OVER by consensus: {outcome['type']} "
                  f"(winner: {outcome['winner']}, step {outcome['step']})")
        else:
            print(f"[{self.role_name}] stopped after {turns} turns with no terminal "
                  "consensus — no result is claimed")
