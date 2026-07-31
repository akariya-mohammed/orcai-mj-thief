"""End-of-game reveal and mutual audit (task 6.3 wiring for 6.5).

Once both peers agree the game is over, each discloses its full history — every
nonce included — and audits the other's. Only now are nonces surrendered: that
is what makes the per-turn commitments binding rather than decorative. Every
verdict is written to disk, because a declaration without its evidence is an
accusation we cannot defend (Rules 19, 36).
"""
from __future__ import annotations

import json
from pathlib import Path

from police_thief.peer.audit import audit_opponent
from police_thief.peer.sealing import SEALING_SCHEME


def deliver_verdict(runtime) -> bool:
    """Send the answer we owe before leaving the table.

    The peer that CONFIRMS a terminal claim learns the game is over first. If it
    simply exits, the claimant is left waiting on a verdict that never arrives —
    observed live: the cop confirmed survival at step 35 and vanished. This ships
    the owed claim_response on its own, without pretending to take another turn.
    """
    owed = getattr(runtime, "_pending_response", None)
    if not owed:
        return False
    from police_thief.domain.protocol import build_turn_message
    last = runtime.records[-1]["commit"] if runtime.records else "0" * 64
    message = build_turn_message(runtime.role.value, "", {}, last,
                                 claim_response=owed)
    runtime.transport.send_turn(message.to_dict())
    runtime._pending_response = None
    return True


def disclosure(runtime, group_id: str) -> dict:
    """Everything the opponent needs to audit us — withheld until now."""
    return {"group_id": group_id, "role": runtime.role.value,
            "sealing_scheme": SEALING_SCHEME, "records": runtime.records,
            "start": list(runtime.start_position),
            "scent_broadcasts": [dict(s) for s in runtime.my_scent_history]}


def finalize(runtime, their: dict, *, config, out_dir="logs", game_uid=None) -> dict:
    """Audit their disclosure, persist the verdict, and report the result."""
    strict = their.get("scent_model") == config.get("scent_model")
    broadcasts = [{tuple(k) if isinstance(k, (list, tuple)) else k: v
                   for k, v in snap.items()} for snap in their.get("scent_broadcasts", [])]
    result = audit_opponent(
        [r for r in their.get("records", []) if r.get("step", 1) != 0],
        role=their.get("role", "thief"),
        start=tuple(their.get("start", (3, 3))),
        barriers_max=config.get("rules.barriers_max", 14),
        broadcasts=broadcasts or None,
        pheromones=config.get("pheromones", {}),
        size=config.get("board.size", 7), strict_scent=strict)

    verdict = {"game_uid": game_uid, "outcome": runtime.outcome,
               "opponent": their.get("group_id"), "audit": result,
               "at_fault": None if result["passed"] else their.get("group_id")}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"audit_{runtime.role.value}.json"
    path.write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    verdict["evidence_path"] = str(path)
    return verdict


def declare_technical_loss(process, reason: str, out_dir="logs",
                           at_fault="opponent") -> None:
    """Declare + persist evidence (Rules 6-7). at_fault records WHOSE breach it was;
    an unproven accusation is itself a violation, so the snapshot ships its proof."""
    runtime = process.runtime
    if runtime.phases.state != "TECHNICAL_LOSS":
        runtime.phases.transition("TECHNICAL_LOSS")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = {"role": process.role_name, "reason": reason, "at_fault": at_fault,
                "game_uid": process.game_uid, "group_id": process.group_id,
                "signed_timeout_sec": process.turn_timeout,
                "position": list(runtime.state.position),
                "trust_ema": runtime.trust_ema, "records": runtime.records,
                "violations": runtime.violations.evidence()}
    path = out / f"technical_loss_{process.role_name}.json"
    path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    print(f"[{process.role_name}] TECHNICAL_LOSS: {reason} — evidence at {path}")
