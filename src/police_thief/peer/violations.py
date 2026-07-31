"""Protocol-violation tracking (P0 hardening; feeds the Stage-6 mutual audit).

An opponent's malformed message is DATA, not a crash: we reject it with a
reason, keep the raw payload as evidence, and count strikes. After STRIKE_LIMIT
violations the opponent has demonstrably broken the wire contract and we declare
the technical loss against them — with the preserved bytes as proof, because the
book penalises a FALSE accusation as harshly as a real violation.
"""
from __future__ import annotations

import logging

STRIKE_LIMIT = 3
RAW_CAP = 500          # keep evidence bounded: a flood must not fill our log


def _evidence_of(raw) -> str:
    text = repr(raw)
    return text[:RAW_CAP] + ("…" if len(text) > RAW_CAP else "")


class ViolationLog:
    """Strike counter + evidence trail for one opponent."""

    def __init__(self, limit: int = STRIKE_LIMIT) -> None:
        self.limit = limit
        self.strikes: list[dict] = []

    @property
    def exhausted(self) -> bool:
        return len(self.strikes) >= self.limit

    def reject(self, reason: str, raw, phases=None) -> dict:
        """Record a violation and build the reject-with-reason acknowledgement.

        When the strike limit is reached, drive the phase machine to
        TECHNICAL_LOSS so the game loop can wake up and declare.
        """
        self.strikes.append({"strike": len(self.strikes) + 1, "reason": reason,
                             "raw": _evidence_of(raw)})
        logging.getLogger(__name__).warning(
            "protocol violation %d/%d from opponent: %s",
            len(self.strikes), self.limit, reason)
        ack = {"status": "rejected", "reason": reason,
               "strike": len(self.strikes),
               "strikes_remaining": max(0, self.limit - len(self.strikes))}
        if self.exhausted:
            ack["opponent_technical_loss"] = True
            if phases is not None and phases.state != "TECHNICAL_LOSS":
                phases.transition("TECHNICAL_LOSS")
        return ack

    def evidence(self) -> dict:
        """Audit-ready record of everything the opponent sent that broke the contract."""
        return {"violation_count": len(self.strikes), "violations": self.strikes}
