"""Task 7.1: the 4 mandatory artifacts conform EXACTLY to the pinned schemas."""
import json
from pathlib import Path

from police_thief.domain.game_ids import artifact_filenames
from police_thief.report import artifact_schemas as S
from police_thief.report.report_writer import (build_declaration, build_config_artifact,
                                               build_group_block, build_log, build_result,
                                               write_artifacts)
from police_thief.shared.config import canonical_sha256

SHARED = json.loads((Path(__file__).resolve().parents[1] / "config" / "game.json")
                    .read_text(encoding="utf-8"))

IDENTITY = {"group_id": "orcai-mj", "group_name": "Orcai-MJ",
            "members": ["id-1001", "id-1002"],
            "repos": {"cop": "https://x/cop", "thief": "https://x/thief"},
            "mcp_servers": ["http://1.2.3.4/mcp"], "llm_model": "template",
            "spec": {"os": "Windows 11"}}
LINKS = {"group_1": IDENTITY["repos"], "group_2": IDENTITY["repos"]}


def _records():
    return [{"commit": "c" * 64, "nonce": "n" * 32, "state": "s", "move": "MOVE:S",
             "intent": "truth", "hint": ""}]


def test_declaration_conforms_to_schema():
    d = build_declaration("a-vs-b", "uid1", LINKS, own=IDENTITY, opponent=IDENTITY,
                          game_started_at="2026-07-26T10:00:00",
                          game_ended_at="2026-07-26T10:30:00",
                          num_sub_games=6, max_tokens_per_game=200000)
    assert set(d) == set(S.DECLARATION_FIELDS)
    assert d["declaration_type"] == "pre_game_declaration"
    for block in d["groups"].values():
        assert set(block) == set(S.GROUP_BLOCK_FIELDS)


def test_config_artifact_conforms_and_signs():
    c = build_config_artifact(SHARED, "a-vs-b", "uid1", 1, LINKS)
    assert set(c) == set(S.CONFIG_FIELDS)
    assert c["config_sha256"] == canonical_sha256(SHARED)
    assert c["config_name"] == "config_a-vs-b_g01.json"


def test_log_conforms_and_carries_consensus_signature():
    records = _records()
    log = build_log("a-vs-b", "uid1", LINKS, records, sub_game_number=1,
                    group_id="orcai-mj", role="police", opponent_group_id="them",
                    result="capture", winner_role="police", steps=12,
                    started_at="2026-07-26T10:00:00", duration_seconds=90,
                    tokens_total=0, audit={"passed": True, "failures": []})
    assert set(log) == set(S.LOG_FIELDS)
    assert set(log["summary"]) == set(S.LOG_SUMMARY_FIELDS)
    assert log["summary"]["ended_at"] == "2026-07-26T10:01:30"
    assert log["mutual_agreement"]["sha256"] == canonical_sha256(records)
    assert log["mutual_agreement"]["confirmed"] is True


def _sub_game(scores):
    return {"sub_game_number": 1, "scores": scores, "tokens_total": 10,
            "audit": {"log_verified": True}}


def test_result_conforms_and_aggregates():
    r = build_result("a-vs-b", "uid1", LINKS, ["us", "them"],
                     [_sub_game({"us": 20, "them": 5}), _sub_game({"us": 5, "them": 10})],
                     scoring=SHARED["scoring"])
    assert set(r) == set(S.RESULT_FIELDS)
    fr = r["final_result"]
    assert fr["scores"] == {"us": 25, "them": 15} and fr["winner"] == "us"
    assert fr["tokens_total_series"] == 20
    assert r["mutual_agreement"]["confirmed"] is True


def test_series_tie_rule_awards_tie_score():
    r = build_result("a-vs-b", "uid1", LINKS, ["us", "them"],
                     [_sub_game({"us": 10, "them": 10})], scoring=SHARED["scoring"])
    fr = r["final_result"]
    assert fr["winner"] == "tie" and fr["tie_score_awarded"] == SHARED["scoring"]["tie_score"]


def test_filenames_follow_table_20():
    names = artifact_filenames("a-vs-b", 3)
    assert names == {"declaration": "declaration_a-vs-b.json",
                     "config": "config_a-vs-b_g03.json",
                     "log": "log_a-vs-b_g03.json",
                     "result": "result_a-vs-b.json"}


def test_write_artifacts_writes_named_files(tmp_path):
    c = build_config_artifact(SHARED, "a-vs-b", "uid1", 1, LINKS)
    paths = write_artifacts(tmp_path, "a-vs-b", 1, config=c)
    assert (tmp_path / "config_a-vs-b_g01.json").exists()
    assert json.loads(paths["config"].read_text(encoding="utf-8"))["game_id"] == "a-vs-b"
