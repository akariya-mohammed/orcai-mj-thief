"""SHA-256 commit-reveal sealing (Rules 17-19, Book Ch. 5).

Each move is sealed BEFORE its content is revealed, so a peer can prove it
picked a legal move without disclosing it early. Any post-hoc tampering is
caught in the final audit because the recomputed hash won't match.
"""
from __future__ import annotations

import hashlib
import json
import secrets


def _payload(state: str, move: str, intent: str, nonce: str) -> bytes:
    """Canonical JSON so BOTH peers hash byte-identical input.

    sort_keys + fixed separators guarantee the serialization is stable
    regardless of dict order or the language the opponent wrote their code in.
    """
    return json.dumps(
        {"state": state, "move": move, "intent": intent, "nonce": nonce},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def commit(state: str, move: str, intent: str) -> tuple[str, str]:
    """Return (h_commit, nonce). Send h_commit now; keep nonce secret until audit.

    intent is the honesty flag for the accompanying verbal hint: "truth" | "lie".
    A fresh cryptographic nonce defeats dictionary attacks over the small move space.
    """
    nonce = secrets.token_hex(16)
    h_commit = hashlib.sha256(_payload(state, move, intent, nonce)).hexdigest()
    return h_commit, nonce


def verify(state: str, move: str, intent: str, nonce: str, h_commit: str) -> bool:
    """Re-synthesize the opponent's hash from revealed data; any mismatch = tampering."""
    recomputed = hashlib.sha256(_payload(state, move, intent, nonce)).hexdigest()
    # constant-time comparison
    return secrets.compare_digest(recomputed, h_commit)
