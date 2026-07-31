"""H3 gate: every documented CLI command runs and reports its true status."""
import pytest

from police_thief.cli import main


def test_selftest_runs_and_succeeds(capsys):
    assert main(["selftest", "--steps", "5"]) == 0
    out = capsys.readouterr().out
    assert "DEV TOOL" in out           # never mistakable for a league mode
    assert "step  5" in out or "CAPTURE" in out


def test_peer_without_fastmcp_exits_cleanly(capsys):
    # peer is WIRED as of 5.3; without the dependency installed it must fail
    # with a clear instruction, never a traceback.
    assert main(["peer", "--role", "police", "--turns", "1"]) == 2
    assert "uv sync" in capsys.readouterr().err


def test_replay_verdicts_from_real_log(tmp_path, capsys):
    # replay is WIRED as of 7.4: green verdict on an honest log, exit 1 on tamper.
    import json
    from police_thief.domain.crypto import commit
    from police_thief.report.report_writer import build_log

    h, nonce = commit("s1", "MOVE:N", "truth")
    records = [{"commit": h, "nonce": nonce, "state": "s1", "move": "MOVE:N",
                "intent": "truth", "hint": ""}]
    log = build_log("a-vs-b", "uid1", {}, records, sub_game_number=1, group_id="us",
                    role="police", opponent_group_id="them", result="capture",
                    winner_role="police", steps=1, started_at="2026-07-26T10:00:00",
                    duration_seconds=10, tokens_total=0,
                    audit={"passed": True, "failures": []})
    path = tmp_path / "log.json"
    path.write_text(json.dumps(log), encoding="utf-8")
    assert main(["replay", "--log", str(path)]) == 0
    assert "Verified OK" in capsys.readouterr().out

    log["records"][0]["move"] = "MOVE:S"
    path.write_text(json.dumps(log), encoding="utf-8")
    assert main(["replay", "--log", str(path)]) == 1
    assert "TAMPERED" in capsys.readouterr().out


def test_series_command_writes_artifacts(tmp_path, capsys):
    assert main(["series", "--games", "1", "--seed", "1", "--out", str(tmp_path)]) == 0
    assert "artifacts in" in capsys.readouterr().out
    assert (tmp_path / "result_orcai-mj-vs-orcai-mj-thief.json").exists()


def test_invalid_role_rejected():
    with pytest.raises(SystemExit) as e:
        main(["peer", "--role", "banker"])
    assert e.value.code == 2
