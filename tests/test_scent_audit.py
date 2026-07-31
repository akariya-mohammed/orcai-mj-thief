"""P0-3: post-game scent-history audit — catching an opponent who broadcast a
scent trail their own revealed positions cannot explain.

Two modes, deliberately. STRUCTURAL (default) asserts only what every honest
emission model must satisfy: scent appears near where you have been. STRICT
replays our exact model and demands equality — fair ONLY when both peers
declared the same scent model at handshake, because our falloff was derived
from the book's figure and never confirmed against another implementation.
Accusing an honest opponent of tampering loses US the game.
"""
from police_thief.domain.smell import ScentGrid
from police_thief.peer.audit import audit_scent_history

CFG = {"pheromone_center_intensity": 0.9, "pheromone_decay": 0.10,
       "pheromone_grid_size": 5}


def _honest_broadcasts(positions, size=7):
    """Exactly what an honest peer emits: deposit at each position, then decay."""
    grid, out = ScentGrid(size), []
    for pos in positions:
        grid.deposit(pos)
        grid.decay_all()
        out.append(grid.snapshot())
    return out


HONEST_WALK = [(3, 3), (4, 3), (5, 3), (5, 4), (5, 5)]


def test_honest_trail_passes_both_modes():
    broadcasts = _honest_broadcasts(HONEST_WALK)
    for strict in (False, True):
        findings = audit_scent_history(HONEST_WALK, broadcasts, CFG, 7, strict=strict)
        assert findings == [], f"strict={strict}: {findings}"


def test_fake_trail_broadcast_at_turn_4_is_caught():
    # The attack: on step 4 the thief broadcasts a blob across the board from
    # anywhere it has actually been, to drag the cop away.
    broadcasts = _honest_broadcasts(HONEST_WALK)
    decoy = ScentGrid(7)
    decoy.deposit((0, 0))                     # nowhere near the revealed walk
    decoy.decay_all()
    broadcasts[3] = decoy.snapshot()
    findings = audit_scent_history(HONEST_WALK, broadcasts, CFG, 7)
    assert findings, "doctored trail slipped through"
    assert findings[0]["step"] == 4           # 1-indexed: the tampered turn
    assert "scent" in findings[0]["rule"]


def test_structural_mode_tolerates_a_different_honest_falloff():
    # An opponent whose emission decays differently but is still centred on its
    # own positions is HONEST. Structural mode must not accuse them.
    broadcasts = []
    for i, pos in enumerate(HONEST_WALK):
        broadcasts.append({pos: 0.42, (pos[0], min(6, pos[1] + 1)): 0.11})
    assert audit_scent_history(HONEST_WALK, broadcasts, CFG, 7) == []


def test_strict_mode_flags_the_same_different_falloff():
    # ...but if both sides DECLARED the same model, deviation is evidence.
    broadcasts = [{pos: 0.42} for pos in HONEST_WALK]
    findings = audit_scent_history(HONEST_WALK, broadcasts, CFG, 7, strict=True)
    assert findings and findings[0]["rule"] == "scent-model"


def test_scent_in_a_never_visited_region_is_caught():
    broadcasts = _honest_broadcasts(HONEST_WALK)
    broadcasts[-1] = dict(broadcasts[-1])
    broadcasts[-1][(0, 6)] = 0.7              # a cell no window ever covered
    findings = audit_scent_history(HONEST_WALK, broadcasts, CFG, 7)
    assert findings and "0, 6" in findings[0]["detail"].replace("(", "").replace(")", "")


def test_missing_broadcasts_are_not_an_accusation():
    # Fewer snapshots than steps is incomplete data, not proof of cheating.
    assert audit_scent_history(HONEST_WALK, [], CFG, 7) == []
