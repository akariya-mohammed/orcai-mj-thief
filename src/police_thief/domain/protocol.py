"""The turn message exchanged between peers (Book Ch. 2; reference build_turn_message).

Per commit-reveal: the message carries the sealed `commit` (a SHA-256 hash) and the verbal
`hint` (which may be a lie) — NOT the move or nonce, which are revealed later. Coordinates in
the protocol are never sent as bare numbers to the opponent as the move (Rule 27); the scent
grid is spatial data, keyed "r,c" for JSON transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from police_thief.exceptions import ProtocolViolation

Cell = tuple[int, int]

ROLES = ("police", "thief")
_HEX = set("0123456789abcdef")
# Flood guards: a legal hint is <=15 words and a 7x7 board holds 49 scent cells,
# so these ceilings cannot reject a lawful message — they only stop resource abuse.
MAX_HINT_CHARS = 1000
MAX_SCENT_CELLS = 4096
MAX_COORD = 64            # generous board-size ceiling for coordinate sanity checks


def _scent_to_wire(scent: dict[Cell, float]) -> dict[str, float]:
    return {f"{r},{c}": v for (r, c), v in scent.items()}


def _scent_from_wire(d: dict) -> dict[Cell, float]:
    """Defensive parse: wire data is opponent-controlled — drop malformed entries,
    never crash the receive path on them."""
    out: dict[Cell, float] = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        try:
            r, c = k.split(",")
            out[(int(r), int(c))] = float(v)
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def _cell_or_none(value, field_name: str, size: int = MAX_COORD) -> list | None:
    """Validate an optional [row, col] wire field — opponent-controlled input."""
    if value is None:
        return None
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)
            or not all(0 <= v < size for v in value)):
        raise ProtocolViolation(f"{field_name} must be [row, col] within the board")
    return list(value)


@dataclass
class TurnMessage:
    role: str                         # "police" | "thief"
    commit: str                       # SHA-256 of the sealed move (reveal comes later)
    hint: str = ""                    # free-text verbal hint (may be a bluff)
    scent: dict[Cell, float] = field(default_factory=dict)
    barrier: list | None = None            # [r, c] walled THIS turn — Rule 15: always declared
    capture_claim: list | None = None      # cop only: [r, c] it claims to have captured on
    claim_response: dict | None = None     # response to the opponent's prior capture claim
    win_claim: dict | None = None          # {"type": ...} when a terminal result is asserted

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "commit": self.commit,
            "hint": self.hint,
            "scent": _scent_to_wire(self.scent),
            "barrier": self.barrier,
            "capture_claim": self.capture_claim,
            "claim_response": self.claim_response,
            "win_claim": self.win_claim,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TurnMessage":
        """Parse an OPPONENT-CONTROLLED envelope. Every rejection is a named
        ProtocolViolation — the caller records a strike; nothing here may raise
        an unhandled exception, because a crashed peer forfeits the match."""
        if not isinstance(d, dict):
            raise ProtocolViolation(f"envelope is {type(d).__name__}, expected object")
        for key in ("role", "commit"):
            if key not in d:
                raise ProtocolViolation(f"missing required field: {key}")
        role, commit = d["role"], d["commit"]
        if not isinstance(role, str) or role not in ROLES:
            raise ProtocolViolation(f"invalid role: {role!r}")
        if (not isinstance(commit, str) or len(commit) != 64
                or not set(commit.lower()) <= _HEX):
            raise ProtocolViolation("commit is not a 64-hex SHA-256 digest")
        hint = d.get("hint", "")
        if not isinstance(hint, str):
            raise ProtocolViolation(f"hint must be a string, got {type(hint).__name__}")
        if len(hint) > MAX_HINT_CHARS:
            raise ProtocolViolation(f"hint exceeds {MAX_HINT_CHARS} chars (flood guard)")
        scent = d.get("scent", {})
        if isinstance(scent, dict) and len(scent) > MAX_SCENT_CELLS:
            raise ProtocolViolation(f"scent exceeds {MAX_SCENT_CELLS} cells (flood guard)")
        return cls(
            role=role, commit=commit, hint=hint, scent=_scent_from_wire(scent),
            barrier=_cell_or_none(d.get("barrier"), "barrier"),
            capture_claim=d.get("capture_claim"),
            claim_response=d.get("claim_response"),
            win_claim=d.get("win_claim"),
        )


def build_turn_message(role, hint, scent, commit, capture_claim=None,
                       claim_response=None, win_claim=None,
                       barrier=None) -> TurnMessage:
    """Assemble the outgoing turn message (mirrors the reference signature)."""
    return TurnMessage(
        role=role, commit=commit, hint=hint, scent=dict(scent), barrier=barrier,
        capture_claim=capture_claim, claim_response=claim_response, win_claim=win_claim,
    )
