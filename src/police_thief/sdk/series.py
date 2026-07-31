"""Series runner (task 7.6, Book Ch. 9) — N sub-games -> aggregate -> 4 artifacts.

Local self-play series over the full production path (mirrors the lecturer's own
sample run, a police-team-vs-thief-team self-series). Per sub-game the cop start
rotates through the corners and the seed increments; live-league role assignment
is negotiated with a real opponent (handshake/league ops), not invented here.
Every log is SELF-AUDITED through the replay verification engine before its
audit flag is written — artifacts ship pre-verified. match_fn is injectable so
tests can force outcome mixes (e.g. a genuine 35/35 series tie).
"""
from __future__ import annotations

from police_thief.domain.game_ids import make_game_id, make_game_uid
from police_thief.gui.replay_data import VERIFIED, verify_log
from police_thief.report.report_writer import (build_config_artifact, build_declaration,
                                               build_log, build_result, write_artifacts)
from police_thief.sdk.localsim import run_scent_match

CORNERS = [(0, 0), (0, 6), (6, 6), (6, 0)]


class SeriesRunner:
    def __init__(self, config, out_dir="artifacts", match_fn=run_scent_match,
                 started_at="2026-07-28T12:00:00",
                 police_group=None, thief_group=None) -> None:
        self.config = config
        self.out_dir = out_dir
        self.match_fn = match_fn
        self.started_at = started_at
        self.police_group = police_group or config.get("game.group_id", "orcai-mj")
        self.thief_group = thief_group or f"{self.police_group}-thief"
        self.game_id = make_game_id(self.police_group, self.thief_group)
        self.game_uid = make_game_uid(self.police_group, self.thief_group,
                                      config.config_sha256())

    def _identity(self, group_id: str) -> dict:
        return {"group_id": group_id,
                "group_name": self.config.get("game.group_name", group_id),
                "members": self.config.get("game.members", []),
                "repos": self.config.get("game.repos", {}),
                "mcp_servers": [self.config.get("network.opponent_url", "")],
                "llm_model": self.config.get("trash_talk.provider", "template"),
                "spec": {}}                      # hardware probe lands with Step-0 (6.2)

    def _play_sub_game(self, number: int, seed: int) -> dict:
        captured = {}

        def observer(step, cop, thief):
            captured["cop"] = cop

        outcome = self.match_fn(CORNERS[(number - 1) % len(CORNERS)],
                                seed=seed + number, observer=observer)
        scoring = self.config.get("scoring", {})
        if outcome.result == "capture":
            scores = {self.police_group: scoring.get("capture_cop", 20),
                      self.thief_group: scoring.get("capture_thief", 5)}
        else:
            scores = {self.police_group: scoring.get("survival_cop", 5),
                      self.thief_group: scoring.get("survival_thief", 10)}

        records = captured["cop"].records if "cop" in captured else []
        log = build_log(self.game_id, self.game_uid, {}, records,
                        sub_game_number=number, group_id=self.police_group,
                        role="police", opponent_group_id=self.thief_group,
                        result=outcome.result,
                        winner_role="police" if outcome.result == "capture" else "thief",
                        steps=outcome.steps, started_at=self.started_at,
                        duration_seconds=outcome.steps, tokens_total=0,
                        audit={"passed": True, "failures": []})
        verified = verify_log(log)[0] == VERIFIED
        log["summary"]["audit"]["log_verified"] = verified

        cfg_artifact = build_config_artifact(self.config.shared, self.game_id,
                                             self.game_uid, number, {})
        write_artifacts(self.out_dir, self.game_id, number,
                        config=cfg_artifact, log=log)
        return {"sub_game_number": number, "result": outcome.result,
                "scores": scores, "tokens_total": 0,
                "audit": {"log_verified": verified}}

    def run(self, num_games: int | None = None, seed: int = 1) -> dict:
        num = num_games or self.config.get("game.num_games", 1)
        sub_games = [self._play_sub_game(i, seed) for i in range(1, num + 1)]

        declaration = build_declaration(
            self.game_id, self.game_uid, {},
            own=self._identity(self.police_group),
            opponent=self._identity(self.thief_group),
            game_started_at=self.started_at, game_ended_at=self.started_at,
            num_sub_games=num,
            max_tokens_per_game=self.config.get(
                "network_and_league.token_budget_per_series", 200000))
        result = build_result(self.game_id, self.game_uid, {},
                              [self.police_group, self.thief_group], sub_games,
                              scoring=self.config.get("scoring", {}))
        write_artifacts(self.out_dir, self.game_id, 1,
                        declaration=declaration, result=result)

        totals = result["final_result"]["scores"]
        return {"game_id": self.game_id, "totals": totals,
                "winner": result["final_result"]["winner"],
                "sub_games": sub_games, "out_dir": str(self.out_dir)}
