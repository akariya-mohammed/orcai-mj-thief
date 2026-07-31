"""Task 5.3: negotiation logic — payloads, rejection paths, turn order, game ids."""
from police_thief.domain.negotiation import (FIRST_MOVER, REQUIRED_FIELDS,
                                             build_payload, evaluate)
from police_thief.domain.game_ids import make_game_id, make_game_uid


def _payload(role="police", cfg="a" * 64, group="team-x", step0="s" * 64,
             scheme="canonical-json-v1"):
    return build_payload(config_sha256=cfg, group_id=group, role=role,
                         code_version="0.1.0", step0_commit=step0,
                         sealing_scheme=scheme)


def test_payload_contains_all_required_fields():
    p = _payload()
    assert all(f in p for f in REQUIRED_FIELDS)


def test_complementary_roles_and_matching_config_accept():
    ok, reason = evaluate(_payload("police"), _payload("thief", group="team-y"))
    assert ok, reason


def test_config_hash_mismatch_rejects_loudly():
    ok, reason = evaluate(_payload(cfg="a" * 64), _payload("thief", cfg="b" * 64))
    assert not ok and "config" in reason.lower()


def test_same_role_rejects():
    ok, reason = evaluate(_payload("police"), _payload("police", group="team-y"))
    assert not ok and "role" in reason.lower()


def test_missing_field_rejects_politely():
    theirs = _payload("thief")
    del theirs["config_sha256"]
    ok, reason = evaluate(_payload(), theirs)
    assert not ok and "missing" in reason.lower()


def test_missing_step_zero_declaration_rejects():
    # Rule 24/53: a peer that will not seal its hardware and code version before
    # turn 1 cannot be audited for computational fairness afterwards.
    ok, reason = evaluate(_payload("police"), _payload("thief", group="y", step0=""))
    assert not ok and "step-0" in reason.lower()


def test_sealing_scheme_mismatch_rejects():
    # If we cannot recompute each other's digests, the mutual audit is theatre.
    ok, reason = evaluate(_payload("police"),
                          _payload("thief", group="y", scheme="their-own-v2"))
    assert not ok and "sealing scheme" in reason.lower()


def test_thief_moves_first():
    # Intel I3 (provisional, relayed): "the Thief always moves first" — matches
    # our sim convention; enforced structurally from here on.
    assert FIRST_MOVER == "thief"


def test_game_ids_deterministic_and_symmetric():
    assert make_game_id("alpha", "beta") == "alpha-vs-beta"
    uid_a = make_game_uid("alpha", "beta", "c" * 64)
    uid_b = make_game_uid("beta", "alpha", "c" * 64)     # both peers compute the SAME uid
    assert uid_a == uid_b and len(uid_a) == 16
    assert make_game_uid("alpha", "beta", "d" * 64) != uid_a
