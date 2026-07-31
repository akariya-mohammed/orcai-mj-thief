"""Task 7.4: the replay verification engine — two tamper layers (record + consensus)."""
from police_thief.domain.crypto import commit
from police_thief.gui.replay_data import verify_step, verify_log, VERIFIED, TAMPERED
from police_thief.report.report_writer import build_log
from police_thief.shared.config import canonical_sha256


def _sealed(state, move, intent="truth"):
    h, nonce = commit(state, move, intent)
    return {"commit": h, "nonce": nonce, "state": state, "move": move,
            "intent": intent, "hint": ""}


def _log(records):
    return build_log("a-vs-b", "uid1", {}, records, sub_game_number=1,
                     group_id="us", role="police", opponent_group_id="them",
                     result="capture", winner_role="police", steps=len(records),
                     started_at="2026-07-26T10:00:00", duration_seconds=30,
                     tokens_total=0, audit={"passed": True, "failures": []})


def test_honest_record_verifies():
    assert verify_step(_sealed("s1", "MOVE:N")) == VERIFIED


def test_tampered_move_is_caught_per_record():
    rec = _sealed("s1", "MOVE:N")
    rec["move"] = "MOVE:S"                       # rewrite history after sealing
    assert verify_step(rec) == TAMPERED


def test_honest_log_verdict_ok():
    verdict, detail = verify_log(_log([_sealed("s1", "MOVE:N"), _sealed("s2", "MOVE:E")]))
    assert verdict == VERIFIED and detail["steps_checked"] == 2


def test_single_record_tamper_reports_the_exact_step():
    records = [_sealed("s1", "MOVE:N"), _sealed("s2", "MOVE:E"), _sealed("s3", "HOLD")]
    log = _log(records)
    log["records"][1]["move"] = "MOVE:W"
    verdict, detail = verify_log(log)
    assert verdict == TAMPERED and detail["step"] == 2


def test_wholesale_record_swap_caught_by_consensus_signature():
    # Every record is individually valid, but the SET differs from what both
    # peers agreed on: the consensus layer must catch it.
    log = _log([_sealed("s1", "MOVE:N")])
    log["records"] = [_sealed("s1", "MOVE:S")]   # re-sealed, individually valid
    verdict, detail = verify_log(log)
    assert verdict == TAMPERED and detail["layer"] == "consensus"


def test_end_to_end_runtime_records_verify():
    # Records produced by the REAL turn loop must replay-verify.
    from police_thief.domain.belief import BeliefGrid
    from police_thief.domain.board import Board
    from police_thief.domain.brains import Role
    from police_thief.domain.own_state import OwnGameState
    from police_thief.peer.runtime import PeerRuntime
    from police_thief.strategy.heuristic import ManhattanBayesThief

    class _T:
        def send_turn(self, m):
            return {}

    rt = PeerRuntime(Role.THIEF, ManhattanBayesThief(), _T(),
                     OwnGameState((3, 3), Board(7)), BeliefGrid(7), config={})
    for _ in range(3):
        rt.run_turn()
    verdict, detail = verify_log(_log(rt.records))
    assert verdict == VERIFIED and detail["steps_checked"] == 3
