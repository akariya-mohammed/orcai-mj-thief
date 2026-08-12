"""Interop layer tests: contract lock, golden vectors, audit, series logic,
friendly/counted wall. See docs/INTEROP-ahk-yosi.md."""
from __future__ import annotations

import json
import queue
from pathlib import Path

import pytest

from police_thief.domain.smell import ScentGrid
from police_thief.exceptions import ProtocolViolation
from police_thief.interop import refaudit, wire
from police_thief.interop import terms as terms_mod
from police_thief.interop.refcrypto import (
    canonical_bytes,
    digest,
    new_nonce,
    reference_commit,
    seal,
    verify_record,
)
from police_thief.interop.series import (
    CAPTURE,
    SURVIVAL,
    TECHNICAL_LOSS,
    ReferenceSeriesPeer,
    SubGame,
    role_for,
    score_for,
)
from police_thief.shared.config import Config

AGREED_SHA = "fef1fe3a229b0c7daece9f1e3ebe7a097a7207e6ac0628b6c67050595a6101be"

GOLDEN_PAYLOAD = {"kind": "step", "role": "police", "sub_game": 1, "step": 1,
                  "position": [1, 0], "move": "MOVE:S", "barrier": None,
                  "intent": "truth", "hint": "golden"}
GOLDEN_NONCE = "00112233445566778899aabbccddeeff"
GOLDEN_COMMIT = "9896089baad1e3ef87214d04ab397828c4f8e1b8c1db034648110cd48aaca90a"
GOLDEN_CANONICAL = ('{"barrier":null,"hint":"golden","intent":"truth",'
                    '"kind":"step","move":"MOVE:S","position":[1,0],'
                    '"role":"police","step":1,"sub_game":1}')


def load_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    return Config.load(shared_path=str(root / "config" / "game.json"),
                       private_path=str(root / "config" / "does-not-exist.toml"))


# -- contract lock -----------------------------------------------------------
def test_agreed_constitution_hash():
    """game.json must stay byte-compatible with the agreed constitution."""
    cfg = load_config()
    assert digest(cfg.shared) == AGREED_SHA


def test_constitution_fixed_values():
    cfg = load_config()
    assert cfg.get("board.size") == 7
    assert tuple(cfg.get("positions.thief_start")) == (3, 3)
    assert tuple(cfg.get("positions.cop_start")) == (0, 0)
    assert cfg.get("rules.max_steps") == 35
    assert cfg.get("rules.barriers_max") == 14
    assert cfg.get("pheromones.pheromone_decay") == 0.1
    assert cfg.get("pheromones.pheromone_center_intensity") == 0.9
    assert cfg.get("pheromones.pheromone_grid_size") == 5
    assert cfg.get("game.num_games") == 6
    assert cfg.get("board_and_agents.first_mover") == "thief"


# -- commit golden vector -----------------------------------------------------
def test_commit_golden_vector():
    assert canonical_bytes(GOLDEN_PAYLOAD).decode() == GOLDEN_CANONICAL
    assert reference_commit(GOLDEN_PAYLOAD, GOLDEN_NONCE) == GOLDEN_COMMIT


def test_seal_and_verify_roundtrip():
    record = seal(GOLDEN_PAYLOAD)
    assert set(record) == {"payload", "nonce", "commit"}
    assert verify_record(record)


def test_tampered_payload_fails():
    record = seal(GOLDEN_PAYLOAD)
    record["payload"]["position"] = [6, 6]
    assert not verify_record(record)


def test_tampered_nonce_fails():
    record = seal(GOLDEN_PAYLOAD)
    record["nonce"] = new_nonce()
    assert not verify_record(record)


def test_tampered_commit_fails():
    record = seal(GOLDEN_PAYLOAD)
    record["commit"] = "0" * 64
    assert not verify_record(record)


# -- scent golden vector --------------------------------------------------------
def test_scent_golden_vector():
    """Our declared model: tau = min(0.9, sum 0.9*exp(-0.375*d^2)); decay x0.9;
    dust floor: prune below 1e-3. Field is served AFTER the step's emission."""
    grid = ScentGrid(7, center_intensity=0.9, decay_rate=0.10, field_size=5)
    grid.deposit((3, 3))
    snap = grid.snapshot()
    assert snap[(3, 3)] == pytest.approx(0.9)
    assert snap[(2, 3)] == pytest.approx(0.618560350911875)
    assert snap[(2, 2)] == pytest.approx(0.4251298974669132)
    assert snap[(1, 3)] == pytest.approx(0.20081714413358684)
    assert snap[(1, 2)] == pytest.approx(0.13801947016043561)
    assert snap[(1, 1)] == pytest.approx(0.04480836153107755)
    assert len(snap) == 25
    grid.decay_all()
    snap = grid.snapshot()
    assert snap[(3, 3)] == pytest.approx(0.81)
    assert snap[(1, 1)] == pytest.approx(0.0403275253779698)


def test_scent_dust_floor():
    grid = ScentGrid(7)
    grid._tau[(0, 0)] = 0.00105
    grid.decay_all()   # 0.000945 < 1e-3 -> pruned to nothing
    assert (0, 0) not in grid.snapshot()


def test_scent_clamped_at_center():
    grid = ScentGrid(7)
    grid.deposit((3, 3))
    grid.deposit((3, 3))
    assert max(grid.snapshot().values()) == pytest.approx(0.9)


# -- result serialization golden vector -----------------------------------------
def test_result_digest_golden_vector():
    body = {"report_type": "game_result", "match_mode": "FRIENDLY (UNCOUNTED)",
            "dialect": "reference", "totals": {"police": 75, "thief": 45},
            "series_winner": "police"}
    assert digest(body) == \
        "496e2433b76951c4baf8cbadbb3f6940ef2753bb3c3298e739ea65caf3c44127"


def test_score_table():
    scoring = load_config().get("scoring")
    assert score_for(CAPTURE, scoring) == (20, 5)
    assert score_for(SURVIVAL, scoring) == (5, 10)
    assert score_for(TECHNICAL_LOSS, scoring) == (0, 0)


# -- terms / negotiate ------------------------------------------------------------
def test_terms_match_their_vocabulary():
    """Field-for-field the dict their interop_terms builds from the same game.json."""
    cfg = load_config()
    assert terms_mod.build_terms(cfg, 6) == {
        "board_size": 7, "smell_grid_size": 5, "decay_per_step": 0.1,
        "emit_intensity": 0.9, "min_center_intensity": 0.5, "max_steps": 35,
        "barriers_max": 14, "setting": "New York", "hint_max_words": 15,
        "axis_origin_corner": "top-left", "axis_start_index": 0,
        "thief_start": [3, 3], "cop_start": [0, 0], "num_games": 6,
    }


def test_agreement_signature_roundtrip():
    cfg = load_config()
    terms = terms_mod.build_terms(cfg, 6)
    agreement = terms_mod.signed_agreement(terms, {"group_id": "orcai-mj"})
    ok, reason = terms_mod.evaluate_agreement(agreement, terms)
    assert ok, reason


def test_agreement_refused_on_terms_mismatch():
    cfg = load_config()
    terms = terms_mod.build_terms(cfg, 6)
    wrong = dict(terms, max_steps=40)
    agreement = terms_mod.signed_agreement(wrong, {})
    ok, reason = terms_mod.evaluate_agreement(agreement, terms)
    assert not ok and "max_steps" in reason


def test_agreement_refused_on_bad_signature():
    cfg = load_config()
    terms = terms_mod.build_terms(cfg, 6)
    agreement = terms_mod.signed_agreement(terms, {})
    agreement["signature"] = "0" * 64
    ok, reason = terms_mod.evaluate_agreement(agreement, terms)
    assert not ok and "signature" in reason


# -- wire ---------------------------------------------------------------------------
def test_wire_roundtrip():
    msg = wire.build_turn(step=3, sender="thief", hint="hi",
                          scent={(3, 3): 0.9, (2, 3): 0.61}, commit="a" * 64,
                          barrier=None, capture_claim=None,
                          claim_response={"claim": [1, 1], "caught": False},
                          win_claim=None)
    assert set(msg) == {"step", "sender", "hint", "smell_grid", "commit",
                        "timestamp", "barrier_placed", "capture_claim",
                        "claim_response", "win_claim"}
    parsed = wire.parse_turn(msg, grid_size=7)
    assert parsed["scent"][(3, 3)] == 0.9
    assert parsed["claim_response"] == {"claim": [1, 1], "caught": False}


@pytest.mark.parametrize("mutation", [
    {"commit": "zz"}, {"sender": "warden"}, {"step": -1},
    {"barrier_placed": [9, 9]}, {"capture_claim": [1]}, {"win_claim": "yes"},
])
def test_wire_rejects_malformed(mutation):
    msg = wire.build_turn(step=1, sender="thief", hint="", scent={},
                          commit="a" * 64)
    msg.update(mutation)
    with pytest.raises(ProtocolViolation):
        wire.parse_turn(msg, grid_size=7)


# -- reference audit ------------------------------------------------------------------
def _walk_records(cells: list[list[int]], role: str = "thief") -> list[dict]:
    return [seal({"kind": "step", "role": role, "sub_game": 1, "step": i + 1,
                  "position": cell, "move": "MOVE:S", "barrier": None,
                  "intent": "truth", "hint": ""})
            for i, cell in enumerate(cells)]


def test_audit_clean_log_verifies():
    records = _walk_records([[3, 3], [3, 4], [3, 5]])
    live = [r["commit"] for r in records]
    verdict, violations = refaudit.audit_reference_log(records, live, grid_size=7)
    assert verdict == refaudit.VERIFIED_OK and not violations


def test_audit_detects_withheld_commitment():
    records = _walk_records([[3, 3], [3, 4]])
    live = [r["commit"] for r in records] + ["f" * 64]
    verdict, violations = refaudit.audit_reference_log(records, live, grid_size=7)
    assert verdict == refaudit.TAMPERED
    assert any("never revealed" in v for v in violations)


def test_audit_detects_teleport():
    records = _walk_records([[3, 3], [5, 5]])
    verdict, violations = refaudit.audit_reference_log(
        records, [r["commit"] for r in records], grid_size=7)
    assert verdict == refaudit.TAMPERED
    assert any("jumped" in v for v in violations)


def test_audit_detects_tampered_record():
    records = _walk_records([[3, 3], [3, 4]])
    records[1]["payload"]["position"] = [3, 5]
    verdict, violations = refaudit.audit_reference_log(
        records, [r["commit"] for r in records], grid_size=7)
    assert verdict == refaudit.TAMPERED
    assert any("hash mismatch" in v for v in violations)


def test_audit_reads_their_pos_after_shape():
    records = [seal({"kind": "step", "role": "police", "sub_game": 1, "step": i + 1,
                     "pos_before": a, "pos_after": b, "move": "S",
                     "intent": "truth"})
               for i, (a, b) in enumerate([([0, 0], [1, 0]), ([1, 0], [2, 0])])]
    verdict, _ = refaudit.audit_reference_log(
        records, [r["commit"] for r in records], grid_size=7)
    assert verdict == refaudit.VERIFIED_OK


def test_audit_barrier_quota():
    records = _walk_records([[3, 3]] * 15, role="police")
    for r in records:
        r["payload"]["barrier"] = [0, 0]
    resealed = [seal(r["payload"]) for r in records]
    verdict, violations = refaudit.audit_reference_log(
        resealed, [], grid_size=7, barriers_max=14)
    assert verdict == refaudit.TAMPERED
    assert any("quota" in v for v in violations)


# -- series logic -----------------------------------------------------------------------
def test_role_alternation():
    assert [role_for("police", n) for n in range(1, 7)] == \
        ["police", "thief", "police", "thief", "police", "thief"]
    assert [role_for("thief", n) for n in range(1, 7)] == \
        ["thief", "police", "thief", "police", "thief", "police"]


def _sub_game(role: str) -> SubGame:
    return SubGame(role, load_config(), 1, seed=7)


def _turn(step: int, sender: str, **extra) -> dict:
    msg = wire.build_turn(step=step, sender=sender, hint="", scent={},
                          commit="a" * 64)
    msg.update(extra)
    return wire.parse_turn(msg, grid_size=7)


def test_survival_claim_variants_accepted():
    """Their engine sends {"type": "survival_claim"} with NO step field."""
    for kind in ("survival", "survival_claim"):
        engine = _sub_game("police")
        engine.opp_steps = 34
        engine.process_opp_turn(_turn(35, "thief",
                                      win_claim={"type": kind}))
        assert engine.outcome == {
            "ending": SURVIVAL, "winner": "thief", "step": 35,
            "cause": f"{kind} at 35 steps"}


def test_false_survival_claim_is_technical():
    engine = _sub_game("police")
    engine.process_opp_turn(_turn(10, "thief", win_claim={"type": "survival"}))
    assert engine.outcome["ending"] == TECHNICAL_LOSS
    assert engine.outcome["winner"] == "police"


def test_captured_event_confession_ends_capture():
    engine = _sub_game("police")
    engine.process_opp_turn(_turn(9, "thief",
                                  win_claim={"type": "captured_event"}))
    assert engine.outcome["ending"] == CAPTURE
    assert engine.outcome["winner"] == "police"


def test_capture_claim_answered_truthfully():
    engine = _sub_game("thief")      # we start at (3,3)
    engine.process_opp_turn(_turn(4, "police", capture_claim=[3, 3]))
    assert engine.owed_claim_response == {"claim": [3, 3], "caught": True}
    assert engine.outcome["ending"] == CAPTURE
    engine2 = _sub_game("thief")
    engine2.process_opp_turn(_turn(4, "police", capture_claim=[0, 0]))
    assert engine2.owed_claim_response == {"claim": [0, 0], "caught": False}
    assert engine2.outcome is None


def test_claim_response_confirms_our_capture():
    engine = _sub_game("police")
    engine.process_opp_turn(_turn(5, "thief",
                                  claim_response={"claim": [2, 2],
                                                  "caught": True}))
    assert engine.outcome["ending"] == CAPTURE
    assert engine.outcome["winner"] == "police"


def test_duplicate_step_is_claims_only():
    """Their terminal flush re-sends the last turn; it must never move them."""
    engine = _sub_game("police")
    engine.process_opp_turn(_turn(5, "thief"))
    assert engine.opp_steps == 5 and len(engine.opp_commits) == 1
    engine.process_opp_turn(_turn(5, "thief",
                                  claim_response={"claim": [1, 1],
                                                  "caught": True}))
    assert engine.opp_steps == 5 and len(engine.opp_commits) == 1
    assert engine.outcome["ending"] == CAPTURE


def test_captured_thief_never_claims_survival():
    """Even if play somehow continues, a captured thief holds and never claims."""
    engine = _sub_game("thief")
    engine.captured = True
    engine.my_steps = 40
    message = engine.build_my_turn()
    assert message["win_claim"] is None
    assert engine.records[-1]["payload"]["move"] == "HOLD"


def test_thief_survival_claim_sent_at_threshold():
    engine = _sub_game("thief")
    engine.my_steps = 34
    message = engine.build_my_turn()
    assert message["win_claim"] == {"type": "survival", "step": 35}
    assert engine.outcome["ending"] == SURVIVAL


def _peer(mode: str = "friendly", **kw) -> ReferenceSeriesPeer:
    return ReferenceSeriesPeer(
        natural_role="police", config=load_config(),
        opponent_url="http://127.0.0.1:1/mcp", my_port=1,
        mode=mode, log_fn=lambda *a: None, **kw)


def test_turn_timeout_is_technical_loss():
    peer = _peer(turn_timeout=0.2)
    engine = _sub_game("police")
    assert peer._await_opponent_turn(engine) is None
    assert engine.outcome["ending"] == TECHNICAL_LOSS
    assert "timeout" in engine.outcome["cause"]


def test_role_collision_is_technical_loss():
    peer = _peer(turn_timeout=5.0)
    engine = _sub_game("police")
    peer.inbox.turns.put(wire.build_turn(step=1, sender="police", hint="",
                                         scent={}, commit="a" * 64))
    assert peer._await_opponent_turn(engine) is None
    assert "both peers claim role" in engine.outcome["cause"]


def test_audit_package_is_terminal_signal():
    """A barrier-capture ending has no turn-message channel in the reference
    dialect: the opponent's audit package ends the sub-game (measured live)."""
    peer = _peer(turn_timeout=5.0)
    engine = _sub_game("police")
    peer.inbox.audits.put({"sender": "thief", "records": [],
                           "result_claim": "capture"})
    assert peer._await_opponent_turn(engine) is None
    assert engine.outcome["ending"] == CAPTURE
    assert engine.outcome["winner"] == "police"
    assert not peer.inbox.audits.empty()      # requeued for the audit exchange


def test_result_claim_inconsistent_is_technical():
    # a thief that was NOT captured must not accept a capture concession
    engine = _sub_game("thief")
    engine.accept_result_claim("capture")
    assert engine.outcome["ending"] == TECHNICAL_LOSS
    # a captured thief accepts it
    engine2 = _sub_game("thief")
    engine2.captured = True
    engine2.accept_result_claim("capture")
    assert engine2.outcome["ending"] == CAPTURE


def test_captured_thief_confesses_and_ends():
    """Rule #46: a wall on our cell ends the sub-game as capture, confessed via
    an unprompted truthful claim_response (the only channel their bridge
    accepts as terminal)."""
    engine = _sub_game("thief")
    engine.process_opp_turn(_turn(1, "police", barrier_placed=[3, 3]))
    assert engine.captured
    assert engine.outcome["ending"] == CAPTURE
    assert engine.outcome["winner"] == "police"
    assert engine.owed_claim_response == {"claim": [3, 3], "caught": True}
    flush = engine.courtesy_flush()
    assert flush["claim_response"] == {"claim": [3, 3], "caught": True}
    assert flush["win_claim"] is None


def test_stale_audit_drained_at_boundary():
    peer = _peer()
    peer.inbox.audits.put({"result_claim": "capture", "records": []})
    peer._drain_stale_turns()
    assert peer.inbox.audits.empty()


def test_stale_flush_drained_at_boundary():
    peer = _peer()
    stale = wire.build_turn(step=35, sender="thief", hint="", scent={},
                            commit="a" * 64, win_claim={"type": "survival"})
    fresh = wire.build_turn(step=1, sender="thief", hint="", scent={},
                            commit="b" * 64)
    peer.inbox.turns.put(stale)
    peer.inbox.turns.put(fresh)
    peer._drain_stale_turns()
    assert peer.inbox.turns.get_nowait()["commit"] == "b" * 64
    with pytest.raises(queue.Empty):
        peer.inbox.turns.get_nowait()


# -- friendly / counted wall ----------------------------------------------------------
def test_friendly_never_constructs_email_sender(monkeypatch):
    """FRIENDLY must be structurally unable to send: the sender module is
    poisoned and dispatch_report must still succeed by never touching it."""
    import sys

    monkeypatch.setitem(sys.modules, "police_thief.infra.email_sender", None)
    peer = _peer(mode="friendly")
    receipt = peer.dispatch_report({"series_winner": "police"})
    assert "suppressed" in receipt["status"]
    assert "friendly" in receipt["status"]


def test_counted_mode_reaches_for_the_sender(monkeypatch, tmp_path):
    """COUNTED with verified audits is the only path that touches the email module."""
    import sys

    monkeypatch.setitem(sys.modules, "police_thief.infra.email_sender", None)
    peer = _peer(mode="counted", out_dir=str(tmp_path))
    with pytest.raises(ImportError):
        peer.dispatch_report({"series_winner": "police", "all_audits_verified": True})


def test_friendly_artifacts_are_labeled(tmp_path):
    peer = _peer(out_dir=str(tmp_path))
    result = peer.build_result()
    assert result["match_mode"] == "FRIENDLY (UNCOUNTED)"
    # game_id computed from identity (orcai-mj) vs empty their_identity (opponent)
    result_file = tmp_path / f"result_{result['game_id']}.json"
    on_disk = json.loads(result_file.read_text(encoding="utf-8"))
    assert on_disk["match_mode"] == "FRIENDLY (UNCOUNTED)"
    assert on_disk["result_sha256"] == result["result_sha256"]


def test_result_digest_is_canonical_and_reproducible(tmp_path):
    peer = _peer(out_dir=str(tmp_path))
    result = peer.build_result()
    claimed = result.pop("result_sha256")
    result.pop("report_status", None)  # post-sha256 metadata; not in the digest
    assert digest(result) == claimed


def test_emission_matches_book_figure4():
    """Book Figure 4 anchor values, within 0.01."""
    from police_thief.domain.smell import emission_at
    for d2, expected in [(0, 0.90), (1, 0.62), (2, 0.42), (4, 0.20),
                         (5, 0.14), (8, 0.04)]:
        assert emission_at(d2) == pytest.approx(expected, abs=0.011)
