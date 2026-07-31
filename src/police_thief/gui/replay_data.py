"""Replay verification engine (task 7.4, Book Ch. 7) — data layer, ZERO Tk imports.

Two tamper layers, both required by the mutual-audit rule:
1. per-record: recompute the sealed commitment from the revealed fields + nonce —
   any rewritten move/state/intent/hint mismatches its SHA-256 (crypto.verify);
2. consensus: the whole record SET must hash to the mutual_agreement signature
   both peers confirmed — catches wholesale swaps of individually-valid records.
The verdict is binary and machine-decidable: "there is no almost-matching"
(Book Ch. 7). The visual viewer (task 7.3) consumes this module unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from police_thief.domain.crypto import verify
from police_thief.shared.config import canonical_sha256

VERIFIED = "Verified OK"
TAMPERED = "TAMPERED"


def verify_step(record: dict) -> str:
    """Re-seal one revealed record and compare to its committed hash."""
    ok = verify(record.get("state", ""), record.get("move", ""),
                record.get("intent", ""), record.get("nonce", ""),
                record.get("commit", ""))
    return VERIFIED if ok else TAMPERED


def verify_log(log_artifact: dict) -> tuple[str, dict]:
    """Full audit of a log artifact. Returns (verdict, detail).

    detail: {"steps_checked": n} on success;
            {"step": i, "layer": "record"|"consensus"} on the first tamper.
    """
    records = log_artifact.get("records", [])
    for i, record in enumerate(records, start=1):
        if verify_step(record) == TAMPERED:
            return TAMPERED, {"step": i, "layer": "record"}
    agreed = log_artifact.get("mutual_agreement", {}).get("sha256")
    if agreed != canonical_sha256(records):
        return TAMPERED, {"step": None, "layer": "consensus"}
    return VERIFIED, {"steps_checked": len(records)}


def load_log(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
