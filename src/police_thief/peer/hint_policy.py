"""How a received hint moves our belief and our trust in the speaker (Book Ch. 4).

Asymmetric by design, because the two verdicts carry different information:

* a proven LIE is genuinely new evidence — the speaker contradicted the one
  signal they cannot fake, so the claimed region is suppressed hard;
* a proven TRUTH is mostly REDUNDANT with the scent that verified it, so the
  reward is confined to scent-backed cells (never empty ones) and kept modest.
  Rewarding a broad claim wholesale is how an opponent hijacks our argmax.
"""
from __future__ import annotations

from police_thief.domain.hints import (LIE, TRUTH, TRUTH_BOOST, judge_claim,
                                       parse_hint, supported_cells)

ALPHA = 0.3            # trust EMA responsiveness
DISTRUST_LINE = 0.35   # below this, unjudgeable claims are pre-emptively suppressed
LIE_FACTOR = 0.1       # suppression applied to a disproven region


def weigh(belief, hint: str, scent: dict, size: int,
          trust_ema: float) -> tuple[float, str | None]:
    """Apply one hint to `belief`; return (new trust_ema, verdict or None)."""
    claim = parse_hint(hint, size)
    if claim is None:                      # unparseable -> zero information
        return trust_ema, None
    verdict = judge_claim(claim.cells, scent)
    if verdict in (TRUTH, LIE):
        trust_ema = ALPHA * (1.0 if verdict is TRUTH else 0.0) + (1 - ALPHA) * trust_ema
    if verdict is LIE or (verdict not in (TRUTH, LIE) and trust_ema < DISTRUST_LINE):
        belief.penalize(claim.cells, factor=LIE_FACTOR)
    elif verdict is TRUTH:
        target = supported_cells(claim.cells, scent)
        if target:
            belief.penalize(target, factor=TRUTH_BOOST)   # factor >1 = boost
    return trust_ema, verdict
