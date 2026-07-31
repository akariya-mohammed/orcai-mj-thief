"""Verbal-hint parsing + scent-based claim judging (tasks 4.6-4.7, Book Ch. 4).

Zero dependencies: a lexicon matcher, not NLP. Hints are free natural language
(<=15 words) and NEVER contain coordinates (Rule 27 forbids numeric positions in
the protocol), so claims are coarse regions: compass directions (EN + HE) and
optional map-area landmarks supplied by the caller.

Judging follows the book's worked example: a verbal claim is checked against the
opponent's OWN scent snapshot — the one signal they cannot fake. Claim says
"north" while the scent mass sits south-east => lie. Thin early-game scent gives
UNKNOWN (never accuse without evidence).
"""
from __future__ import annotations

from dataclasses import dataclass

Cell = tuple[int, int]

TRUTH, LIE, UNKNOWN = "truth", "lie", "unknown"

# term -> (axis, side): axis 0 = rows, 1 = cols; side 0 = low half, 1 = high half
_DIRECTIONS = {
    "north": (0, 0), "south": (0, 1), "west": (1, 0), "east": (1, 1),
    "צפון": (0, 0), "דרום": (0, 1), "מערב": (1, 0), "מזרח": (1, 1),
}

# Judging thresholds (private tuning, not part of the signed contract):
MIN_TOTAL_SCENT = 0.5     # below this the evidence is too thin to judge
LIE_SHARE = 0.10          # claimed region holding <10% of the mass => lie
TRUTH_SHARE = 0.30        # claimed region must hold >30% of the mass...
SUPPORT_FLOOR = 0.5       # "scent-backed" = at least half the peak intensity
# Confinement is what makes a strong reward safe: TRUTH already requires the scent
# PEAK inside the claim, so every boosted cell is real evidence and no decoy can be
# amplified. Tuned empirically (capture rate 67% -> 100% across 5.0-8.0; 5.0 is the knee).
TRUTH_BOOST = 5.0


@dataclass(frozen=True)
class HintClaim:
    terms: frozenset
    cells: frozenset


def parse_hint(hint: str, size: int,
               landmarks: dict[str, frozenset] | None = None) -> HintClaim | None:
    """Extract a coarse region claim from free text, or None if unparseable.

    Opposing directions in one hint (north + south) contradict => None.
    Landmark phrases (map_area lexicon) win over compass terms when present.
    """
    text = (hint or "").lower()
    if not text:
        return None
    for phrase, cells in (landmarks or {}).items():
        if phrase.lower() in text:
            return HintClaim(frozenset({phrase}), frozenset(cells))

    found = {term: axis_side for term, axis_side in _DIRECTIONS.items()
             if term in text}
    if not found:
        return None
    constraints: dict[int, int] = {}
    for _, (axis, side) in found.items():
        if constraints.setdefault(axis, side) != side:
            return None                                   # north AND south: nonsense
    lo, hi = range(0, size // 2), range((size + 1) // 2, size)
    rows = (lo if constraints[0] == 0 else hi) if 0 in constraints else range(size)
    cols = (lo if constraints[1] == 0 else hi) if 1 in constraints else range(size)
    cells = frozenset((r, c) for r in rows for c in cols)
    return HintClaim(frozenset(found), cells)


def judge_claim(claim_cells: frozenset, scent: dict[Cell, float]) -> str:
    """Verdict on a region claim given the claimant's own scent snapshot.

    TRUTH additionally requires the scent PEAK to sit inside the claim. Mass
    share alone is truth-washable: a broad claim propped up by a decoy tail can
    clear 30% while the real peak lies elsewhere, and rewarding that lets an
    opponent steer our belief into the wrong quadrant. No peak, no reward.
    """
    total = sum(scent.values())
    if total < MIN_TOTAL_SCENT:
        return UNKNOWN
    claimed = sum(v for cell, v in scent.items() if cell in claim_cells)
    share = claimed / total
    if share < LIE_SHARE:
        return LIE
    if share > TRUTH_SHARE and max(scent, key=scent.get) in claim_cells:
        return TRUTH
    return UNKNOWN


def supported_cells(claim_cells: frozenset, scent: dict[Cell, float],
                    floor: float = SUPPORT_FLOOR) -> frozenset:
    """Claimed cells the scent ALREADY backs (>= floor x peak intensity).

    Confining a truth reward to these cells makes it self-regulating: when the
    scent blob lies wholly inside the claim the boost is near-neutral (it scales
    what is already the peak), and when the claim spans several scent lobes it
    disambiguates between them — which is the only genuinely new information a
    confirmed hint carries. Empty claimed cells are never pumped.
    """
    if not scent:
        return frozenset()
    cutoff = floor * max(scent.values())
    return frozenset(c for c, v in scent.items() if c in claim_cells and v >= cutoff)
