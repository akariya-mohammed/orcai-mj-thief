"""Pre-game negotiation logic (task 5.3, Book Ch. 2 + appendix ב).

Pure evaluation — no I/O. Each peer presents {config signature, identity, role};
play begins only when BOTH sides verify a byte-identical shared contract and
complementary roles. Any mismatch refuses loudly: a game on divergent physics
is void before it starts (Rule 11).

Turn order: the THIEF always moves first (Intel I3, relayed/provisional —
matches our simulation convention; enforced structurally by the runner).
"""
from __future__ import annotations

REQUIRED_FIELDS = ("config_sha256", "group_id", "role", "code_version",
                   "step0_commit", "sealing_scheme")
ROLES = ("police", "thief")
FIRST_MOVER = "thief"


def build_payload(config_sha256: str, group_id: str, role: str,
                  code_version: str = "0.0.0", step0_commit: str = "",
                  sealing_scheme: str = "") -> dict:
    return {"config_sha256": config_sha256, "group_id": group_id,
            "role": role, "code_version": code_version,
            "step0_commit": step0_commit, "sealing_scheme": sealing_scheme}


def evaluate(mine: dict, theirs: dict) -> tuple[bool, str]:
    """(accepted, reason). Tolerant of malformed input — refuse politely, never crash."""
    if not isinstance(theirs, dict):
        return False, "missing payload"
    for field in REQUIRED_FIELDS:
        if field not in theirs:
            return False, f"missing field: {field}"
    if theirs["role"] not in ROLES:
        return False, f"unknown role: {theirs['role']}"
    if theirs["role"] == mine["role"]:
        return False, f"role conflict: both sides claim {mine['role']}"
    if not theirs.get("step0_commit"):
        return False, "no Step-0 declaration: hardware and code version must be sealed"
    if theirs["sealing_scheme"] != mine["sealing_scheme"]:
        return False, (f"sealing scheme mismatch: ours {mine['sealing_scheme']!r}, "
                       f"theirs {theirs['sealing_scheme']!r} — audits could not verify")
    if theirs["config_sha256"] != mine["config_sha256"]:
        return False, ("config mismatch: contracts are not byte-identical "
                       f"(mine {mine['config_sha256'][:12]}…, "
                       f"theirs {theirs['config_sha256'][:12]}…)")
    return True, "ok"
