"""Belief map: prior, scent fusion, diffusion, and the lie-detection penalty (Ch. 4, 6)."""
import math

from police_thief.domain.belief import BeliefGrid


def test_uniform_prior_sums_to_one():
    b = BeliefGrid(7)
    assert math.isclose(sum(sum(row) for row in b.grid), 1.0)


def test_smell_concentrates_belief():
    b = BeliefGrid(7)
    b.update_from_smell({(5, 2): 0.9})          # strong scent at one cell
    assert b.most_likely() == (5, 2)
    assert math.isclose(sum(sum(row) for row in b.grid), 1.0)


def test_lie_penalty_shifts_argmax():
    # Scent says south-east; the opponent claims "north". Penalize the north cells → argmax
    # stays on the true (scented) region, not the claimed one.
    b = BeliefGrid(7)
    b.update_from_smell({(1, 4): 0.81})         # true-ish location, south-east corner region
    b.penalize([(0, c) for c in range(7)])      # opponent lied "went north" (row 0)
    r, _ = b.most_likely()
    assert r != 0


def _point_mass(size, cell):
    """A pure delta prior — update_from_smell leaves residue everywhere, which would
    mask the neighborhood shape under test."""
    b = BeliefGrid(size)
    b.grid = [[0.0] * size for _ in range(size)]
    b.grid[cell[0]][cell[1]] = 1.0
    return b


def test_diffuse_preserves_total_mass():
    b = BeliefGrid(7)
    b.update_from_smell({(3, 3): 1.0})
    b.diffuse()
    assert math.isclose(sum(sum(row) for row in b.grid), 1.0)
    # a point mass spreads to neighbors
    assert b.grid[3][3] < 1.0 and b.grid[2][3] > 0


# ── 4.5: von-Neumann + stay, barrier-aware ───────────────────────────────────

def test_diffusion_is_von_neumann_not_king():
    # This game has no diagonal moves: a point mass must spread ONLY to the four
    # orthogonal neighbors + itself, never to diagonals.
    b = _point_mass(7, (3, 3))
    b.diffuse()
    assert b.grid[2][2] == 0.0 and b.grid[2][4] == 0.0    # diagonals: nothing
    assert b.grid[4][2] == 0.0 and b.grid[4][4] == 0.0
    for r, c in ((3, 3), (2, 3), (4, 3), (3, 2), (3, 4)):  # stay + N/S/E/W: 1/5 each
        assert math.isclose(b.grid[r][c], 0.2)


def test_barrier_blocks_diffusion_inflow():
    b = _point_mass(7, (3, 3))
    b.diffuse(barriers={(2, 3)})
    assert b.grid[2][3] == 0.0                             # nothing enters a wall
    for r, c in ((3, 3), (4, 3), (3, 2), (3, 4)):          # 4 ways left: 1/4 each
        assert math.isclose(b.grid[r][c], 0.25)
    assert math.isclose(sum(sum(row) for row in b.grid), 1.0)


def test_walled_in_cell_keeps_its_mass():
    b = _point_mass(7, (3, 3))
    b.diffuse(barriers={(2, 3), (4, 3), (3, 2), (3, 4)})
    assert math.isclose(b.grid[3][3], 1.0)                 # nowhere to go -> stays


def test_mass_stranded_on_a_barrier_is_pushed_out():
    # The opponent cannot stand inside a wall: stale mass on a barrier cell must
    # relocate to its passable neighbors, and the barrier ends at zero.
    b = _point_mass(7, (3, 3))
    b.diffuse(barriers={(3, 3)})
    assert b.grid[3][3] == 0.0
    for r, c in ((2, 3), (4, 3), (3, 2), (3, 4)):
        assert math.isclose(b.grid[r][c], 0.25)
    assert math.isclose(sum(sum(row) for row in b.grid), 1.0)
