"""Task 4.7: trust EMA + belief penalize/boost wired into the receive path."""
import math

from test_fusion import _msg, _runtime


def test_book_example_lie_is_caught_and_punished():
    # Hint says "north"; the opponent's own scent sits south-east. Trust drops,
    # the claimed (deceptive) region is suppressed, argmax stays on the scent.
    rt = _runtime()
    rt.on_opponent_turn(_msg(scent={"5,5": 0.81, "5,4": 0.62},
                             hint="I slipped away north"))
    assert rt.trust_ema < 0.5                              # 0.7 * 0.5 = 0.35
    assert rt.belief.most_likely() == (5, 5)               # evidence wins
    north_mass = sum(rt.belief.grid[r][c] for r in range(3) for c in range(7))
    assert north_mass < 0.05                               # claimed area suppressed


def test_honest_opponent_builds_trust():
    rt = _runtime()
    for _ in range(3):                                     # truthful: scent matches claim
        rt.on_opponent_turn(_msg(scent={"1,3": 0.81, "2,3": 0.62},
                                 hint="still up north, come find me"))
    assert rt.trust_ema > 0.8                              # 0.5->0.65->0.755->0.83


def _north_split(rt):
    """(mass on the two scent-backed cells, mass on the 19 empty claimed cells)."""
    backed = {(1, 3), (2, 3)}
    cells = [(r, c) for r in range(3) for c in range(7)]
    return (sum(rt.belief.grid[r][c] for r, c in cells if (r, c) in backed),
            sum(rt.belief.grid[r][c] for r, c in cells if (r, c) not in backed))


SCENT = {"1,3": 0.81, "2,3": 0.62}


def test_trusted_hint_reinforces_only_the_scent_backed_cells():
    # Differential: same scent, once with an unparseable hint (no verdict, no
    # reward) and once with the verified claim. The reward must land on the
    # evidence-backed cells and NOWHERE else.
    quiet, believed = _runtime(), _runtime()
    quiet.on_opponent_turn(_msg(scent=SCENT, hint="you will never catch me"))
    believed.on_opponent_turn(_msg(scent=SCENT, hint="up north, catch me"))
    assert believed.last_hint_verdict == "truth" and quiet.last_hint_verdict is None

    q_backed, q_empty = _north_split(quiet)
    b_backed, b_empty = _north_split(believed)
    assert b_backed > q_backed          # confirmation reinforces the evidence...
    assert b_empty < q_empty            # ...and never pumps the empty claimed cells
    assert math.isclose(sum(sum(row) for row in believed.belief.grid), 1.0)


def test_truth_boost_never_pumps_empty_claimed_cells():
    rt = _runtime()
    rt.on_opponent_turn(_msg(scent=SCENT, hint="still up north somewhere"))
    assert rt.last_hint_verdict == "truth"
    backed, empty = _north_split(rt)
    assert backed > empty                # evidence dominates the claimed region
    assert rt.belief.most_likely() == (1, 3)


def test_unparseable_hint_leaves_trust_untouched():
    rt = _runtime()
    rt.on_opponent_turn(_msg(scent={"3,3": 0.81}, hint="you will never catch me"))
    assert rt.trust_ema == 0.5


def test_truth_washing_cannot_hijack_our_argmax():
    # Full receive path: a broad "north" claim propped up by a decoy tail while the
    # real peak sits south. Our belief must stay on the evidence, not the claim.
    rt = _runtime()
    rt.on_opponent_turn(_msg(
        scent={"5,5": 0.81, "5,4": 0.55, "2,2": 0.62, "1,2": 0.55, "2,3": 0.50},
        hint="I am heading north"))
    assert rt.belief.most_likely() == (5, 5)          # decoy did NOT steer us
    assert rt.last_hint_verdict != "truth"            # unverifiable -> no reward


def test_known_liar_gets_penalized_even_without_verdict():
    # Two proven lies push trust below the liar line; after that, even a claim
    # the scent cannot judge (thin evidence) is preemptively suppressed.
    rt = _runtime()
    for _ in range(2):
        rt.on_opponent_turn(_msg(scent={"5,5": 0.81, "5,4": 0.62},
                                 hint="running north again"))
    assert rt.trust_ema < 0.35                             # 0.35 -> 0.245
    before = sum(rt.belief.grid[r][c] for r in range(3) for c in range(7))
    rt.on_opponent_turn(_msg(scent={"5,5": 0.1}, hint="heading north now"))
    after = sum(rt.belief.grid[r][c] for r in range(3) for c in range(7))
    assert after < before                                  # distrust prior applied
