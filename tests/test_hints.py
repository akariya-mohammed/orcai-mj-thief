"""Task 4.6: lexicon hint parser (EN+HE, zero deps) + scent-based claim judging."""
from police_thief.domain.hints import (LIE, TRUTH, UNKNOWN, judge_claim, parse_hint,
                                       supported_cells)


# ── parsing ──────────────────────────────────────────────────────────────────

def test_english_direction():
    claim = parse_hint("I keep heading north through the streets", 7)
    assert claim is not None
    assert all(r <= 2 for r, _ in claim.cells)          # north = top rows
    assert len(claim.cells) == 21                        # 3 rows x 7 cols


def test_hebrew_direction():
    claim = parse_hint("אני נע לכיוון דרום", 7)
    assert claim is not None
    assert all(r >= 4 for r, _ in claim.cells)           # דרום = south = bottom rows


def test_compound_direction_intersects():
    claim = parse_hint("slipping away north-east of you", 7)
    assert claim is not None
    assert claim.cells == frozenset((r, c) for r in range(3) for c in range(4, 7))


def test_contradictory_directions_yield_none():
    assert parse_hint("north then south, catch me", 7) is None


def test_empty_or_unparseable_yields_none():
    assert parse_hint("", 7) is None
    assert parse_hint("you will never catch me copper", 7) is None


def test_landmark_lexicon_is_extensible():
    landmarks = {"times square": frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})}
    claim = parse_hint("hiding near Times Square tonight", 7, landmarks=landmarks)
    assert claim is not None and claim.cells == landmarks["times square"]


# ── judging a claim against the opponent's own (unfakeable) scent ────────────

def _north_cells():
    return frozenset((r, c) for r in range(3) for c in range(7))


def test_claim_matching_scent_is_truth():
    scent = {(1, 3): 0.81, (2, 3): 0.62}                 # mass IS in the north
    assert judge_claim(_north_cells(), scent) is TRUTH


def test_claim_contradicting_scent_is_lie():
    # Book Ch.4 worked example: "went north" while all scent sits south-east.
    scent = {(5, 5): 0.81, (5, 4): 0.62}
    assert judge_claim(_north_cells(), scent) is LIE


def test_early_game_thin_scent_is_unknown():
    assert judge_claim(_north_cells(), {(5, 5): 0.2}) is UNKNOWN
    assert judge_claim(_north_cells(), {}) is UNKNOWN


# ── P1-2: truth-washing resistance ───────────────────────────────────────────

# A technically-broad claim propped up by a decoy tail: 35% of the scent mass
# sits in the claimed north, but the actual peak is in the south. Granting TRUTH
# here lets an opponent steer our belief to the wrong quadrant.
WASH_SCENT = {(5, 5): 0.81, (5, 4): 0.55, (2, 2): 0.62, (1, 2): 0.55, (2, 3): 0.50}


def test_truth_requires_the_scent_peak_inside_the_claim():
    assert max(WASH_SCENT, key=WASH_SCENT.get) == (5, 5)      # true peak is south
    assert judge_claim(_north_cells(), WASH_SCENT) is UNKNOWN  # not TRUTH, not LIE


def test_genuine_truth_still_verifies():
    # peak inside the claim + healthy share -> still TRUTH
    assert judge_claim(_north_cells(), {(1, 3): 0.81, (2, 3): 0.62}) is TRUTH


def test_supported_cells_are_only_the_scent_backed_ones():
    claim = _north_cells()
    supported = supported_cells(claim, {(1, 3): 0.81, (2, 3): 0.62, (5, 5): 0.9})
    assert supported == frozenset({(1, 3), (2, 3)})   # in-claim AND scent-backed
    assert (0, 0) not in supported                     # empty claimed cells excluded
    assert (5, 5) not in supported                     # out-of-claim excluded


def test_supported_cells_empty_when_no_scent():
    assert supported_cells(_north_cells(), {}) == frozenset()
