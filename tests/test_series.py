"""Task 7.6: the series runner — N sub-games -> aggregation -> 4 artifacts on disk."""
import json

from police_thief.sdk.localsim import MatchOutcome
from police_thief.sdk.series import SeriesRunner
from police_thief.shared.config import Config

SHARED = json.loads(open("config/game.json", encoding="utf-8").read())


def _runner(tmp_path, match_fn=None):
    cfg = Config(SHARED, {"game": {"group_id": "orcai-mj"}})
    kwargs = {"out_dir": tmp_path, "started_at": "2026-07-28T12:00:00"}
    if match_fn:
        kwargs["match_fn"] = match_fn
    return SeriesRunner(cfg, **kwargs)


def test_real_series_writes_all_artifacts(tmp_path):
    summary = _runner(tmp_path).run(num_games=2, seed=1)
    game_id = "orcai-mj-vs-orcai-mj-thief"
    for name in [f"declaration_{game_id}.json", f"result_{game_id}.json",
                 f"config_{game_id}_g01.json", f"config_{game_id}_g02.json",
                 f"log_{game_id}_g01.json", f"log_{game_id}_g02.json"]:
        assert (tmp_path / name).exists(), name
    result = json.loads((tmp_path / f"result_{game_id}.json").read_text(encoding="utf-8"))
    assert result["num_sub_games"] == 2
    # scores must equal the per-sub-game sum
    totals = {}
    for sg in result["sub_games"]:
        for g, pts in sg["scores"].items():
            totals[g] = totals.get(g, 0) + pts
    assert result["final_result"]["scores"] == totals
    assert summary["winner"] == result["final_result"]["winner"]


def test_every_written_log_is_self_audited(tmp_path):
    _runner(tmp_path).run(num_games=1, seed=1)
    log = json.loads((tmp_path / "log_orcai-mj-vs-orcai-mj-thief_g01.json")
                     .read_text(encoding="utf-8"))
    assert log["summary"]["audit"]["log_verified"] is True
    # and it must replay-verify from disk, independently
    from police_thief.gui.replay_data import verify_log, VERIFIED
    assert verify_log(log)[0] == VERIFIED


def _fake_outcomes(results):
    seq = iter(results)

    def fake_match(cop_start, thief_start=(3, 3), seed=0, observer=None, **kw):
        return MatchOutcome(next(seq), 20, 0.5, 0, 0)
    return fake_match


def test_series_tie_applies_tie_score(tmp_path):
    # 1 capture (20/5) + 3 survivals (5/10 each) = 35/35 — a genuine series tie.
    runner = _runner(tmp_path, match_fn=_fake_outcomes(
        ["capture", "survival", "survival", "survival"]))
    summary = runner.run(num_games=4, seed=1)
    assert summary["totals"] == {"orcai-mj": 35, "orcai-mj-thief": 35}
    assert summary["winner"] == "tie"
    result = json.loads((tmp_path / "result_orcai-mj-vs-orcai-mj-thief.json")
                        .read_text(encoding="utf-8"))
    assert result["final_result"]["tie_score_awarded"] == SHARED["scoring"]["tie_score"]


def test_cop_start_rotates_between_sub_games(tmp_path):
    starts = []

    def spy_match(cop_start, thief_start=(3, 3), seed=0, observer=None, **kw):
        starts.append(cop_start)
        return MatchOutcome("capture", 10, 0.5, 0, 0)

    _runner(tmp_path, match_fn=spy_match).run(num_games=4, seed=1)
    assert len(set(starts)) == 4                      # four distinct corners
