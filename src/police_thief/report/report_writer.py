"""Builders for the 4 mandatory artifacts (task 7.1, Book Ch. 9 + Table 20).

Every builder emits EXACTLY the field set pinned in artifact_schemas (the
conformance tests iterate those lists). Schemas are ours until audit interop
with reference-derived teams matters (Stage 6 / Intel I1).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from police_thief.domain.game_ids import artifact_filenames
from police_thief.report.artifact_schemas import SCHEMA_VERSION
from police_thief.shared.config import canonical_sha256

DEFAULT_TIMEZONE = "Asia/Jerusalem"

_S = "police-thief/{}@" + SCHEMA_VERSION   # _schema tags


def build_group_block(identity: dict) -> dict:
    return {"group_id": identity["group_id"], "group_name": identity["group_name"],
            "members": identity["members"], "repos": identity["repos"],
            "mcp_servers": identity["mcp_servers"], "llm_model": identity["llm_model"],
            "hardware_spec": identity["spec"]}


def build_declaration(game_id, game_uid, links, own, opponent, game_started_at,
                      game_ended_at, num_sub_games, max_tokens_per_game,
                      timezone=DEFAULT_TIMEZONE) -> dict:
    return {"_schema": _S.format("declaration"), "schema_version": SCHEMA_VERSION,
            "declaration_type": "pre_game_declaration",
            "game_id": game_id, "game_uid": game_uid, "links": links,
            "timezone": timezone, "game_started_at": game_started_at,
            "game_ended_at": game_ended_at, "num_sub_games": num_sub_games,
            "max_tokens_per_game": max_tokens_per_game,
            "groups": {"group_1": build_group_block(own),
                       "group_2": build_group_block(opponent)}}


def build_config_artifact(shared_terms: dict, game_id, game_uid, sub_game_number,
                          links) -> dict:
    return {"_schema": _S.format("config"), **shared_terms,
            "schema_version": SCHEMA_VERSION, "game_id": game_id,
            "game_uid": game_uid, "sub_game_number": sub_game_number, "links": links,
            "config_name": artifact_filenames(game_id, sub_game_number)["config"],
            "config_sha256": canonical_sha256(shared_terms)}


def _ended_at(started_at: str, duration_seconds: float) -> str:
    return (datetime.fromisoformat(started_at)
            + timedelta(seconds=duration_seconds)).isoformat()


def build_log(game_id, game_uid, links, records, *, sub_game_number, group_id, role,
              opponent_group_id, result, winner_role, steps, started_at,
              duration_seconds, tokens_total, audit,
              timezone=DEFAULT_TIMEZONE) -> dict:
    summary = {"sub_game_number": sub_game_number, "group_id": group_id, "role": role,
               "opponent_group_id": opponent_group_id, "result": result,
               "winner_role": winner_role, "steps": steps, "timezone": timezone,
               "started_at": started_at,
               "ended_at": _ended_at(started_at, duration_seconds),
               "duration_seconds": duration_seconds, "tokens_total": tokens_total,
               "audit": audit}
    return {"_schema": _S.format("log"), "schema_version": SCHEMA_VERSION,
            "game_id": game_id, "game_uid": game_uid, "links": links,
            "summary": summary, "records": records,
            "mutual_agreement": {"opponent_group_id": opponent_group_id,
                                 "sha256": canonical_sha256(records),
                                 "confirmed": bool(audit.get("passed"))}}


def build_result(game_id, game_uid, links, groups, sub_games, scoring,
                 timezone=DEFAULT_TIMEZONE) -> dict:
    totals = {g: sum(sg["scores"].get(g, 0) for sg in sub_games) for g in groups}
    ranked = sorted(totals, key=totals.get, reverse=True)
    tie = len(groups) == 2 and totals[groups[0]] == totals[groups[1]]
    final = {"scores": totals, "winner": "tie" if tie else ranked[0],
             "tokens_total_series": sum(sg.get("tokens_total", 0) for sg in sub_games)}
    if tie:
        final["tie_score_awarded"] = scoring["tie_score"]     # book series tie rule
    return {"_schema": _S.format("result"), "schema_version": SCHEMA_VERSION,
            "report_type": "final_game_result", "game_id": game_id,
            "game_uid": game_uid, "links": links, "timezone": timezone,
            "groups": list(groups), "num_sub_games": len(sub_games),
            "sub_games": sub_games, "final_result": final,
            "mutual_agreement": {
                "sha256": canonical_sha256(sub_games),
                "confirmed": all(sg.get("audit", {}).get("log_verified", False)
                                 for sg in sub_games)}}


def write_artifacts(out_dir, game_id, sub_game_number, **artifacts) -> dict[str, Path]:
    """Write any of declaration/config/log/result under their Table-20 names."""
    names = artifact_filenames(game_id, sub_game_number)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind, artifact in artifacts.items():
        path = out / names[kind]
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        paths[kind] = path
    return paths
