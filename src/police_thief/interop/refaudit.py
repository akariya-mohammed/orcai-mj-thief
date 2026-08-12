"""End-of-sub-game audit of a reference-dialect disclosure.

Mirrors what the opponent's `infra/interop_audit.py` verifies about US, applied
symmetrically to THEIR revealed log:

1. every ``{payload, nonce, commit}`` record still binds to its commitment;
2. every commitment we witnessed live is actually revealed (no withheld step);
3. the revealed trajectory is physically continuous and on the board;
4. the barrier quota is respected.

Their step payloads carry ``pos_before``/``pos_after``; ours carry
``position`` — both shapes are read.
"""
from __future__ import annotations

from typing import Any

from police_thief.interop.refcrypto import verify_record

VERIFIED_OK = "Verified OK"
TAMPERED = "TAMPERED"


def _positions(records: list[dict[str, Any]]) -> list[tuple[int, list[int]]]:
    """(step, position) for every step record that declares one, in step order."""
    found: list[tuple[int, list[int]]] = []
    for record in records:
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        pos = payload.get("position") or payload.get("pos_after")
        if pos is not None:
            found.append((payload.get("step", -1), list(pos)))
    return sorted(found)


def audit_reference_log(records: list[dict[str, Any]], live_hashes: list[str], *,
                        grid_size: int,
                        barriers_max: int | None = None) -> tuple[str, list[str]]:
    """Verify a revealed reference-format log against live commitments."""
    violations: list[str] = []

    for index, record in enumerate(records):
        if not isinstance(record, dict) or \
                not {"payload", "nonce", "commit"} <= set(record):
            violations.append(f"record {index}: not a sealed {{payload, nonce, commit}}")
        elif not verify_record(record):
            violations.append(f"record {index}: hash mismatch (tampering)")

    revealed = {record.get("commit") for record in records if isinstance(record, dict)}
    for commit in live_hashes:
        if commit not in revealed:
            violations.append(f"commitment {commit[:16]}... was sent but never revealed")

    previous: list[int] | None = None
    for step, position in _positions(records):
        if not all(isinstance(a, int) and 0 <= a < grid_size for a in position):
            violations.append(f"step {step}: position {position} is off the board")
        elif previous is not None:
            distance = abs(position[0] - previous[0]) + abs(position[1] - previous[1])
            if distance > 1:
                violations.append(
                    f"step {step}: jumped {previous} -> {position} in one move")
        previous = position

    if barriers_max is not None:
        placed = [r["payload"].get("barrier") for r in records
                  if isinstance(r, dict) and isinstance(r.get("payload"), dict)
                  and r["payload"].get("barrier")]
        if len(placed) > barriers_max:
            violations.append(
                f"{len(placed)} barriers placed, quota is {barriers_max}")

    return (VERIFIED_OK, []) if not violations else (TAMPERED, violations)
