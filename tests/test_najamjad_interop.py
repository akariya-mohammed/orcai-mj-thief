"""Regression tests for the NajAmjad opponent profile (NAJAMJAD_MATCH_TERMS.md).

Covers the compatibility surface that differs from the ahk-yosi and amireman
profiles — and pins that both of those are untouched:

* §1  — the exactly-14 signed terms and the a284082d… digest, re-derived
        through OUR loader; the full-file config lock is a separate hash.
* §5  — the 4047830b… commit-reveal golden vector, computed through OUR
        sealing implementation; audit pushed both ways; repeated audit copies.
* §6  — sorted game_id and UUID game_uid (golden values).
* §3  — split two-process windows, per-role routing, busy refusals,
        sub_game_number on every negotiate, re-offer under the same number.
* §4  — the EXACT multiplicative_book_v1 25-cell kernel, max-merge clamp,
        the decay->deposit->transmit serve order (peak always 0.90), and a
        fresh empty field per sub-game.
* Rule 47 — thief concedes when immobilised; police never finalizes a capture
        without the acknowledgement; the NajAmjad barrier restriction.
* §7  — group-keyed roles/score, the SPACED mutual digest over exactly
        {game_id, aggregate, sub_games}, the raw-75-75 + tie_award=2 tie rule,
        per-window per-repo github_commit.
* §7.4 — friendly can never mail the lecturer; counted mails only the lecturer.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from police_thief.cli_cmds import NAJAMJAD_CONFIG_SHA256
from police_thief.domain.board import Board
from police_thief.domain.brains import Decision, Direction, MoveType
from police_thief.infra.email_sender import LEAGUE_ADDRESS
from police_thief.interop import consensus as C
from police_thief.interop import najamjad as N
from police_thief.interop import najamjad_report as R
from police_thief.interop import terms as terms_mod
from police_thief.interop.mcp import Inbox
from police_thief.interop.refcrypto import digest, reference_commit
from police_thief.interop.series import (
    NAJAMJAD_FRIENDLY_RECIPIENT,
    POLICE,
    THIEF,
    ReferenceSeriesPeer,
    SubGame,
)
from police_thief.shared.config import Config
from police_thief.strategy.trapping import TrapperPolice

ROOT = Path(__file__).resolve().parents[1]

SIGNED_TERMS = {
    "board_size": 7, "smell_grid_size": 5, "decay_per_step": 0.1,
    "emit_intensity": 0.9, "min_center_intensity": 0.5, "max_steps": 35,
    "barriers_max": 14, "setting": "New York", "hint_max_words": 15,
    "axis_origin_corner": "top-left", "axis_start_index": 0,
    "thief_start": [3, 3], "cop_start": [0, 0], "num_games": 6,
}
GOLDEN_GAME_ID = "najamjad-vs-orcai-mj"
GOLDEN_GAME_UID = "87e65319-3cf1-d7c9-0f4e-cf940418aa14"


def najamjad_config() -> Config:
    return Config.load(
        shared_path=str(ROOT / "config" / "game.najamjad.json"),
        private_path=str(ROOT / "config" / "najamjad" / "police.toml"))


def make_peer(tmp_path, natural_role=POLICE, first_window_role=POLICE,
              mode="friendly", private=None) -> ReferenceSeriesPeer:
    cfg = najamjad_config()
    if private is not None:
        cfg = Config(cfg.shared, private)
    peer = ReferenceSeriesPeer(
        natural_role=natural_role, config=cfg,
        opponent_url="http://127.0.0.1:1/mcp", my_port=18999,
        mode=mode, spec_profile="najamjad", out_dir=str(tmp_path),
        first_window_role=first_window_role, log_fn=lambda *_: None,
        git_commit_hash="a" * 40)
    return peer


def _mk_row(n, my_role, ending, winner, our_commit, police_score, thief_score):
    return {
        "index": n, "my_role": my_role, "ending": ending, "winner": winner,
        "cause": "test", "step": 20, "police_score": police_score,
        "thief_score": thief_score, "audit_of_opponent": "Verified OK",
        "audit_violations": [], "audit_delivered": True,
        "opponent_audit_of_us": "n/a", "protocol_violations": [],
        "started_at": "t0", "ended_at": "t1", "our_commit": our_commit,
        "their_commit": "c" * 40, "their_group_id": "najamjad",
        "result_agreed": True, "log_verified": True,
    }


# =========================================================================
# §1 — exactly 14 signed terms and the a284082d… digest, via OUR loader
# =========================================================================
def test_terms_are_exactly_the_fourteen_signed_keys():
    terms = terms_mod.build_terms(najamjad_config(), 6)
    assert terms == SIGNED_TERMS
    assert len(terms) == 14


def test_canonical_terms_bytes_match_their_published_bytes():
    assert C.canonical(SIGNED_TERMS) == (
        '{"axis_origin_corner":"top-left","axis_start_index":0,'
        '"barriers_max":14,"board_size":7,"cop_start":[0,0],'
        '"decay_per_step":0.1,"emit_intensity":0.9,"hint_max_words":15,'
        '"max_steps":35,"min_center_intensity":0.5,"num_games":6,'
        '"setting":"New York","smell_grid_size":5,"thief_start":[3,3]}')


def test_terms_digest_matches_and_verifies_loudly():
    terms = terms_mod.build_terms(najamjad_config(), 6)
    assert N.terms_sha256(terms) == N.TERMS_SHA256
    N.verify_terms(terms)                       # must not raise
    with pytest.raises(ValueError, match="refusing to play"):
        N.verify_terms(dict(terms, setting="Haifa"))


def test_full_config_lock_is_a_different_hash_from_the_terms():
    """Never confuse the 14-key terms digest with a full-config hash."""
    shared = najamjad_config().shared
    assert digest(shared) == NAJAMJAD_CONFIG_SHA256
    assert NAJAMJAD_CONFIG_SHA256 != N.TERMS_SHA256


# =========================================================================
# §5 — commit-reveal golden vector through OUR implementation
# =========================================================================
def test_commit_reveal_golden_vector():
    got = reference_commit(N.COMMIT_VECTOR_PAYLOAD, N.COMMIT_VECTOR_NONCE)
    assert got == N.COMMIT_VECTOR_SHA256
    N.verify_commit_vector()                    # must not raise


def test_nonce_is_32_lowercase_hex():
    from police_thief.interop.refcrypto import new_nonce
    for _ in range(8):
        nonce = new_nonce()
        assert len(nonce) == 32
        assert set(nonce) <= set("0123456789abcdef")


def test_sealed_records_carry_position():
    """A reveal without per-record positions is unverifiable (their §5)."""
    engine = SubGame(THIEF, najamjad_config(), 1, seed=1,
                     spec_profile="najamjad")
    engine.build_my_turn()
    assert engine.records and "position" in engine.records[0]["payload"]


# =========================================================================
# §6 — identifiers both sides compute independently
# =========================================================================
def test_game_id_sorted_and_golden():
    assert C.spec_game_id("orcai-mj", "najamjad") == GOLDEN_GAME_ID
    assert C.spec_game_id("najamjad", "orcai-mj") == GOLDEN_GAME_ID


def test_game_uid_golden_and_order_independent():
    terms = terms_mod.build_terms(najamjad_config(), 6)
    a = C.spec_game_uid(terms, "orcai-mj", "najamjad")
    b = C.spec_game_uid(terms, "najamjad", "orcai-mj")
    assert a == b == GOLDEN_GAME_UID


def test_peer_derives_ids_before_any_handshake(tmp_path):
    peer = make_peer(tmp_path)
    peer._compute_ids()
    assert peer.game_id == GOLDEN_GAME_ID
    assert peer.game_uid == GOLDEN_GAME_UID


# =========================================================================
# §3 — two processes, per-role routing, window scheduling
# =========================================================================
def test_window_partition_covers_the_series_disjointly():
    cop = N.windows_for(POLICE, POLICE, 6)
    thief = N.windows_for(THIEF, POLICE, 6)
    assert cop == [1, 3, 5]
    assert thief == [2, 4, 6]
    assert sorted(cop + thief) == [1, 2, 3, 4, 5, 6]


def test_window_partition_flips_with_first_window_role():
    assert N.windows_for(POLICE, THIEF, 6) == [2, 4, 6]
    assert N.windows_for(THIEF, THIEF, 6) == [1, 3, 5]


def test_per_role_routing_cop_dials_their_thief():
    assert N.opponent_url_for(POLICE) == N.THEIR_THIEF_URL
    assert N.opponent_url_for(THIEF) == N.THEIR_COP_URL
    assert N.THEIR_COP_URL != N.THEIR_THIEF_URL


def test_peer_plays_only_its_fixed_role_windows(tmp_path):
    assert make_peer(tmp_path, POLICE).my_windows == [1, 3, 5]
    assert make_peer(tmp_path, THIEF).my_windows == [2, 4, 6]


def test_identity_names_both_our_doors(tmp_path):
    private = {"game": {"group_id": "orcai-mj"},
               "network": {"cop_mcp_url": "https://our-cop.example/mcp",
                           "thief_mcp_url": "https://our-thief.example/mcp"}}
    peer = make_peer(tmp_path, private=private)
    assert peer.identity["mcp_servers"] == {
        "cop": "https://our-cop.example/mcp",
        "thief": "https://our-thief.example/mcp"}


# =========================================================================
# §3.1 — negotiate: sub_game_number, busy refusals, fresh handshakes
# =========================================================================
def test_agreement_carries_sub_game_number_and_top_level_identity(tmp_path):
    peer = make_peer(tmp_path)
    agreement = N.signed_agreement(peer.terms, peer.identity, 3)
    assert agreement["sub_game_number"] == 3
    assert agreement["sender"] == "orcai-mj"          # their §9.8
    assert agreement["group_id"] == "orcai-mj"
    assert agreement["scent_model_sha256"] == N.SCENT_MODEL_SHA256


def test_fresh_negotiate_uses_a_fresh_nonce(tmp_path):
    peer = make_peer(tmp_path)
    a = N.signed_agreement(peer.terms, peer.identity, 1)
    b = N.signed_agreement(peer.terms, peer.identity, 1)
    assert a["nonce"] != b["nonce"]
    assert a["signature"] != b["signature"]


def test_evaluate_agreement_accepts_matching_and_verifies_signature(tmp_path):
    peer = make_peer(tmp_path)
    theirs = N.signed_agreement(peer.terms, {"group_id": "najamjad"}, 2)
    ok, reason = N.evaluate_agreement(theirs, peer.terms, expected_sub_game=2)
    assert ok, reason


def test_evaluate_agreement_refuses_differing_terms(tmp_path):
    peer = make_peer(tmp_path)
    theirs = N.signed_agreement(dict(peer.terms, setting="Haifa"),
                                {"group_id": "najamjad"}, 2)
    ok, reason = N.evaluate_agreement(theirs, peer.terms, expected_sub_game=2)
    assert not ok and "terms mismatch" in reason


def test_evaluate_agreement_refuses_wrong_window_number(tmp_path):
    peer = make_peer(tmp_path)
    theirs = N.signed_agreement(peer.terms, {"group_id": "najamjad"}, 5)
    ok, reason = N.evaluate_agreement(theirs, peer.terms, expected_sub_game=3)
    assert not ok and "names window 5" in reason


def test_evaluate_agreement_refuses_foreign_scent_model(tmp_path):
    peer = make_peer(tmp_path)
    theirs = N.signed_agreement(peer.terms, {"group_id": "najamjad"}, 1)
    theirs["scent_model_sha256"] = "81ebee59" + "0" * 56     # A1, not agreed
    ok, reason = N.evaluate_agreement(theirs, peer.terms, expected_sub_game=1)
    assert not ok and "scent model" in reason


def test_evaluate_agreement_refuses_bad_signature_but_tolerates_absent(tmp_path):
    peer = make_peer(tmp_path)
    theirs = N.signed_agreement(peer.terms, {"group_id": "najamjad"}, 1)
    theirs["signature"] = "0" * 64
    ok, reason = N.evaluate_agreement(theirs, peer.terms)
    assert not ok and "signature" in reason
    del theirs["signature"]
    ok, _ = N.evaluate_agreement(theirs, peer.terms)
    assert ok


def test_busy_refusal_shape_is_retriable():
    busy = N.busy_refusal()
    assert busy["accepted"] is False and busy["errors"]
    assert N.is_busy_refusal(busy)
    assert not N.is_busy_refusal({"ok": True})
    assert not N.is_busy_refusal({"accepted": True})


def test_responder_returns_busy_mid_game(tmp_path):
    peer = make_peer(tmp_path)
    peer._mid_game = True
    assert N.is_busy_refusal(peer._najamjad_negotiate_responder({}))


def test_responder_refuses_mismatched_window_and_accepts_matching(tmp_path):
    peer = make_peer(tmp_path)
    peer._current_window = 3
    refusal = peer._najamjad_negotiate_responder({"sub_game_number": 5})
    assert refusal["accepted"] is False and "5" in refusal["errors"][0]
    reply = peer._najamjad_negotiate_responder({"sub_game_number": 3})
    assert reply["accepted"] is True
    assert reply["agreement"]["sub_game_number"] == 3    # in-band agreement


def test_inbox_never_queues_a_refused_negotiate():
    inbox = Inbox()
    inbox.negotiate_responder = lambda msg: {"accepted": False, "errors": ["x"]}
    assert inbox.on_negotiate({"terms": {}})["accepted"] is False
    assert inbox.agreements.empty()
    inbox.negotiate_responder = None                     # legacy behavior
    assert inbox.on_negotiate({"terms": {}}) == {"ok": True}
    assert not inbox.agreements.empty()


def test_negotiate_window_retries_through_busy_then_locks(tmp_path):
    peer = make_peer(tmp_path)
    their_agreement = N.signed_agreement(
        peer.terms, {"group_id": "najamjad", "group_name": "NajAmjad"}, 2)
    calls = []

    class FakeLink:
        def negotiate(self, agreement, timeout=None):
            calls.append(agreement)
            if len(calls) == 1:
                return N.busy_refusal()          # busy is retriable, not fatal
            return {"ok": True, "accepted": True, "agreement": their_agreement}

    peer.link = FakeLink()
    ok, reason = peer.negotiate_window_najamjad(2)
    assert ok, reason
    assert len(calls) == 2
    assert all(c["sub_game_number"] == 2 for c in calls)
    assert peer.their_identity.get("group_id") == "najamjad"


def test_window_patience_is_bounded_and_reports_failure(tmp_path):
    peer = make_peer(tmp_path)
    peer.window_patience = 0.3                   # test-scale wall clock

    class DeadLink:
        def negotiate(self, agreement, timeout=None):
            from police_thief.interop.mcp import LinkError
            raise LinkError("door is down")

    peer.link = DeadLink()
    ok, reason = peer.negotiate_window_najamjad(1)
    assert not ok


# =========================================================================
# §1/§3 — thief-first, role alternation across the series
# =========================================================================
def test_role_alternates_across_windows():
    assert [N.our_window_role(POLICE, n) for n in range(1, 7)] == \
        [POLICE, THIEF, POLICE, THIEF, POLICE, THIEF]


def test_thief_sends_the_first_gameplay_turn(tmp_path):
    peer = make_peer(tmp_path, natural_role=THIEF, first_window_role=THIEF)
    peer.turn_timeout = 0.2
    sent = []

    class FakeLink:
        def receive_turn(self, message, timeout=None):
            sent.append(message)

        def submit_audit(self, payload, timeout=None):
            pass

    peer.link = FakeLink()
    engine = SubGame(THIEF, peer.config, 1, seed=1, spec_profile="najamjad")
    peer._run_play_loop(engine)
    assert sent and sent[0]["step"] == 1 and sent[0]["sender"] == THIEF


def test_step_one_means_state_after_first_move(tmp_path):
    engine = SubGame(THIEF, najamjad_config(), 1, seed=1,
                     spec_profile="najamjad")
    message = engine.build_my_turn()
    assert message["step"] == 1
    assert engine.records[0]["payload"]["step"] == 1
    # position sealed is the post-move cell, not the start cell
    assert engine.records[0]["payload"]["position"] == \
        list(engine.state.position)


def test_survival_only_at_exactly_step_35():
    engine = SubGame(THIEF, najamjad_config(), 1, seed=1,
                     spec_profile="najamjad")
    engine.my_steps = 33
    assert engine.build_my_turn()["win_claim"] is None       # step 34: no claim
    engine2 = SubGame(THIEF, najamjad_config(), 1, seed=1,
                      spec_profile="najamjad")
    engine2.my_steps = 34
    claim = engine2.build_my_turn()["win_claim"]             # step 35: claim
    assert claim and claim["type"] == "survival" and claim["step"] == 35
    assert engine2.outcome["ending"] == "survival"


# =========================================================================
# Rule 47 + the NajAmjad barrier restriction
# =========================================================================
def _opp_turn(step, barrier=None, capture_claim=None, claim_response=None,
              sender=POLICE):
    return {"step": step, "sender": sender, "hint": "", "scent": {},
            "commit": "0" * 64, "barrier": barrier,
            "capture_claim": capture_claim, "claim_response": claim_response,
            "win_claim": None}


def test_rule_47_thief_concedes_when_enclosed():
    engine = SubGame(THIEF, najamjad_config(), 1, seed=1,
                     spec_profile="najamjad")
    engine.state.position = (0, 0)
    engine.state.board.barriers.update({(0, 1), (1, 0)})
    engine.process_opp_turn(_opp_turn(1))
    assert engine.captured
    assert engine.owed_claim_response == {"claim": [0, 0], "caught": True}
    assert engine.outcome["ending"] == "capture"


def test_najamjad_barrier_on_our_cell_is_violation_not_capture():
    engine = SubGame(THIEF, najamjad_config(), 1, seed=1,
                     spec_profile="najamjad")
    engine.process_opp_turn(_opp_turn(1, barrier=[3, 3]))    # our start cell
    assert not engine.captured
    assert engine.outcome is None
    assert (3, 3) not in engine.state.barriers               # never applied
    assert any("Barrier Law" in v for v in engine.violations)


def test_ahk_yosi_barrier_on_cell_capture_is_unchanged():
    """The rule-46 confession stays exactly as ahk-yosi verified it."""
    cfg = Config.load(shared_path=str(ROOT / "config" / "game.json"),
                      private_path=str(ROOT / "config" / "does-not-exist.toml"))
    engine = SubGame(THIEF, cfg, 1, seed=1, spec_profile="ahk-yosi")
    engine.process_opp_turn(_opp_turn(1, barrier=[3, 3]))
    assert engine.captured
    assert engine.outcome["ending"] == "capture"


def test_police_never_finalizes_capture_without_acknowledgement():
    engine = SubGame(POLICE, najamjad_config(), 1, seed=1,
                     spec_profile="najamjad")
    engine.process_opp_turn(_opp_turn(1, sender=THIEF))      # plain turn
    assert engine.outcome is None                            # no unilateral end
    engine.process_opp_turn(_opp_turn(
        2, sender=THIEF, claim_response={"claim": [2, 2], "caught": True}))
    assert engine.outcome["ending"] == "capture"             # ack arrived


def test_najamjad_police_brain_never_walls_the_thief_cell():
    board = Board(7)

    class _Point:
        def __init__(self, cell):
            self.cell = cell

        def most_likely(self):
            return self.cell

    class _State:
        def __init__(self):
            self.position = (3, 3)
            self.board = board
            self.visited = frozenset()

    thief_cell = (3, 4)                                      # adjacent
    banned = TrapperPolice(forbid_barrier_on_thief=True)
    decision = banned._decide_move(_State(), _Point(thief_cell), 14)
    if decision[0] is MoveType.BARRIER:
        target = ((3, 3) if decision[1] is None
                  else board.step((3, 3), decision[1]))
        assert target != thief_cell
    legacy = TrapperPolice()                                  # R46 pounce intact
    move_type, direction = legacy._decide_move(_State(), _Point(thief_cell), 14)
    assert move_type is MoveType.BARRIER
    assert board.step((3, 3), direction) == thief_cell


# =========================================================================
# §4 — A2 kernel, serve order, clamp, fresh field
# =========================================================================
A2_TABLE = [
    [0.04, 0.14, 0.20, 0.14, 0.04],
    [0.14, 0.42, 0.62, 0.42, 0.14],
    [0.20, 0.62, 0.90, 0.62, 0.20],
    [0.14, 0.42, 0.62, 0.42, 0.14],
    [0.04, 0.14, 0.20, 0.14, 0.04],
]


def test_a2_first_turn_kernel_is_the_exact_25_cell_table():
    grid = N.KernelScentGrid(7)
    grid.deposit((3, 3))
    snapshot = grid.snapshot()
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            expected = A2_TABLE[dr + 2][dc + 2]
            assert snapshot[(3 + dr, 3 + dc)] == pytest.approx(expected), \
                f"cell ({3 + dr},{3 + dc})"
    assert len(snapshot) == 25


def test_a2_decay_is_multiplicative_0_9():
    grid = N.KernelScentGrid(7)
    grid.deposit((3, 3))
    grid.decay_all()
    snap = grid.snapshot()
    assert snap[(3, 3)] == pytest.approx(0.81)
    assert snap[(3, 4)] == pytest.approx(0.558)
    assert snap[(1, 1)] == pytest.approx(0.036)   # the kit's field_walk value


def test_a2_max_merge_clamp_stationary_agent_plateaus():
    grid = N.KernelScentGrid(7)
    for _ in range(5):                    # serve order: age, then deposit
        grid.decay_all()
        grid.deposit((3, 3))
    snap = grid.snapshot()
    assert snap[(3, 3)] == pytest.approx(0.90)    # never above emit_intensity
    assert snap[(3, 4)] == pytest.approx(0.62)    # max-merge, NOT a sum


def test_serve_order_peak_is_0_90_and_trail_carries_this_turns_decay():
    cfg = najamjad_config()
    engine = SubGame(THIEF, cfg, 1, seed=1, spec_profile="najamjad")

    class _GoEast:
        def decide(self, state, belief, opponent_hint="", play_setting=None,
                   barriers_max=0, **kw):
            return Decision(MoveType.MOVE, Direction.E)

    engine.brain = _GoEast()
    t1 = engine.build_my_turn()           # (3,3) -> (3,4)
    assert t1["smell_grid"]["3,4"] == pytest.approx(0.90)   # fresh peak
    assert t1["smell_grid"]["3,3"] == pytest.approx(0.62)   # NOT pre-decayed
    t2 = engine.build_my_turn()           # (3,4) -> (3,5)
    assert t2["smell_grid"]["3,5"] == pytest.approx(0.90)   # peak stays 0.90
    assert t2["smell_grid"]["3,4"] == pytest.approx(0.81)   # aged exactly once
    assert t2["smell_grid"]["3,3"] == pytest.approx(0.558)  # aged trail
    t3 = engine.build_my_turn()           # (3,5) -> (3,6)
    assert t3["smell_grid"]["3,6"] == pytest.approx(0.90)
    assert t3["smell_grid"]["3,5"] == pytest.approx(0.81)
    assert t3["smell_grid"]["3,4"] == pytest.approx(0.729)  # multi-turn trail


def test_other_profiles_keep_their_deposit_then_decay_order():
    """ahk-yosi's wire behavior is pinned: peak 0.81 after its agreed order."""
    cfg = Config.load(shared_path=str(ROOT / "config" / "game.json"),
                      private_path=str(ROOT / "config" / "does-not-exist.toml"))
    engine = SubGame(THIEF, cfg, 1, seed=1, spec_profile="ahk-yosi")

    class _GoEast:
        def decide(self, state, belief, opponent_hint="", play_setting=None,
                   barriers_max=0, **kw):
            return Decision(MoveType.MOVE, Direction.E)

    engine.brain = _GoEast()
    t1 = engine.build_my_turn()
    assert t1["smell_grid"]["3,4"] == pytest.approx(0.81)


def test_scent_field_starts_empty_for_every_sub_game():
    cfg = najamjad_config()
    first = SubGame(THIEF, cfg, 1, seed=1, spec_profile="najamjad")
    first.build_my_turn()
    assert first.scent.snapshot()                 # populated after a turn
    replay = SubGame(THIEF, cfg, 1, seed=1, spec_profile="najamjad")
    assert replay.scent.snapshot() == {}          # fresh window, empty field
    assert isinstance(replay.scent, N.KernelScentGrid)


# =========================================================================
# §5 — audit pushed both ways, repeated copies tolerated
# =========================================================================
def _finished_engine(cfg, n):
    engine = SubGame(POLICE, cfg, n, seed=1, spec_profile="najamjad")
    engine.outcome = {"ending": "capture", "winner": POLICE, "step": 10,
                      "cause": "test"}
    return engine


def test_our_audit_is_pushed_outbound_with_window_index(tmp_path):
    peer = make_peer(tmp_path)
    peer.audit_wait = 0.1
    pushed = []

    class FakeLink:
        def submit_audit(self, payload, timeout=None):
            pushed.append(payload)

    peer.link = FakeLink()
    row = peer._finish_sub_game(_finished_engine(peer.config, 2), 2,
                                datetime.now(UTC).isoformat())
    assert pushed, "outbound submit_audit must be pushed, not only answered"
    assert pushed[0]["result_claim"] == "capture"
    assert pushed[0]["sub_game"] == 2 and pushed[0]["sub_game_number"] == 2
    assert row["audit_delivered"] is True


def test_repeated_byte_identical_audit_copies_are_tolerated(tmp_path):
    peer = make_peer(tmp_path)
    package = {"sender": "thief", "records": [], "result_claim": "capture"}
    peer._last_audit_key = json.dumps(package, sort_keys=True, default=str)
    assert peer._is_stale_audit_copy(dict(package), 3)       # identical copy
    assert peer._is_stale_audit_copy(
        {"sender": "thief", "records": [], "result_claim": "capture",
         "sub_game_number": 2}, 3)                           # earlier window
    fresh = {"sender": "thief", "records": [], "result_claim": "survival",
             "sub_game_number": 3}
    assert not peer._is_stale_audit_copy(fresh, 3)


def test_stale_audit_tolerance_is_najamjad_only(tmp_path):
    cfg = Config.load(shared_path=str(ROOT / "config" / "game.json"),
                      private_path=str(ROOT / "config" / "does-not-exist.toml"))
    peer = ReferenceSeriesPeer(
        natural_role=POLICE, config=cfg, opponent_url="http://127.0.0.1:1/mcp",
        my_port=18998, out_dir=str(tmp_path), log_fn=lambda *_: None)
    peer._last_audit_key = "anything"
    assert not peer._is_stale_audit_copy({"sub_game_number": 1}, 3)


# =========================================================================
# §7 — group-keyed rows, spaced mutual digest, tie rule, per-window commits
# =========================================================================
def _tie_rows():
    """3-3 of clean captures: 75-75, the measured real tie."""
    rows = []
    for n in (1, 3, 5):                    # we are police, we capture: 20-5
        rows.append(_mk_row(n, POLICE, "capture", POLICE, "a" * 40, 20, 5))
    for n in (2, 4, 6):                    # we are thief, they capture: 20-5
        rows.append(_mk_row(n, THIEF, "capture", POLICE, "b" * 40, 20, 5))
    return rows


def test_group_rows_are_keyed_by_group_id(tmp_path):
    peer = make_peer(tmp_path)
    rows = peer._najamjad_group_rows(_tie_rows())
    for row in rows:
        assert set(row["roles"]) == {"orcai-mj", "najamjad"}
        assert set(row["score"]) == {"orcai-mj", "najamjad"}
        assert set(row) == {"sub_game_number", "result", "roles", "score",
                            "winner_group"}


def test_mutual_doc_signed_over_exactly_three_keys(tmp_path):
    peer = make_peer(tmp_path)
    doc = N.build_mutual_doc(GOLDEN_GAME_ID,
                             peer._najamjad_group_rows(_tie_rows()),
                             "orcai-mj", "najamjad")
    assert set(doc) == {"game_id", "aggregate", "sub_games"}
    text = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for banned in ("game_uid", "timestamp", "tokens", "steps", "started_at",
                   "github", "log_files", "audit"):
        assert banned not in text


def test_mutual_digest_uses_the_spaced_default_separators():
    doc = {"game_id": GOLDEN_GAME_ID, "aggregate": {"x": 1}, "sub_games": []}
    spaced = hashlib.sha256(
        json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    compact = hashlib.sha256(
        json.dumps(doc, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode()).hexdigest()
    assert N.mutual_digest(doc) == spaced
    assert N.mutual_digest(doc) != compact       # never the compact form


#: NajAmjad's authoritative filed preimage (anrbj666 series) and its digest.
ANRBJ_PREIMAGE = (
    '{"aggregate": {"series_tie": true, "sub_games_won": {"anrbj666": 3, '
    '"najamjad": 3}, "ties": 0, "total_score": {"anrbj666": 77, "najamjad": '
    '77}, "winner_group": null}, "game_id": "anrbj666-vs-najamjad", '
    '"sub_games": [{"result": "capture", "roles": {"anrbj666": "police", '
    '"najamjad": "thief"}, "score": {"anrbj666": 20, "najamjad": 5}, '
    '"sub_game_number": 1, "winner_group": "anrbj666"}, {"result": '
    '"capture", "roles": {"anrbj666": "thief", "najamjad": "police"}, '
    '"score": {"anrbj666": 5, "najamjad": 20}, "sub_game_number": 2, '
    '"winner_group": "najamjad"}, {"result": "capture", "roles": '
    '{"anrbj666": "police", "najamjad": "thief"}, "score": {"anrbj666": 20, '
    '"najamjad": 5}, "sub_game_number": 3, "winner_group": "anrbj666"}, '
    '{"result": "capture", "roles": {"anrbj666": "thief", "najamjad": '
    '"police"}, "score": {"anrbj666": 5, "najamjad": 20}, "sub_game_number": '
    '4, "winner_group": "najamjad"}, {"result": "capture", "roles": '
    '{"anrbj666": "police", "najamjad": "thief"}, "score": {"anrbj666": 20, '
    '"najamjad": 5}, "sub_game_number": 5, "winner_group": "anrbj666"}, '
    '{"result": "capture", "roles": {"anrbj666": "thief", "najamjad": '
    '"police"}, "score": {"anrbj666": 5, "najamjad": 20}, "sub_game_number": '
    '6, "winner_group": "najamjad"}]}')
ANRBJ_DIGEST = \
    "a3645e1f1f554cce75cf419ebe089efa8e93ccd5af1c87b22d5c3f5d8529b597"


def _anrbj_rows():
    """The anrbj666 series as OUR internal rows, from anrbj666's perspective:
    anrbj666 is police (and captures) on 1/3/5, najamjad on 2/4/6."""
    rows = []
    for n in (1, 3, 5):
        rows.append(_mk_row(n, POLICE, "capture", POLICE, "a" * 40, 20, 5))
    for n in (2, 4, 6):
        rows.append(_mk_row(n, THIEF, "capture", POLICE, "a" * 40, 20, 5))
    return rows


def test_golden_anrbj666_preimage_and_digest_through_our_builder():
    """NajAmjad's real filed example must reproduce byte-for-byte and
    hash-for-hash through OUR real builder + digest function."""
    doc = N.build_mutual_doc(
        "anrbj666-vs-najamjad",
        N.group_rows(_anrbj_rows(), "anrbj666", "najamjad"),
        "anrbj666", "najamjad")
    preimage = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    assert preimage == ANRBJ_PREIMAGE            # byte-for-byte, spaced form
    assert N.mutual_digest(doc) == ANRBJ_DIGEST
    assert hashlib.sha256(preimage.encode("utf-8")).hexdigest() == ANRBJ_DIGEST


def test_tie_raw_75_signed_77_no_tie_award_key(tmp_path):
    """Clean 3-3 capture tie: raw sum is 75-75, the SIGNED total_score folds
    the +2 award in (77-77), and tie_award is NOT a signed aggregate key."""
    peer = make_peer(tmp_path)
    grouped = peer._najamjad_group_rows(_tie_rows())
    raw = {"orcai-mj": 0, "najamjad": 0}
    for cr in grouped:
        for group, score in cr["score"].items():
            raw[group] += score
    assert raw == {"orcai-mj": 75, "najamjad": 75}        # raw sub-game sum
    doc = N.build_mutual_doc(GOLDEN_GAME_ID, grouped, "orcai-mj", "najamjad")
    aggregate = doc["aggregate"]
    assert aggregate["total_score"] == {"orcai-mj": 77, "najamjad": 77}
    assert aggregate["winner_group"] is None
    assert aggregate["series_tie"] is True
    assert aggregate["sub_games_won"] == {"orcai-mj": 3, "najamjad": 3}
    assert aggregate["ties"] == 0
    assert "tie_award" not in aggregate
    assert set(aggregate) == {"series_tie", "sub_games_won", "ties",
                              "total_score", "winner_group"}


def test_signed_preimage_shape_is_exact():
    """Aggregate: exactly five keys. Rows: exactly five keys. Top level:
    exactly three keys. game_uid and every other report field excluded."""
    doc = N.build_mutual_doc(
        "anrbj666-vs-najamjad",
        N.group_rows(_anrbj_rows(), "anrbj666", "najamjad"),
        "anrbj666", "najamjad")
    assert set(doc) == {"game_id", "aggregate", "sub_games"}
    assert set(doc["aggregate"]) == {"series_tie", "sub_games_won", "ties",
                                     "total_score", "winner_group"}
    for row in doc["sub_games"]:
        assert set(row) == {"result", "roles", "score", "sub_game_number",
                            "winner_group"}
    text = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    for banned in ("game_uid", "tie_award", "github_commit", "steps",
                   "timestamp", "tokens", "audit", "log_files"):
        assert banned not in text
    assert '"total_score": {' in text            # spaced/default separators


def test_non_tie_totals_unaffected_and_no_award(tmp_path):
    peer = make_peer(tmp_path)
    rows = _tie_rows()
    rows[5] = _mk_row(6, THIEF, "survival", THIEF, "b" * 40, 5, 10)  # we survive
    doc = N.build_mutual_doc(GOLDEN_GAME_ID, peer._najamjad_group_rows(rows),
                             "orcai-mj", "najamjad")
    aggregate = doc["aggregate"]
    assert aggregate["series_tie"] is False
    assert aggregate["winner_group"] == "orcai-mj"
    assert aggregate["total_score"] == {"orcai-mj": 80, "najamjad": 60}  # raw
    assert "tie_award" not in aggregate


# =========================================================================
# §2.4.2 — strict agent separation + the post-match aggregator
# =========================================================================
def _make_role_dirs(tmp_path, rows=None):
    """Two INDEPENDENT role-owned artifact sets, exactly as the two gameplay
    processes produce them — no shared directory anywhere."""
    rows = rows if rows is not None else _tie_rows()
    cop_dir, thief_dir = tmp_path / "cop-artifacts", tmp_path / "thief-artifacts"
    cop = make_peer(cop_dir, natural_role=POLICE)
    thief = make_peer(thief_dir, natural_role=THIEF)
    cop.rows = [r for r in rows if r["index"] in (1, 3, 5)]
    thief.rows = [r for r in rows if r["index"] in (2, 4, 6)]
    cop._compute_ids(), thief._compute_ids()
    for row in cop.rows:
        cop._write_row_file(row)
    for row in thief.rows:
        thief._write_row_file(row)
    cop.build_najamjad_role_result()
    thief.build_najamjad_role_result()
    return cop_dir, thief_dir


def _dir_fingerprint(path: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.glob("*.json"))}


def test_gameplay_peer_has_no_sibling_reading_code():
    """The gameplay class must not even HAVE merge/dispatch machinery: the
    six-row report and the email belong exclusively to the aggregator."""
    assert not hasattr(ReferenceSeriesPeer, "_collect_all_rows")
    assert not hasattr(ReferenceSeriesPeer, "build_najamjad_result")
    assert not hasattr(ReferenceSeriesPeer, "_dispatch_report_najamjad")


def test_role_partial_ignores_foreign_row_files_and_needs_no_sibling(tmp_path):
    """Tests 1-4: each process finalizes from ITS OWN rows only, instantly,
    with the sibling's artifacts completely unavailable — and even a foreign
    row file dropped into its directory is not read back into its result."""
    peer = make_peer(tmp_path, natural_role=POLICE)      # plays 1/3/5
    peer.rows = [r for r in _tie_rows() if r["index"] in (1, 3, 5)]
    peer._compute_ids()
    for row in [r for r in _tie_rows() if r["index"] in (2, 4, 6)]:
        peer._write_row_file(row)          # foreign rows present on disk
    body = peer.build_najamjad_role_result()
    assert body["report_type"] == "najamjad_role_partial_result"
    assert body["windows_played"] == [1, 3, 5]           # own windows ONLY
    assert body["num_sub_games"] == 3 == body["windows_expected"]
    assert body["mutual_agreement"]["sha256"] == ""      # deferred, not invented
    assert body["series_winner"] == "pending-aggregation"
    assert "deferred" in body["report_status"]["status"]
    assert not (tmp_path / f"result_{GOLDEN_GAME_ID}.json").exists()


def test_role_partial_carries_own_commit_per_window(tmp_path):
    peer = make_peer(tmp_path, natural_role=THIEF)       # plays 2/4/6
    peer.rows = [r for r in _tie_rows() if r["index"] in (2, 4, 6)]
    peer._compute_ids()
    body = peer.build_najamjad_role_result()
    assert [r["github_commit"]["orcai-mj"] for r in body["sub_games"]] == \
        ["b" * 40, "b" * 40, "b" * 40]


def test_aggregator_merges_two_finalized_sets(tmp_path):
    """Tests 5 + per-window commits + tie rule end-to-end."""
    cop_dir, thief_dir = _make_role_dirs(tmp_path)
    fake = _FakeSender()
    outcome = R.aggregate(cop_dir, thief_dir, tmp_path / "team", "friendly",
                          sender_factory=lambda: fake, log=lambda *_: None)
    assert outcome["status"] == "ok"
    body = outcome["body"]
    commits = {r["sub_game_number"]: r["github_commit"]["orcai-mj"]
               for r in body["sub_games"]}
    assert commits == {1: "a" * 40, 3: "a" * 40, 5: "a" * 40,
                       2: "b" * 40, 4: "b" * 40, 6: "b" * 40}
    assert body["num_sub_games"] == 6
    assert body["final_result"]["total_score"] == \
        {"orcai-mj": 77, "najamjad": 77}           # SIGNED totals (award in)
    assert body["final_result"]["raw_total_score"] == \
        {"orcai-mj": 75, "najamjad": 75}           # display only
    assert body["final_result"]["tie_award"] == 2  # display only, outside preimage
    expected_rows = sorted(_tie_rows(), key=lambda r: r["index"])
    assert body["mutual_agreement"]["sha256"] == N.mutual_digest(
        N.build_mutual_doc(GOLDEN_GAME_ID,
                           N.group_rows(expected_rows, "orcai-mj", "najamjad"),
                           "orcai-mj", "najamjad"))
    assert (tmp_path / "team" / f"result_{GOLDEN_GAME_ID}.json").exists()


def test_aggregator_refuses_an_incomplete_series(tmp_path):
    """Tests 6 + 8: fewer than six finalized windows -> suppressed, no team
    result written, no email — never invented values."""
    cop_dir, thief_dir = _make_role_dirs(tmp_path)
    (cop_dir / f"row_{GOLDEN_GAME_ID}_g03.json").unlink()
    fake = _FakeSender()
    outcome = R.aggregate(cop_dir, thief_dir, tmp_path / "team", "counted",
                          sender_factory=lambda: fake, log=lambda *_: None)
    assert outcome["status"] == "suppressed"
    assert "incomplete" in outcome["reason"]
    assert not (tmp_path / "team" / f"result_{GOLDEN_GAME_ID}.json").exists()
    assert not fake.sent


def test_aggregator_refuses_contradictory_role_artifacts(tmp_path):
    """Test 8: the same window claimed by both role processes is a
    contradiction — suppress, do not pick a side."""
    cop_dir, thief_dir = _make_role_dirs(tmp_path)
    contested = thief_dir / f"row_{GOLDEN_GAME_ID}_g02.json"
    (cop_dir / f"row_{GOLDEN_GAME_ID}_g02.json").write_text(
        contested.read_text(encoding="utf-8"), encoding="utf-8")
    fake = _FakeSender()
    outcome = R.aggregate(cop_dir, thief_dir, tmp_path / "team", "friendly",
                          sender_factory=lambda: fake, log=lambda *_: None)
    assert outcome["status"] == "suppressed"
    assert "BOTH role processes" in outcome["reason"]
    assert not fake.sent


def test_aggregator_never_alters_role_owned_artifacts(tmp_path):
    """Test 7: the two source artifact sets are byte-identical before and
    after aggregation — the aggregator is a reader, never a writer, there."""
    cop_dir, thief_dir = _make_role_dirs(tmp_path)
    before = (_dir_fingerprint(cop_dir), _dir_fingerprint(thief_dir))
    R.aggregate(cop_dir, thief_dir, tmp_path / "team", "friendly",
                sender_factory=_FakeSender, log=lambda *_: None)
    assert (_dir_fingerprint(cop_dir), _dir_fingerprint(thief_dir)) == before


def test_exactly_one_team_result_is_produced(tmp_path):
    """Test 9: role dirs hold only partials; the ONE result_<game_id>.json
    exists in the aggregator's own output directory."""
    cop_dir, thief_dir = _make_role_dirs(tmp_path)
    R.aggregate(cop_dir, thief_dir, tmp_path / "team", "friendly",
                sender_factory=_FakeSender, log=lambda *_: None)
    team_results = list((tmp_path / "team").glob("result_*.json"))
    assert [p.name for p in team_results] == [f"result_{GOLDEN_GAME_ID}.json"]
    for role_dir in (cop_dir, thief_dir):
        assert not (role_dir / f"result_{GOLDEN_GAME_ID}.json").exists()


def test_aggregation_is_deterministic_across_runs(tmp_path):
    """Two independent aggregations of the same finalized sets sign the same
    consensus object — what the two teams will compare before filing."""
    cop_dir, thief_dir = _make_role_dirs(tmp_path)
    one = R.aggregate(cop_dir, thief_dir, tmp_path / "t1", "friendly",
                      sender_factory=_FakeSender, log=lambda *_: None)
    two = R.aggregate(cop_dir, thief_dir, tmp_path / "t2", "friendly",
                      sender_factory=_FakeSender, log=lambda *_: None)
    assert one["body"]["mutual_agreement"]["sha256"] == \
        two["body"]["mutual_agreement"]["sha256"]


# =========================================================================
# §7.4 — reporting: friendly never mails the lecturer; counted does
# =========================================================================
class _FakeSender:
    def __init__(self):
        self.recipient = None
        self.mode = None
        self.sent = []

    def send_series_report(self, paths, summary):
        self.sent.append((dict(paths), dict(summary)))
        return {"status": "sent"}


def _result_stub():
    return {"game_id": GOLDEN_GAME_ID, "series_winner": "tie",
            "all_audits_verified": True}


def test_gameplay_has_no_email_path_only_the_aggregator_does():
    """Test 10: exactly one dispatch path exists, and it is NOT in the
    gameplay peer."""
    assert not hasattr(ReferenceSeriesPeer, "_dispatch_report_najamjad")
    assert callable(R.dispatch_report)


def test_friendly_report_never_reaches_the_lecturer(tmp_path):
    fake = _FakeSender()
    report = R.dispatch_report(_result_stub(), tmp_path, "friendly",
                               tmp_path, tmp_path,
                               sender_factory=lambda: fake)
    assert report["recipient"] == NAJAMJAD_FRIENDLY_RECIPIENT
    assert report["recipient"] != LEAGUE_ADDRESS
    assert fake.recipient == NAJAMJAD_FRIENDLY_RECIPIENT


def test_counted_report_goes_to_the_lecturer_once(tmp_path):
    fake = _FakeSender()
    report = R.dispatch_report(_result_stub(), tmp_path, "counted",
                               tmp_path, tmp_path,
                               sender_factory=lambda: fake)
    assert report["recipient"] == LEAGUE_ADDRESS
    assert report["status"] == "sent"
    again = R.dispatch_report(_result_stub(), tmp_path, "counted",
                              tmp_path, tmp_path,
                              sender_factory=lambda: fake)
    assert again["status"] == "duplicate_suppressed"       # sentinel guard
    assert len(fake.sent) == 1


def test_counted_report_suppressed_on_audit_failures(tmp_path):
    fake = _FakeSender()
    report = R.dispatch_report(
        dict(_result_stub(), all_audits_verified=False), tmp_path, "counted",
        tmp_path, tmp_path, sender_factory=lambda: fake)
    assert report["status"].startswith("suppressed")
    assert not fake.sent


def test_email_disable_env_suppresses_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("P2P_EMAIL_DISABLE", "1")
    fake = _FakeSender()
    report = R.dispatch_report(_result_stub(), tmp_path, "counted",
                               tmp_path, tmp_path,
                               sender_factory=lambda: fake)
    assert "P2P_EMAIL_DISABLE" in report["status"]
    assert not fake.sent


# =========================================================================
# §7.4-attach — dispatch attaches ONLY result_<game_id>.json
# =========================================================================

class _CapturingSender:
    """Like _FakeSender but records the artifact_paths dict for inspection."""
    def __init__(self):
        self.recipient = None
        self.mode = None
        self.captured_paths = None
        self.sent = []

    def send_series_report(self, paths, summary):
        self.captured_paths = dict(paths)
        self.sent.append((dict(paths), dict(summary)))
        return {"status": "sent"}


def _make_role_artifacts_with_extras(tmp_path, game_id=None):
    """Role dirs populated with declaration, config, and log extras to verify
    they are NOT attached by dispatch_report."""
    gid = game_id or GOLDEN_GAME_ID
    cop_dir = tmp_path / "cop-extras"
    thief_dir = tmp_path / "thief-extras"
    cop_dir.mkdir(exist_ok=True)
    thief_dir.mkdir(exist_ok=True)
    for d in (cop_dir, thief_dir):
        (d / f"declaration_{gid}.json").write_text("{}", encoding="utf-8")
        (d / f"config_{gid}_g01.json").write_text("{}", encoding="utf-8")
        (d / f"log_{gid}_g01.json").write_text("{}", encoding="utf-8")
    return cop_dir, thief_dir


def _make_result_file(out_dir, game_id=None):
    gid = game_id or GOLDEN_GAME_ID
    out_dir.mkdir(exist_ok=True, parents=True)
    result = out_dir / f"result_{gid}.json"
    result.write_text("{}", encoding="utf-8")
    return result


def test_friendly_dispatch_attaches_exactly_one_file(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out1"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    assert len(cap.captured_paths) == 1


def test_counted_dispatch_attaches_exactly_one_file(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out2"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "counted",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    assert len(cap.captured_paths) == 1


def test_attachment_key_is_result_and_filename_matches_game_id(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out3"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    assert "result" in cap.captured_paths
    assert cap.captured_paths["result"].name == f"result_{GOLDEN_GAME_ID}.json"


def test_declaration_not_in_attachment_even_when_present(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out4"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    assert "declaration" not in cap.captured_paths


def test_config_files_not_in_attachment_even_when_present(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out5"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    config_keys = [k for k in cap.captured_paths if k.startswith("config_")]
    assert config_keys == []


def test_log_files_not_in_attachment_even_when_present(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out6"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    log_keys = [k for k in cap.captured_paths if k.startswith("log_")]
    assert log_keys == []


def test_role_dir_artifacts_preserved_after_dispatch(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out7"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      cop_dir, thief_dir, sender_factory=lambda: cap)
    for d in (cop_dir, thief_dir):
        assert (d / f"declaration_{GOLDEN_GAME_ID}.json").exists()
        assert (d / f"config_{GOLDEN_GAME_ID}_g01.json").exists()
        assert (d / f"log_{GOLDEN_GAME_ID}_g01.json").exists()


def test_friendly_single_attach_recipient_is_not_lecturer(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out8"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    report = R.dispatch_report(_result_stub(), out_dir, "friendly",
                               cop_dir, thief_dir, sender_factory=lambda: cap)
    assert report["recipient"] == NAJAMJAD_FRIENDLY_RECIPIENT
    assert report["recipient"] != LEAGUE_ADDRESS
    assert len(cap.captured_paths) == 1


def test_counted_single_attach_recipient_is_lecturer(tmp_path):
    cop_dir, thief_dir = _make_role_artifacts_with_extras(tmp_path)
    out_dir = tmp_path / "out9"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    report = R.dispatch_report(_result_stub(), out_dir, "counted",
                               cop_dir, thief_dir, sender_factory=lambda: cap)
    assert report["recipient"] == LEAGUE_ADDRESS
    assert len(cap.captured_paths) == 1


def test_dispatch_sentinel_still_blocks_duplicate_with_single_attach(tmp_path):
    out_dir = tmp_path / "out10"
    _make_result_file(out_dir)
    cap = _CapturingSender()
    R.dispatch_report(_result_stub(), out_dir, "friendly",
                      tmp_path, tmp_path, sender_factory=lambda: cap)
    second = R.dispatch_report(_result_stub(), out_dir, "friendly",
                               tmp_path, tmp_path, sender_factory=lambda: cap)
    assert second["status"] == "duplicate_suppressed"
    assert len(cap.sent) == 1


def test_corrective_email_attaches_only_result_file(tmp_path):
    out_dir = tmp_path / "out11"
    result_path = _make_result_file(out_dir)
    cap = _CapturingSender()
    report = R.send_corrective_friendly(result_path, out_dir,
                                        sender_factory=lambda: cap)
    assert report["status"] == "sent"
    assert len(cap.captured_paths) == 1
    assert "result" in cap.captured_paths
    assert cap.captured_paths["result"] == result_path


def test_corrective_sentinel_independent_of_main_sentinel(tmp_path):
    out_dir = tmp_path / "out12"
    result_path = _make_result_file(out_dir)
    cap = _CapturingSender()
    main_sentinel = out_dir / f"najamjad_report_sent_{GOLDEN_GAME_ID}.lock"
    main_sentinel.write_text("{}", encoding="utf-8")
    report = R.send_corrective_friendly(result_path, out_dir,
                                        sender_factory=lambda: cap)
    assert report["status"] == "sent"
    assert len(cap.sent) == 1
    again = R.send_corrective_friendly(result_path, out_dir,
                                       sender_factory=lambda: cap)
    assert again["status"] == "duplicate_suppressed"
    assert len(cap.sent) == 1


# =========================================================================
# isolation — the other opponents' paths are untouched
# =========================================================================
def test_ahk_yosi_constitution_untouched():
    cfg = Config.load(shared_path=str(ROOT / "config" / "game.json"),
                      private_path=str(ROOT / "config" / "does-not-exist.toml"))
    assert digest(cfg.shared) == \
        "fef1fe3a229b0c7daece9f1e3ebe7a097a7207e6ac0628b6c67050595a6101be"


def test_amireman_constitution_untouched():
    cfg = Config.load(shared_path=str(ROOT / "config" / "game.amireman.json"),
                      private_path=str(ROOT / "config" / "does-not-exist.toml"))
    assert digest(cfg.shared) == \
        "32e86f85c47920c4a567df403bd1f263f1bbea5f59c7db0b7aeb640f30d15812"


def test_najamjad_group_id_is_lowercase_and_isolated():
    cfg = najamjad_config()
    game = cfg.private.get("game", {})
    assert game.get("group_id") == "orcai-mj"        # case-sensitive, THIS opponent
    assert game.get("group_name") == "Orcai-MJ"
    assert game.get("members") == ["Jude Khleif", "Mohammad Akariya"]
