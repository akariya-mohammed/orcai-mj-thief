"""6.4 + 6.5: terminal claims and the mutual audit's hash / move-chain layers."""
import pytest

from police_thief.domain.brains import Decision, Direction, MoveType
from police_thief.domain.termination import (CAPTURE, SURVIVAL, judge_capture_claim,
                                             judge_survival_claim)
from police_thief.peer.audit import audit_hash_chain, audit_move_chain, audit_opponent
from police_thief.peer.sealing import sealed_record


class _State:
    def __init__(self, pos, size=7, barriers=()):
        self.position = pos
        self.barriers = set(barriers)
        self.board = type("B", (), {"grid_size": size})()


def _rec(pos, move="HOLD", step=1, barriers=()):
    decision = Decision(MoveType.HOLD, None, hint="")
    if move.startswith("MOVE:"):
        decision = Decision(MoveType.MOVE, Direction(move.split(":")[1]), hint="")
    elif move.startswith("BARRIER"):
        decision = Decision(MoveType.BARRIER, Direction.N, hint="")
    return sealed_record(_State(pos, barriers=barriers), decision, step)


# ── 6.4 terminal claims ──────────────────────────────────────────────────────

def test_true_capture_claim_is_confirmed():
    verdict = judge_capture_claim(claimed_cell=[3, 3], my_position=(3, 3), step=7)
    assert verdict["confirmed"] is True and verdict["type"] == CAPTURE
    assert verdict["step"] == 7


def test_false_capture_claim_is_honestly_denied():
    verdict = judge_capture_claim(claimed_cell=[3, 3], my_position=(5, 5), step=7)
    assert verdict["confirmed"] is False
    assert verdict["position"] == [5, 5]      # denial ships its own proof


def test_survival_claim_needs_the_agreed_step_count():
    assert judge_survival_claim(claimed_step=35, threshold=35)["confirmed"] is True
    assert judge_survival_claim(claimed_step=34, threshold=35)["confirmed"] is False
    assert judge_survival_claim(claimed_step=35, threshold=35)["type"] == SURVIVAL


# ── 6.5 hash layer ───────────────────────────────────────────────────────────

def test_untouched_records_pass_the_hash_audit():
    records = [_rec((3, 3), "MOVE:S", 1), _rec((4, 3), "MOVE:S", 2)]
    assert audit_hash_chain(records) == []


def test_rewritten_move_fails_its_own_digest():
    records = [_rec((3, 3), "MOVE:S", 1)]
    records[0]["move"] = "MOVE:N"             # history edited after sealing
    findings = audit_hash_chain(records)
    assert findings and findings[0]["rule"] == "hash" and findings[0]["step"] == 1


def test_missing_reveal_fields_are_reported_not_crashed():
    assert audit_hash_chain([{"commit": "x"}])[0]["rule"] == "hash"


# ── 6.5 move-chain layer ─────────────────────────────────────────────────────

def _chain(moves, start=(3, 3)):
    """Build a position chain that honestly follows the declared moves."""
    from police_thief.domain.board import DELTAS
    pos, records = start, []
    for i, mv in enumerate(moves, start=1):
        if mv.startswith("MOVE:"):
            d = next(k for k in DELTAS if k.value == mv.split(":")[1])
            pos = (pos[0] + DELTAS[d][0], pos[1] + DELTAS[d][1])
        records.append(_rec(pos, mv, i))
    return records


def test_legal_walk_passes():
    records = _chain(["MOVE:S", "MOVE:E", "HOLD"])
    assert audit_move_chain(records, "thief", (3, 3), 14) == []


def test_two_step_jump_is_caught():
    records = _chain(["MOVE:S"])
    records[0]["position"] = [5, 3]           # teleported two cells
    findings = audit_move_chain(records, "thief", (3, 3), 14)
    assert findings and "revealed [5, 3]" in findings[0]["detail"]


def test_thief_placing_a_barrier_is_caught():
    records = _chain(["BARRIER:N"])
    findings = audit_move_chain(records, "thief", (3, 3), 14)
    assert any("cop-only" in f["detail"] for f in findings)


def test_barrier_quota_breach_is_caught():
    records = _chain(["BARRIER:N"] * 3)
    findings = audit_move_chain(records, "police", (3, 3), barriers_max=2)
    assert any("quota" in f["detail"] for f in findings)


def test_hold_that_secretly_moved_is_caught():
    records = _chain(["HOLD"])
    records[0]["position"] = [4, 3]
    findings = audit_move_chain(records, "thief", (3, 3), 14)
    assert findings and "HOLD" in findings[0]["detail"]


# ── full matrix ──────────────────────────────────────────────────────────────

def test_clean_disclosure_passes_the_whole_matrix():
    records = _chain(["MOVE:S", "MOVE:E"])
    result = audit_opponent(records, role="thief", start=(3, 3), barriers_max=14)
    assert result["passed"] is True and result["failures"] == []
    assert result["checked"]["records"] == 2


def test_tampered_disclosure_fails_with_evidence():
    records = _chain(["MOVE:S", "MOVE:E"])
    records[1]["move"] = "MOVE:W"
    result = audit_opponent(records, role="thief", start=(3, 3), barriers_max=14)
    assert result["passed"] is False
    assert {f["rule"] for f in result["failures"]} & {"hash", "move"}
