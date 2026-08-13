"""Reference-dialect commit/reveal primitives.

The reference digest differs from our native `canonical-json-v1` scheme
(domain/crypto.py): the nonce lives OUTSIDE the JSON —
``commit = sha256(canonical(payload) + b"|" + nonce_utf8)`` — and canonical
JSON uses ``ensure_ascii=False``. Both formulas are equally binding; only the
composition differs, and both peers must use the same one for the final audit
to verify. This module is the single source of truth for every reference-
dialect digest in the system.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

NONCE_HEX_BYTES = 16


def canonical_bytes(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, tight separators, UTF-8, ensure_ascii=False."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(obj: Any) -> str:
    """SHA-256 hex of the canonical form — used for the config lock and results."""
    return sha256_hex(canonical_bytes(obj))


def new_nonce() -> str:
    return secrets.token_hex(NONCE_HEX_BYTES)


def reference_commit(payload: dict[str, Any], nonce: str) -> str:
    """The reference commitment over a nonce-free payload."""
    return sha256_hex(canonical_bytes(payload) + b"|" + nonce.encode("utf-8"))


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    """Seal one payload: returns the audit-ready ``{payload, nonce, commit}`` record.

    Only ``commit`` travels during play; ``payload`` and ``nonce`` stay private
    until the end-of-sub-game ``submit_audit`` disclosure.
    """
    nonce = new_nonce()
    return {"payload": dict(payload), "nonce": nonce,
            "commit": reference_commit(payload, nonce)}


def mutual_digest(doc: dict) -> str:
    """Shared cross-team outcome digest agreed with ahk-yosi.

    Uses json.dumps(doc, sort_keys=True) with Python DEFAULT separators
    (', ' and ': ') so both teams produce byte-identical output regardless
    of dict insertion order. Our private result_sha256 continues to use
    tight-separator canonical JSON via digest(); this function is exclusively
    for the mutual_agreement.sha256 field.
    """
    return sha256_hex(json.dumps(doc, sort_keys=True).encode("utf-8"))


def verify_record(record: dict[str, Any]) -> bool:
    """Re-hash one revealed ``{payload, nonce, commit}`` record (timing-safe)."""
    try:
        return secrets.compare_digest(
            reference_commit(record["payload"], record["nonce"]), record["commit"])
    except (KeyError, TypeError, AttributeError):
        return False
