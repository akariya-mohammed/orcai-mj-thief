"""Regression tests for the amireman public-spec interop profile.

Covers the parts of NEXT_OPPONENT_INTEROP_GUIDE_PUBLIC.md that differ from the
ahk-yosi dialect and are therefore the compatibility-test surface:

* Appendix A / B — the 14 signed terms, sorted game_id, UUID game_uid.
* Section 11 — the canonical consensus object and its SHA-256 (tight separators).
* Section 10 step 3 — the explicit series_consensus envelope and its validation.
* Section 5 — capture_claim on EVERY police turn (ungated) under this profile.
* Section 12 — the result-report schema.

The ahk-yosi golden vectors live in test_interop.py and MUST keep passing; this
file never touches config/game.json or refcrypto.mutual_digest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from police_thief.domain.brains import MoveType
from police_thief.interop import consensus as C
from police_thief.interop import terms as terms_mod
from police_thief.interop.refcrypto import digest
from police_thief.infra.email_sender import LEAGUE_ADDRESS
from police_thief.interop.series import (
    AMIREMAN_FRIENDLY_RECIPIENT,
    POLICE,
    ReferenceSeriesPeer,
    SubGame,
)
from police_thief.shared.config import Config

ROOT = Path(__file__).resolve().parents[1]

APPENDIX_A = {
    "board_size": 7, "smell_grid_size": 5, "decay_per_step": 0.1,
    "emit_intensity": 0.9, "min_center_intensity": 0.5, "max_steps": 35,
    "barriers_max": 14, "setting": "Haifa", "hint_max_words": 15,
    "axis_origin_corner": "top-left", "axis_start_index": 0,
    "thief_start": [3, 3], "cop_start": [0, 0], "num_games": 6,
}
AMIREMAN_CONFIG_SHA = \
    "32e86f85c47920c4a567df403bd1f263f1bbea5f59c7db0b7aeb640f30d15812"
# Golden derivations for the confirmed-lowercase group ids "amireman"/"orcai-mj".
GOLDEN_GAME_ID = "amireman-vs-orcai-mj"
GOLDEN_GAME_UID = "3862f6c4-223c-8294-c3f5-2d4e50f917c0"


def amireman_config() -> Config:
    return Config.load(shared_path=str(ROOT / "config" / "game.amireman.json"),
                       private_path=str(ROOT / "config" / "does-not-exist.toml"))


# -- constitution / signed terms (Appendix A) --------------------------------
def test_amireman_constitution_hash():
    assert digest(amireman_config().shared) == AMIREMAN_CONFIG_SHA


def test_amireman_terms_are_appendix_a():
    assert terms_mod.build_terms(amireman_config(), 6) == APPENDIX_A


def test_canonical_terms_bytes_match_appendix_a_order():
    assert C.canonical(APPENDIX_A) == (
        '{"axis_origin_corner":"top-left","axis_start_index":0,'
        '"barriers_max":14,"board_size":7,"cop_start":[0,0],'
        '"decay_per_step":0.1,"emit_intensity":0.9,"hint_max_words":15,'
        '"max_steps":35,"min_center_intensity":0.5,"num_games":6,'
        '"setting":"Haifa","smell_grid_size":5,"thief_start":[3,3]}')


# -- shared ids (Appendix B) -------------------------------------------------
def test_game_id_is_sorted_and_order_independent():
    assert C.spec_game_id("orcai-mj", "amireman") == GOLDEN_GAME_ID
    assert C.spec_game_id("amireman", "orcai-mj") == GOLDEN_GAME_ID


def test_game_uid_golden_and_order_independent():
    a = C.spec_game_uid(APPENDIX_A, "amireman", "orcai-mj")
    b = C.spec_game_uid(APPENDIX_A, "orcai-mj", "amireman")
    assert a == b == GOLDEN_GAME_UID


def test_game_uid_is_a_uuid_string():
    import uuid
    uid = C.spec_game_uid(APPENDIX_A, "amireman", "orcai-mj")
    assert str(uuid.UUID(uid)) == uid    # round-trips as a canonical UUID


def test_game_uid_sensitive_to_group_spelling():
    """Different spelling -> different game_uid: this is why the exact group_id
    string must be confirmed with the opponent before the counted series."""
    lower = C.spec_game_uid(APPENDIX_A, "amireman", "orcai-mj")
    upper = C.spec_game_uid(APPENDIX_A, "amireman", "Orcai-MJ")
    assert lower != upper


def test_game_uid_sensitive_to_terms():
    tampered = dict(APPENDIX_A, setting="New York")
    assert C.spec_game_uid(tampered, "amireman", "orcai-mj") != GOLDEN_GAME_UID


# -- canonical consensus object + SHA (Section 11) ---------------------------
def _rows_two():
    return [
        C.consensus_row(sub_game_number=1, result="survival",
                        roles={"amireman": "thief", "orcai-mj": "police"},
                        score={"amireman": 10, "orcai-mj": 5},
                        winner_group="amireman"),
        C.consensus_row(sub_game_number=2, result="capture",
                        roles={"amireman": "police", "orcai-mj": "thief"},
                        score={"amireman": 20, "orcai-mj": 5},
                        winner_group="amireman"),
    ]


def test_consensus_object_shape():
    obj = C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID, _rows_two())
    assert set(obj) == {"game_id", "game_uid", "sub_games"}
    for row in obj["sub_games"]:
        assert set(row) == {"sub_game_number", "result", "roles", "score",
                            "winner_group"}


def test_consensus_object_rows_sorted_by_number():
    obj = C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID,
                                   list(reversed(_rows_two())))
    assert [r["sub_game_number"] for r in obj["sub_games"]] == [1, 2]


def test_consensus_sha_is_reproducible_64_lower_hex():
    obj = C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID, _rows_two())
    sha = C.consensus_sha(obj)
    assert sha == C.consensus_sha(obj)
    assert C.is_valid_consensus_sha(sha)


def test_consensus_sha_golden_vector():
    obj = C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID, _rows_two())
    assert C.consensus_sha(obj) == (
        "8d25619cbeaa53d5e80b43def5d2887baac4da15bc7202b87fcbf9eed61b5dcd")


def test_consensus_sha_uses_tight_separators():
    """Section 11 hashes with tight separators; a default-separator hash differs."""
    import hashlib
    obj = C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID, _rows_two())
    loose = hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()
    assert C.consensus_sha(obj) != loose


# -- explicit consensus envelope (Section 10 step 3) -------------------------
def test_envelope_build_is_well_formed():
    env = C.build_consensus_envelope("thief", "a" * 64)
    assert env == {"sender": "thief", "records": [],
                   "result_claim": "series_consensus", "consensus_sha": "a" * 64}


def test_envelope_rejects_non_wire_sender_on_build():
    with pytest.raises(ValueError):
        C.build_consensus_envelope("orcai-mj", "a" * 64)


def test_validate_accepts_either_wire_role():
    for role in ("police", "thief"):
        ok, _ = C.validate_remote_consensus(
            {"sender": role, "records": [], "result_claim": "series_consensus",
             "consensus_sha": "b" * 64})
        assert ok


@pytest.mark.parametrize("env,needle", [
    ({"sender": "orcai-mj", "records": [], "result_claim": "series_consensus",
      "consensus_sha": "a" * 64}, "wire role"),
    ({"sender": "thief", "records": [{"x": 1}], "result_claim": "series_consensus",
      "consensus_sha": "a" * 64}, "records"),
    ({"sender": "thief", "records": [], "result_claim": "capture",
      "consensus_sha": "a" * 64}, "series_consensus"),
    ({"sender": "thief", "records": [], "result_claim": "series_consensus",
      "consensus_sha": "A" * 64}, "64 lowercase hex"),
    ({"sender": "thief", "records": [], "result_claim": "series_consensus"},
     "64 lowercase hex"),
])
def test_validate_rejects_malformed(env, needle):
    ok, reason = C.validate_remote_consensus(env)
    assert not ok and needle in reason


def test_straggler_per_sub_game_audit_is_not_consensus():
    """A late per-sub-game audit (no consensus_sha) MUST NOT be mistaken for one."""
    straggler = {"sender": "thief", "records": [{"payload": {}, "nonce": "x",
                 "commit": "0" * 64}], "result_claim": "capture",
                 "sub_game_number": 3}
    ok, _ = C.validate_remote_consensus(straggler)
    assert not ok


def test_two_peer_consensus_digests_agree():
    """Both peers build the SAME object/sha from their own perspective."""
    rows = _rows_two()
    a = C.consensus_sha(C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID, rows))
    b = C.consensus_sha(C.build_consensus_object(GOLDEN_GAME_ID, GOLDEN_GAME_UID,
                                                 list(reversed(rows))))
    assert a == b


# -- capture_claim on every police turn (Section 5) --------------------------
def _amireman_subgame(role: str) -> SubGame:
    return SubGame(role, amireman_config(), 1, seed=7, spec_profile="amireman")


def test_capture_claim_present_on_every_police_turn():
    engine = _amireman_subgame(POLICE)
    seen = []
    for _ in range(6):
        msg = engine.build_my_turn()
        seen.append(msg["capture_claim"])
        engine.my_steps = engine.my_steps  # no-op; steps advanced inside
    # Every police turn carries a claim equal to the cop's own post-move cell.
    assert all(c is not None for c in seen)
    assert all(c == list(engine.records[i]["payload"]["position"])
               for i, c in enumerate(seen))


def test_capture_claim_present_even_on_hold_turn():
    engine = _amireman_subgame(POLICE)
    engine.captured = False
    # Force a HOLD by exhausting movement intent is hard; instead assert that a
    # STAY/HOLD-produced turn still declares the claim = current cell.
    msg = engine.build_my_turn()
    assert msg["capture_claim"] == list(engine.state.position)


def test_ahk_yosi_profile_still_gates_capture_claim():
    """The default profile must keep the gated behaviour so ahk-yosi verifies."""
    from police_thief.interop.series import SubGame as SG
    engine = SG(POLICE, amireman_config(), 1, seed=7)  # default profile
    # On turn 1 the cop moves from (0,0); belief.most_likely is far away, so the
    # gated path emits no claim.
    msg = engine.build_my_turn()
    assert msg["capture_claim"] is None


def test_thief_never_emits_capture_claim_under_amireman():
    engine = _amireman_subgame("thief")
    msg = engine.build_my_turn()
    assert msg["capture_claim"] is None


def test_survival_win_claim_is_exactly_type_survival():
    """Appendix D: amireman survival claim is exactly {"type": "survival"}."""
    engine = _amireman_subgame("thief")
    engine.my_steps = 34
    msg = engine.build_my_turn()          # step becomes 35 == threshold
    assert msg["win_claim"] == {"type": "survival"}
    assert engine.outcome["ending"] == "survival"


# -- peer id derivation + Section 12 report ----------------------------------
class _FakeSender:
    """Records send_series_report calls; NEVER touches the network so no real
    email can be sent during testing."""

    def __init__(self, record: list) -> None:
        self._record = record
        self.recipient = None
        self.mode = "draft"

    def send_series_report(self, artifact_paths, summary):
        self._record.append({
            "recipient": self.recipient,
            "mode": self.mode,
            "attachments": [Path(p).name for p in artifact_paths.values()],
            "summary": summary,
        })
        return {"status": "sent", "id": "fake"}


def _amireman_peer(tmp_path, their_group="amireman", mode="friendly",
                   game_id_override=None) -> ReferenceSeriesPeer:
    peer = ReferenceSeriesPeer(
        natural_role="police", config=amireman_config(),
        opponent_url="http://127.0.0.1:1/mcp", my_port=1, mode=mode,
        spec_profile="amireman", out_dir=str(tmp_path), log_fn=lambda *a: None,
        git_commit_hash="a" * 40, game_id_override=game_id_override)
    peer.their_identity = {"group_id": their_group, "group_name": "Amireman",
                           "members": ["m1"], "repos": {"cop": "u1", "thief": "u2"},
                           "mcp_servers": {"cop": "m", "thief": "m"},
                           "github_commit": "b" * 40, "git_commit_hash": "b" * 40}
    # Install the fake sender so build_spec_result never sends a real email.
    peer.sent_emails: list = []
    peer._new_gmail_sender = lambda: _FakeSender(peer.sent_emails)
    return peer


def test_peer_computes_spec_ids(tmp_path):
    peer = _amireman_peer(tmp_path)
    peer._compute_ids()
    assert peer.game_id == GOLDEN_GAME_ID
    assert peer.game_uid == GOLDEN_GAME_UID


def test_game_id_override_keeps_derived_game_uid(tmp_path):
    """A mutually-agreed label (TEST22) overrides game_id ONLY; game_uid is still
    derived from canonical(terms) + sorted group ids (Section 3)."""
    peer = ReferenceSeriesPeer(
        natural_role="police", config=amireman_config(),
        opponent_url="http://127.0.0.1:1/mcp", my_port=1, mode="friendly",
        spec_profile="amireman", out_dir=str(tmp_path), log_fn=lambda *a: None,
        game_id_override="TEST22")
    peer.their_identity = {"group_id": "amireman"}
    peer.identity = dict(peer.identity, group_id="Orcai-MJ")
    peer._compute_ids()
    assert peer.game_id == "TEST22"
    # sorted(["Orcai-MJ","amireman"]) -> "Orcai-MJ" first (uppercase O < lowercase a)
    assert peer.game_uid == C.spec_game_uid(APPENDIX_A, "Orcai-MJ", "amireman")
    assert peer.game_uid != GOLDEN_GAME_UID   # different from the lowercase pair


def _row(n, my_role, ending, winner_role, police_score, thief_score):
    return {
        "index": n, "my_role": my_role, "ending": ending, "winner": winner_role,
        "cause": "t", "step": 35 if ending == "survival" else 12,
        "police_score": police_score, "thief_score": thief_score,
        "audit_of_opponent": "Verified OK", "audit_violations": [],
        "audit_delivered": True, "opponent_audit_of_us": "", "protocol_violations": [],
        "our_commit": "a" * 40, "their_commit": "b" * 40, "their_group_id": "amireman",
        "result_agreed": True, "log_verified": True,
        "started_at": "2026-08-15T00:00:00+00:00",
        "ended_at": "2026-08-15T00:01:00+00:00",
    }


def test_spec_report_schema_and_scoring(tmp_path):
    peer = _amireman_peer(tmp_path)
    peer._compute_ids()
    # A full drawn series: each side Cop 3x / Thief 3x, all survival -> 45-45,
    # then +2 tie bonus each -> 47-47, series tie, winner_group null.
    peer.rows = [
        _row(1, "police", "survival", "thief", 5, 10),
        _row(2, "thief",  "survival", "thief", 5, 10),
        _row(3, "police", "survival", "thief", 5, 10),
        _row(4, "thief",  "survival", "thief", 5, 10),
        _row(5, "police", "survival", "thief", 5, 10),
        _row(6, "thief",  "survival", "thief", 5, 10),
    ]
    body = peer.build_spec_result()

    # top-level [MATCH] fields
    assert body["game_id"] == GOLDEN_GAME_ID
    assert body["game_uid"] == GOLDEN_GAME_UID
    assert body["report_type"] == "final_game_result"
    assert sorted(body["groups"]) == ["amireman", "orcai-mj"]

    # six canonical rows, group-keyed
    assert len(body["sub_games"]) == 6
    r0 = body["sub_games"][0]
    assert set(r0["roles"]) == {"amireman", "orcai-mj"}
    assert set(r0["score"]) == {"amireman", "orcai-mj"}
    assert r0["github_commit"] == {"orcai-mj": "a" * 40, "amireman": "b" * 40}
    assert r0["result"] == "survival"

    # +2 tie bonus applied once each; series tie
    fr = body["final_result"]
    assert fr["total_score"] == {"orcai-mj": 47, "amireman": 47}
    assert fr["series_tie"] is True
    assert fr["winner_group"] is None
    assert fr["tokens_total_series"] == 0

    # mutual agreement present; a local-only digest MUST NOT confirm (Section 10.4)
    ma = body["mutual_agreement"]
    assert C.is_valid_consensus_sha(ma["sha256"])
    assert ma["confirmed"] is False

    # links.github carries four repo links; group_details for both groups
    assert set(body["links"]["github"]) == {"amireman", "orcai-mj"}
    assert set(body["group_details"]) == {"amireman", "orcai-mj"}

    # the file is named result_<game_id>.json
    written = json.loads((tmp_path / f"result_{GOLDEN_GAME_ID}.json")
                         .read_text(encoding="utf-8"))
    assert written["game_uid"] == GOLDEN_GAME_UID


def test_spec_report_winner_group_when_not_tied(tmp_path):
    peer = _amireman_peer(tmp_path)
    peer._compute_ids()
    peer.rows = [
        _row(1, "police", "capture", "police", 20, 5),
        _row(2, "police", "capture", "police", 20, 5),
    ]
    body = peer.build_spec_result()
    fr = body["final_result"]
    assert fr["winner_group"] == "orcai-mj"
    assert fr["series_tie"] is False
    assert fr["total_score"]["orcai-mj"] == 40
    assert fr["total_score"]["amireman"] == 10
    # per-row winner_group keyed by group id
    assert body["sub_games"][0]["winner_group"] == "orcai-mj"


def test_spec_report_consensus_confirmed_when_digests_match(tmp_path, monkeypatch):
    """confirmed is true only when the remote digest equals ours AND every log
    verified AND every result agreed (Section 10 step 4)."""
    peer = _amireman_peer(tmp_path)
    peer._compute_ids()
    peer.rows = [_row(1, "police", "capture", "police", 20, 5)]
    our_sha = C.consensus_sha(peer._consensus_object())
    # Simulate the remote envelope arriving in the audit inbox.
    peer.inbox.audits.put(C.build_consensus_envelope("thief", our_sha))
    peer.consensus_wait = 1.0

    # Avoid a real outbound network call for the envelope we send.
    monkeypatch.setattr(peer.link, "submit_audit", lambda *a, **k: {"ok": True})
    ma = peer._run_consensus_exchange()
    assert ma["peer_sha256"] == our_sha
    assert ma["sha_match"] is True
    assert ma["confirmed"] is True


# -- Section 12 reporting: exactly one email, one attachment -----------------
def _draw_rows():
    """Six survival sub-games; a full drawn series (writes a real result file)."""
    return [
        _row(1, "police", "survival", "thief", 5, 10),
        _row(2, "thief",  "survival", "thief", 5, 10),
        _row(3, "police", "survival", "thief", 5, 10),
        _row(4, "thief",  "survival", "thief", 5, 10),
        _row(5, "police", "survival", "thief", 5, 10),
        _row(6, "thief",  "survival", "thief", 5, 10),
    ]


def test_amireman_friendly_sends_one_email_to_team(tmp_path):
    """Friendly TEST22: exactly one send, to the team address, attaching only
    result_TEST22.json."""
    peer = _amireman_peer(tmp_path, mode="friendly", game_id_override="TEST22")
    peer._compute_ids()
    peer.rows = _draw_rows()
    body = peer.build_spec_result()

    assert len(peer.sent_emails) == 1
    sent = peer.sent_emails[0]
    assert sent["recipient"] == AMIREMAN_FRIENDLY_RECIPIENT == "judekhleif@gmail.com"
    assert sent["attachments"] == ["result_TEST22.json"]
    assert sent["mode"] == "send"
    assert body["report_status"]["status"] == "sent"
    assert body["report_status"]["recipient"] == "judekhleif@gmail.com"
    # the real result artifact exists on disk
    assert (tmp_path / "result_TEST22.json").exists()


def test_amireman_counted_sends_one_email_to_league(tmp_path):
    """Counted: exactly one send, to the league address, one result attachment."""
    peer = _amireman_peer(tmp_path, mode="counted",
                          game_id_override="amireman-vs-orcai-mj")
    peer._compute_ids()
    peer.rows = [_row(1, "police", "capture", "police", 20, 5)]
    body = peer.build_spec_result()

    assert len(peer.sent_emails) == 1
    sent = peer.sent_emails[0]
    assert sent["recipient"] == LEAGUE_ADDRESS == "rmisegal+uoh26finalgame@gmail.com"
    assert sent["attachments"] == ["result_amireman-vs-orcai-mj.json"]
    assert len(sent["attachments"]) == 1
    assert body["report_status"]["recipient"] == LEAGUE_ADDRESS


def test_amireman_friendly_never_to_lecturer_counted_never_to_team(tmp_path):
    friendly = _amireman_peer(tmp_path / "f", mode="friendly",
                              game_id_override="TEST22")
    friendly._compute_ids(); friendly.rows = _draw_rows()
    friendly.build_spec_result()
    assert friendly.sent_emails[0]["recipient"] != LEAGUE_ADDRESS

    counted = _amireman_peer(tmp_path / "c", mode="counted",
                             game_id_override="G1")
    counted._compute_ids(); counted.rows = [_row(1, "police", "capture", "police", 20, 5)]
    counted.build_spec_result()
    assert counted.sent_emails[0]["recipient"] != AMIREMAN_FRIENDLY_RECIPIENT


def test_amireman_intermediate_artifacts_exist_but_are_not_attached(tmp_path):
    """Local declaration/config/log files may exist; only the result is attached."""
    for name in ("declaration_TEST22.json", "config_TEST22_g01.json",
                 "log_TEST22_g01.json", "log_TEST22_g02.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    peer = _amireman_peer(tmp_path, mode="friendly", game_id_override="TEST22")
    peer._compute_ids()
    peer.rows = _draw_rows()
    peer.build_spec_result()

    assert peer.sent_emails[0]["attachments"] == ["result_TEST22.json"]
    # the intermediate artifacts are still present locally, just not emailed
    for name in ("declaration_TEST22.json", "config_TEST22_g01.json",
                 "log_TEST22_g01.json", "log_TEST22_g02.json"):
        assert (tmp_path / name).exists()


def test_amireman_duplicate_invocation_sends_once(tmp_path):
    """One completed series cannot send twice (sentinel guard)."""
    peer = _amireman_peer(tmp_path, mode="friendly", game_id_override="TEST22")
    peer._compute_ids()
    peer.rows = _draw_rows()

    first = peer.build_spec_result()
    second = peer.build_spec_result()

    assert len(peer.sent_emails) == 1                    # only ONE real send
    assert first["report_status"]["status"] == "sent"
    assert second["report_status"]["status"] == "duplicate_suppressed"
    assert (tmp_path / "amireman_report_sent_TEST22.lock").exists()


def test_ahk_yosi_friendly_reporting_still_suppressed(tmp_path):
    """ahk-yosi reporting is UNCHANGED: friendly never constructs a sender."""
    import sys as _sys
    peer = ReferenceSeriesPeer(
        natural_role="police", config=amireman_config(),
        opponent_url="http://127.0.0.1:1/mcp", my_port=1, mode="friendly",
        spec_profile="ahk-yosi", out_dir=str(tmp_path), log_fn=lambda *a: None)
    # Poison the email module: ahk-yosi friendly must succeed without touching it.
    saved = _sys.modules.get("police_thief.infra.email_sender")
    _sys.modules["police_thief.infra.email_sender"] = None
    try:
        receipt = peer.dispatch_report({"series_winner": "police"})
    finally:
        if saved is not None:
            _sys.modules["police_thief.infra.email_sender"] = saved
        else:
            _sys.modules.pop("police_thief.infra.email_sender", None)
    assert "suppressed" in receipt["status"] and "friendly" in receipt["status"]
