"""Stage-4 gate, tasks 4.1-4.2: scent emission field + decay (Book Ch. 4, Figures 4-5).

The emission formula is Gaussian, fitted to the book's Figure-4 grid:
    dtau(d) = 0.9 * exp(-3 * d^2 / 8)
NOTE: derived from the book figure, pending confirmation vs reference smell.py (Intel I2).
"""
import math

from police_thief.domain.smell import ScentGrid


# ── 4.1 emission ─────────────────────────────────────────────────────────────

def test_emission_field_matches_book_figure_4():
    g = ScentGrid(7)
    g.deposit((3, 3))
    s = g.snapshot()
    expected = {(0, 0): 0.90, (0, 1): 0.62, (1, 1): 0.42,
                (0, 2): 0.20, (1, 2): 0.14, (2, 2): 0.04}
    for (dr, dc), want in expected.items():
        got = s[(3 + dr, 3 + dc)]
        assert abs(got - want) <= 0.01, f"offset ({dr},{dc}): got {got:.4f}, want {want}"


def test_field_is_radially_symmetric():
    g = ScentGrid(7)
    g.deposit((3, 3))
    s = g.snapshot()
    assert math.isclose(s[(2, 3)], s[(4, 3)]) and math.isclose(s[(3, 2)], s[(3, 4)])
    assert math.isclose(s[(1, 3)], s[(3, 1)])


def test_corner_deposit_clips_at_board_edges():
    g = ScentGrid(7)
    g.deposit((0, 0))
    s = g.snapshot()
    # 5x5 window centered on a corner -> only the 3x3 on-board quadrant survives
    assert len(s) == 9
    assert all(0 <= r < 7 and 0 <= c < 7 for r, c in s)
    assert math.isclose(s[(0, 0)], 0.9)


def test_redeposit_plateaus_at_center_intensity():
    # Book Figure 5: continuous presence holds the cell at 0.9 — it never grows.
    g = ScentGrid(7)
    g.deposit((3, 3))
    g.deposit((3, 3))
    assert g.snapshot()[(3, 3)] <= 0.9
    assert math.isclose(g.snapshot()[(3, 3)], 0.9)


def test_snapshot_is_sparse_and_detached():
    g = ScentGrid(7)
    g.deposit((3, 3))
    s = g.snapshot()
    assert len(s) == 25 < 49          # only the emission window, not the whole board
    s[(6, 6)] = 1.0                    # mutating the snapshot must not touch the grid
    assert (6, 6) not in g.snapshot()


# ── 4.2 decay ────────────────────────────────────────────────────────────────

def test_decay_multiplies_by_one_minus_rho():
    g = ScentGrid(7)
    g.deposit((3, 3))
    g.decay_all()
    assert math.isclose(g.snapshot()[(3, 3)], 0.9 * 0.90)   # rho = 0.10


def test_trail_half_life_is_about_seven_turns():
    # Book Figure 5: a single deposit stays "readable" ~6-7 turns; the half-intensity
    # line (0.45) is crossed at turn 7 with rho = 0.10.
    g = ScentGrid(7)
    g.deposit((3, 3))
    values = []
    for _ in range(8):
        g.decay_all()
        values.append(g.snapshot().get((3, 3), 0.0))
    assert values[5] > 0.45            # after 6 decays: still above half
    assert values[6] < 0.45            # after 7 decays: below half


def test_faint_cells_are_pruned_before_strong_ones():
    g = ScentGrid(7)
    g.deposit((3, 3))
    for _ in range(40):
        g.decay_all()
    s = g.snapshot()
    assert (5, 5) not in s             # corner of the field (0.045) pruned (< 1e-3)
    assert (3, 3) in s                 # center (~0.013) still present


def test_grid_eventually_empties():
    g = ScentGrid(7)
    g.deposit((3, 3))
    for _ in range(80):
        g.decay_all()
    assert g.snapshot() == {}
