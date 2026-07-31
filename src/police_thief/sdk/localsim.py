"""Headless local simulation over the REAL peer runtimes (task 4.11).

DEV/EVAL ONLY — never a league mode: the harness referees with true positions,
which no peer may do in real play. Both sides run the full production path
(run_turn -> wire message -> on_opponent_turn): decaying scent, belief fusion,
template hints, lie detection, forced-capture search. No perfect-info shortcut.
The Board instance is shared because barriers are public by rule (declared,
Rule 15); positions are the hidden state and never cross the loopback.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from police_thief.domain import rules
from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Role
from police_thief.domain.own_state import OwnGameState
from police_thief.peer.runtime import PeerRuntime
from police_thief.strategy.heuristic import RingRunnerThief
from police_thief.strategy.trapping import TrapperPolice
from police_thief.strategy.trash_talk import TemplateProvider


@dataclass
class MatchOutcome:
    result: str            # "capture" | "survival"
    steps: int
    cop_trust: float       # cop's final trust in the thief's words
    lies_caught: int
    truths_confirmed: int

    def __str__(self) -> str:
        return (f"{self.result} in {self.steps} steps "
                f"(trust={self.cop_trust:.2f}, lies={self.lies_caught})")


@dataclass
class BatchStats:
    games: int
    captures: int
    capture_rate: float
    avg_steps: float
    lies_caught: int
    truths_confirmed: int


class _Loopback:
    """In-process transport: deliver the wire dict straight to the other peer."""
    def __init__(self) -> None:
        self.other: PeerRuntime | None = None

    def send_turn(self, message: dict) -> dict:
        return self.other.on_opponent_turn(message)


def run_scent_match(cop_start, thief_start=(3, 3), seed: int = 0,
                    max_steps: int = 35, size: int = 7,
                    observer=None, chatty_thief: bool = False) -> MatchOutcome:
    """observer(step, cop_runtime, thief_runtime) is called after each full turn —
    used by the docs-image generator and future eval hooks. chatty_thief models a
    talkative league opponent, so our lie detector can be exercised end-to-end."""
    board = Board(size)
    link_c, link_t = _Loopback(), _Loopback()
    cop = PeerRuntime(Role.POLICE, TrapperPolice(), link_c,
                      OwnGameState(cop_start, board), BeliefGrid(size), config={},
                      talker=TemplateProvider(size, random.Random(seed)))
    thief = PeerRuntime(Role.THIEF, RingRunnerThief(), link_t,
                        OwnGameState(thief_start, board), BeliefGrid(size), config={},
                        talker=TemplateProvider(size, random.Random(seed + 1000),
                                                always_speak=chatty_thief))
    link_c.other, link_t.other = thief, cop

    lies = truths = 0
    for step in range(1, max_steps + 1):
        thief.run_turn()
        if cop.last_hint_verdict == "lie":
            lies += 1
        elif cop.last_hint_verdict == "truth":
            truths += 1
        if rules.resolve(cop.state.position, thief.state.position,
                         board, step, 99) == rules.CAPTURE:
            return MatchOutcome("capture", step, cop.trust_ema, lies, truths)
        cop.run_turn()
        if observer is not None:
            observer(step, cop, thief)
        if rules.resolve(cop.state.position, thief.state.position,
                         board, step, 99) == rules.CAPTURE:
            return MatchOutcome("capture", step, cop.trust_ema, lies, truths)
    return MatchOutcome("survival", max_steps, cop.trust_ema, lies, truths)


def run_batch(starts, seeds=(1,), thief_start=(3, 3),
              chatty_thief: bool = False) -> BatchStats:
    outcomes = [run_scent_match(s, thief_start, seed=sd, chatty_thief=chatty_thief)
                for s in starts for sd in seeds]
    caps = [o for o in outcomes if o.result == "capture"]
    return BatchStats(
        games=len(outcomes), captures=len(caps),
        capture_rate=len(caps) / len(outcomes),
        avg_steps=(sum(o.steps for o in caps) / len(caps)) if caps else float("inf"),
        lies_caught=sum(o.lies_caught for o in outcomes),
        truths_confirmed=sum(o.truths_confirmed for o in outcomes),
    )
