"""Reference-dialect TurnMessage — exact field set, defensively parsed.

The opponent's codec (`interop_codec.to_turn_message`) emits EXACTLY these
fields, and the original reference `TurnMessage.from_dict` does ``cls(**data)``
so an extra key is a TypeError on a reference peer: we emit exactly this set
and tolerate nothing less than {step, sender, commit} inbound.

    step, sender, hint, smell_grid, commit, timestamp,
    barrier_placed, capture_claim, claim_response, win_claim
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from police_thief.exceptions import ProtocolViolation

ROLES = ("police", "thief")
_HEX = set("0123456789abcdef")
MAX_HINT_CHARS = 1000
MAX_SCENT_CELLS = 4096

# Win-claim kinds accepted on the wire. The opponent's engine emits
# KIND_SURVIVAL_CLAIM = "survival_claim" (no step field) and, when its thief is
# captured by barrier/enclosure (#46/#47), KIND_CAPTURED_EVENT = "captured_event".
SURVIVAL_KINDS = ("survival", "survival_claim")
CAPTURED_KINDS = ("captured_event", "captured", "capture")


def scent_to_wire(scent: dict[tuple[int, int], float]) -> dict[str, float]:
    return {f"{r},{c}": v for (r, c), v in scent.items()}


def scent_from_wire(grid: Any) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    if not isinstance(grid, dict):
        return out
    for key, value in grid.items():
        try:
            r, c = str(key).split(",")
            out[(int(r), int(c))] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def build_turn(*, step: int, sender: str, hint: str,
               scent: dict[tuple[int, int], float], commit: str,
               barrier: list | None = None, capture_claim: list | None = None,
               claim_response: dict | None = None, win_claim: dict | None = None,
               timestamp: str | None = None) -> dict[str, Any]:
    return {
        "step": step,
        "sender": sender,
        "hint": hint,
        "smell_grid": scent_to_wire(scent),
        "commit": commit,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "barrier_placed": list(barrier) if barrier else None,
        "capture_claim": list(capture_claim) if capture_claim else None,
        "claim_response": claim_response,
        "win_claim": win_claim,
    }


def _cell_or_none(value: Any, name: str, size: int) -> list | None:
    if value is None:
        return None
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)
            or not all(0 <= v < size for v in value)):
        raise ProtocolViolation(f"{name} must be [row, col] within the board")
    return list(value)


def parse_turn(d: Any, *, grid_size: int) -> dict[str, Any]:
    """Validate an OPPONENT-CONTROLLED turn message; raises ProtocolViolation."""
    if not isinstance(d, dict):
        raise ProtocolViolation(f"turn is {type(d).__name__}, expected object")
    for key in ("step", "sender", "commit"):
        if key not in d:
            raise ProtocolViolation(f"missing required field: {key}")
    sender, commit, step = d["sender"], d["commit"], d["step"]
    if sender not in ROLES:
        raise ProtocolViolation(f"invalid sender: {sender!r}")
    if not isinstance(step, int) or isinstance(step, bool) or step < 0:
        raise ProtocolViolation(f"invalid step: {step!r}")
    if (not isinstance(commit, str) or len(commit) != 64
            or not set(commit.lower()) <= _HEX):
        raise ProtocolViolation("commit is not a 64-hex SHA-256 digest")
    hint = d.get("hint", "") or ""
    if not isinstance(hint, str) or len(hint) > MAX_HINT_CHARS:
        raise ProtocolViolation("hint is not a string within the flood guard")
    grid = d.get("smell_grid") or {}
    if isinstance(grid, dict) and len(grid) > MAX_SCENT_CELLS:
        raise ProtocolViolation("smell_grid exceeds the flood guard")
    claim_response = d.get("claim_response")
    if claim_response is not None and not isinstance(claim_response, dict):
        raise ProtocolViolation("claim_response must be an object")
    win_claim = d.get("win_claim")
    if win_claim is not None and not isinstance(win_claim, dict):
        raise ProtocolViolation("win_claim must be an object")
    return {
        "step": step,
        "sender": sender,
        "hint": hint,
        "scent": scent_from_wire(grid),
        "commit": commit,
        "barrier": _cell_or_none(d.get("barrier_placed"), "barrier_placed", grid_size),
        "capture_claim": _cell_or_none(d.get("capture_claim"), "capture_claim",
                                       grid_size),
        "claim_response": claim_response,
        "win_claim": win_claim,
    }
