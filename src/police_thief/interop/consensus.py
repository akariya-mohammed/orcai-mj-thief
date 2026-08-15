"""Spec-exact series-consensus primitives for the amireman public interop spec.

This module implements Appendix B, Section 10 (step 3) and Section 11 of
NEXT_OPPONENT_INTEROP_GUIDE_PUBLIC.md *verbatim* and is deliberately kept
separate from the ahk-yosi ``refcrypto.mutual_digest`` path (which uses Python
DEFAULT json separators and a different object shape). Do NOT route ahk-yosi
through here — its golden vector would break.

Differences from the ahk-yosi dialect that make this a distinct code path:

* ``game_id`` is the two group ids **sorted** and joined by the literal
  ``"-vs-"`` (Section 3 / Appendix B), never perspective-ordered.
* ``game_uid`` is a UUID built from the FIRST 16 raw bytes of
  ``SHA-256(canonical(terms) + "|" + "|".join(sorted(groups)))`` — a UUID
  string, not a truncated hex digest, and computed over ``canonical(terms)``,
  not over a config document (Appendix B).
* The consensus object has EXACTLY three top-level keys and five keys per row,
  hashed with tight separators (Section 11).
* The end-of-series envelope carries ``result_claim = "series_consensus"``,
  ``records = []`` and a 64-lowercase-hex ``consensus_sha`` (Section 10 step 3).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

WIRE_ROLES = ("police", "thief")
SERIES_CONSENSUS = "series_consensus"
_HEX_LOWER = set("0123456789abcdef")


def canonical(obj: Any) -> str:
    """The one canonical JSON form used for every hash in the spec (Appendix B)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -- shared ids (Section 3 / Appendix B) -------------------------------------
def spec_game_id(group_a: str, group_b: str) -> str:
    """Two group ids sorted and joined by the literal ``"-vs-"``."""
    a, b = sorted((group_a, group_b))
    return f"{a}-vs-{b}"


def spec_game_uid(terms: dict[str, Any], group_a: str, group_b: str) -> str:
    """UUID from the first 16 bytes of SHA-256 over canonical(terms)+"|"+groups.

    Mirrors Appendix B exactly::

        seed   = canonical(terms) + "|" + "|".join(sorted(pair))
        digest = sha256(seed.encode()).digest()      # 32 RAW bytes
        game_uid = str(uuid.UUID(bytes=digest[:16]))  # FIRST 16 bytes
    """
    pair = sorted((group_a, group_b))
    seed = canonical(terms) + "|" + "|".join(pair)
    raw = hashlib.sha256(seed.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=raw[:16]))


# -- canonical consensus object (Section 11) ---------------------------------
def consensus_row(*, sub_game_number: int, result: str,
                  roles: dict[str, str], score: dict[str, int],
                  winner_group: str | None) -> dict[str, Any]:
    """One sub-game row — EXACTLY five keys, group-keyed roles/score."""
    return {
        "sub_game_number": int(sub_game_number),
        "result": result,
        "roles": dict(roles),
        "score": dict(score),
        "winner_group": winner_group,
    }


def build_consensus_object(game_id: str, game_uid: str,
                           rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-level object — EXACTLY three keys, rows ordered by sub_game_number."""
    ordered = sorted(rows, key=lambda r: r["sub_game_number"])
    return {"game_id": game_id, "game_uid": game_uid, "sub_games": ordered}


def consensus_sha(consensus_obj: dict[str, Any]) -> str:
    """SHA-256 hex of canonical(consensus_obj) — 64 lowercase hex (Section 11)."""
    return sha256_hex(canonical(consensus_obj))


# -- explicit consensus envelope (Section 10 step 3) -------------------------
def build_consensus_envelope(sender_role: str, sha: str) -> dict[str, Any]:
    """The ``submit_audit`` envelope announcing our series digest."""
    if sender_role not in WIRE_ROLES:
        raise ValueError(f"sender must be a wire role, got {sender_role!r}")
    return {
        "sender": sender_role,
        "records": [],
        "result_claim": SERIES_CONSENSUS,
        "consensus_sha": sha,
    }


def is_valid_consensus_sha(value: Any) -> bool:
    """Exactly 64 lowercase hex characters (Section 9 / Section 10)."""
    return (isinstance(value, str) and len(value) == 64
            and set(value) <= _HEX_LOWER)


def validate_remote_consensus(envelope: Any) -> tuple[bool, str]:
    """(accepted, reason) for a remote consensus envelope, per Section 10 step 3.

    Accept ONLY if all hold: ``result_claim == "series_consensus"``,
    ``records == []``, ``consensus_sha`` present and exactly 64 lowercase hex,
    and ``sender`` is a wire role. A straggler per-sub-game audit (no
    ``consensus_sha``) MUST NOT be mistaken for a consensus envelope. Because
    roles alternate, EITHER of the remote peer's two wire roles is acceptable.
    """
    if not isinstance(envelope, dict):
        return False, "envelope is not an object"
    if envelope.get("result_claim") != SERIES_CONSENSUS:
        return False, "result_claim is not 'series_consensus'"
    if envelope.get("records") != []:
        return False, "records is not empty"
    if not is_valid_consensus_sha(envelope.get("consensus_sha")):
        return False, "consensus_sha is not 64 lowercase hex"
    if envelope.get("sender") not in WIRE_ROLES:
        return False, "sender is not a wire role"
    return True, "ok"
