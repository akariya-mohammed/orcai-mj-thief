"""Counted-mode Gmail reporting — five proofs required by the match spec.

1. friendly sends zero emails (GmailSender never constructed)
2. counted success calls Gmail exactly once with result + all log attachments
3. failed audit sends nothing
4. Gmail failure → dispatch_report returns "failed" → cmd_interop exits 1
5. duplicate invocation cannot send the same report twice (sentinel guard)
"""
from __future__ import annotations

import json
import shutil
import types
from pathlib import Path

import pytest

from police_thief.interop.series import COUNTED, FRIENDLY, ReferenceSeriesPeer
from police_thief.shared.config import Config

SHARED = json.loads(open("config/game.json", encoding="utf-8").read())
_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_peer(tmp_path: Path, mode: str) -> ReferenceSeriesPeer:
    cfg = Config(SHARED, {"game": {"group_id": "test-team"},
                          "email": {"mode": "draft"}})
    peer = object.__new__(ReferenceSeriesPeer)
    peer.mode = mode
    peer.config = cfg
    peer.natural_role = "police"
    peer.identity = {"group_id": "test-team"}
    peer.their_identity = {}
    peer.game_id = "test-team-vs-opponent"
    peer.game_uid = "0000000000000000"
    peer.out_dir = tmp_path
    return peer


def _make_result(*, all_audits_verified: bool = True) -> dict:
    return {
        "series_winner": "police",
        "all_audits_verified": all_audits_verified,
        "num_sub_games": 6,
        "totals": {"police": 120, "thief": 30},
        "result_sha256": "deadbeef",
    }


class _FakeSender:
    """Records what would be sent without touching the Gmail API."""
    def __init__(self, config):
        self.config = config
        self.mode = config.get("email.mode", "draft")
        self.calls: list[dict] = []

    def send_series_report(self, artifact_paths: dict, summary: dict) -> dict:
        self.calls.append({"paths": dict(artifact_paths),
                           "summary": summary, "mode": self.mode})
        return {"status": "sent", "id": "fake-m1"}


class _FailingSender:
    def __init__(self, config):
        self.mode = "draft"

    def send_series_report(self, artifact_paths: dict, summary: dict) -> dict:
        return {"status": "failed", "error": "connection refused"}


# ── 1. Friendly sends zero emails ─────────────────────────────────────────────

def test_friendly_sends_zero_emails(tmp_path, monkeypatch):
    """GmailSender must never be constructed in friendly mode."""
    import police_thief.infra.email_sender as em
    monkeypatch.setattr(em, "GmailSender",
                        lambda *a, **kw: pytest.fail(
                            "GmailSender must not be constructed in friendly mode"))
    peer = _make_peer(tmp_path, FRIENDLY)
    report = peer.dispatch_report(_make_result())
    assert report["status"].startswith("suppressed")
    assert "friendly" in report["status"] or "email" in report["status"]


# ── 2. Counted success — one send, result + logs, mode forced to "send" ───────

def test_counted_success_sends_once_with_all_artifacts(tmp_path, monkeypatch):
    """Counted success: Gmail called exactly once; mode forced to send; logs included."""
    import police_thief.infra.email_sender as em

    instance: list[_FakeSender] = []

    def _factory(config):
        s = _FakeSender(config)
        instance.append(s)
        return s

    monkeypatch.setattr(em, "GmailSender", _factory)

    peer = _make_peer(tmp_path, COUNTED)
    (tmp_path / "result_test-team-vs-opponent.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "log_test-team-vs-opponent_g01.json").write_text('{"sub_game": 1}', encoding="utf-8")
    (tmp_path / "log_test-team-vs-opponent_g02.json").write_text('{"sub_game": 2}', encoding="utf-8")

    report = peer.dispatch_report(_make_result())

    assert report["status"] == "sent", report
    assert len(instance) == 1
    sender = instance[0]
    assert sender.mode == "send", "mode must be forced to 'send' in counted dispatch"
    assert len(sender.calls) == 1

    paths = sender.calls[0]["paths"]
    assert "result" in paths, "result artifact must be attached"
    assert any("g01" in str(k) for k in paths), "log g01 must be attached"
    assert any("g02" in str(k) for k in paths), "log g02 must be attached"

    assert (tmp_path / "report_sent_police.lock").exists(), "sentinel must be written"


# ── 3. Failed audit sends nothing ────────────────────────────────────────────

def test_failed_audit_sends_nothing(tmp_path, monkeypatch):
    """When all_audits_verified=False, Gmail is never called."""
    import police_thief.infra.email_sender as em
    monkeypatch.setattr(em, "GmailSender",
                        lambda *a, **kw: pytest.fail(
                            "GmailSender must not be called when audits fail"))
    peer = _make_peer(tmp_path, COUNTED)
    report = peer.dispatch_report(_make_result(all_audits_verified=False))
    assert report["status"].startswith("suppressed")
    assert "audit" in report["status"]


# ── 4. Gmail failure → status=failed → cmd_interop exits 1 ───────────────────

def test_gmail_failure_returns_failed_and_no_sentinel(tmp_path, monkeypatch):
    """Gmail failure: dispatch_report returns status=failed; no sentinel written."""
    import police_thief.infra.email_sender as em
    monkeypatch.setattr(em, "GmailSender", _FailingSender)

    peer = _make_peer(tmp_path, COUNTED)
    (tmp_path / "result_test-team-vs-opponent.json").write_text('{"ok": true}', encoding="utf-8")

    report = peer.dispatch_report(_make_result())

    assert report["status"] == "failed"
    assert "connection refused" in report.get("error", "")
    assert not (tmp_path / "report_sent_police.lock").exists()


def test_cmd_interop_exits_1_when_counted_report_fails(tmp_path, monkeypatch):
    """cmd_interop returns 1 when the counted report could not be sent."""
    from police_thief.cli_cmds import cmd_interop

    monkeypatch.setenv("P2P_CONFIRM_COUNTED", "YES")
    monkeypatch.chdir(tmp_path)

    # Minimal file tree for cmd_interop pre-flight checks
    cfg_dir = tmp_path / "config" / "police"
    cfg_dir.mkdir(parents=True)
    shutil.copy(_REPO_ROOT / "config" / "game.json",
                tmp_path / "config" / "game.json")
    (cfg_dir / "game.toml").write_text(
        '[game]\ngroup_id="test"\ngroup_name="Test"\n'
        '[network]\nmy_port=8801\nopponent_url="http://127.0.0.1:9999/mcp"\n',
        encoding="utf-8",
    )
    gate_dir = tmp_path / "artifacts"
    gate_dir.mkdir()
    (gate_dir / "friendly_gate.json").write_text('{"passed": true}', encoding="utf-8")
    (tmp_path / "credentials.json").write_text('{}', encoding="utf-8")
    (tmp_path / "token.json").write_text('{}', encoding="utf-8")

    out_dir = gate_dir / "interop"
    out_dir.mkdir()

    mock_result = {
        "all_audits_verified": True, "num_sub_games": 6,
        "totals": {"police": 120, "thief": 30},
        "series_winner": "police", "result_sha256": "abc",
        "report_status": {"status": "failed", "error": "auth failed"},
    }

    class _FakePeer:
        def __init__(self, **kw): pass
        def start_server(self): pass
        def run_series(self): return mock_result

    import police_thief.interop.series as series_mod
    monkeypatch.setattr(series_mod, "ReferenceSeriesPeer", _FakePeer)

    args = types.SimpleNamespace(
        role="police", config=str(cfg_dir / "game.toml"),
        opponent_url="http://127.0.0.1:9999/mcp",
        my_port=None, games=6, mode="counted", out=str(out_dir),
        seed=0, turn_timeout=180.0, no_alternate_roles=False,
        no_handshake_per_sub_game=False, mcp_url=None,
    )

    exit_code = cmd_interop(args)
    assert exit_code == 1


# ── 5. Duplicate invocation cannot send twice ─────────────────────────────────

def test_duplicate_invocation_sends_nothing_the_second_time(tmp_path, monkeypatch):
    """Pre-existing sentinel prevents a second Gmail call."""
    import police_thief.infra.email_sender as em

    call_count = [0]

    class _CountingSender:
        def __init__(self, config):
            self.mode = "draft"
        def send_series_report(self, artifact_paths, summary):
            call_count[0] += 1
            return {"status": "sent", "id": "m2"}

    monkeypatch.setattr(em, "GmailSender", _CountingSender)

    peer = _make_peer(tmp_path, COUNTED)
    (tmp_path / "result_test-team-vs-opponent.json").write_text('{"ok": true}', encoding="utf-8")
    # Simulate a prior successful send by writing the sentinel
    (tmp_path / "report_sent_police.lock").write_text(
        '{"status": "sent", "id": "m0"}', encoding="utf-8")

    report = peer.dispatch_report(_make_result())

    assert report["status"] == "duplicate_suppressed"
    assert call_count[0] == 0, "Gmail must not be called when sentinel exists"
