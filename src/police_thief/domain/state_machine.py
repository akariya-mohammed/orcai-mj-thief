"""Per-turn game phase machine (Rules 4-5, Book Ch. 8).

Only legal transitions are allowed; any illegal jump raises immediately at
DEVELOPMENT time (a loud bug) instead of silently deadlocking at GAME time.
A disconnected opponent routes cleanly to TECHNICAL_LOSS, never an infinite wait.
"""
from __future__ import annotations


class GamePhaseMachine:
    # Each state maps to its set of legal successor states.
    TRANSITIONS: dict[str, set[str]] = {
        # WAITING is a communication phase: a silent opponent must be able to
        # resolve to TECHNICAL_LOSS (book Fig. 11 error edges; Rules 6-7).
        "WAITING_FOR_OPPONENT": {"COMPUTING_MOVE", "TECHNICAL_LOSS"},
        "COMPUTING_MOVE": {"COMMITTING", "TECHNICAL_LOSS"},
        # A protocol violation can be discovered on the receive thread at ANY
        # live phase, so every non-terminal state keeps the TECHNICAL_LOSS edge.
        "COMMITTING": {"AWAITING_REVEAL", "TECHNICAL_LOSS"},
        "AWAITING_REVEAL": {"VERIFYING", "TECHNICAL_LOSS"},
        "VERIFYING": {"WAITING_FOR_OPPONENT", "TECHNICAL_LOSS"},
        "TECHNICAL_LOSS": set(),  # terminal
    }

    def __init__(self) -> None:
        self.state = "WAITING_FOR_OPPONENT"

    def transition(self, target: str) -> str:
        if target not in self.TRANSITIONS[self.state]:
            raise ValueError(f"Illegal transition: {self.state} -> {target}")
        self.state = target
        return self.state
