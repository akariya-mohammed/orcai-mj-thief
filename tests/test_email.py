"""Task 7.2: Gmail sender — fully mocked (no live network ever), draft-mode default,
least-privilege scope, secrets hygiene, never-crash reporting."""
import base64
import json
from email import message_from_bytes
from pathlib import Path

from police_thief.infra.email_sender import SCOPES, GmailSender
from police_thief.shared.config import Config

SHARED = json.loads(open("config/game.json", encoding="utf-8").read())


class _FakeService:
    def __init__(self):
        self.sent = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self._pending = body
        return self

    def execute(self):
        self.sent.append(self._pending)
        return {"id": "m1"}


def _artifacts(tmp_path):
    paths = {}
    for kind in ("declaration", "config", "log", "result"):
        p = tmp_path / f"{kind}_x.json"
        p.write_text(json.dumps({"kind": kind}), encoding="utf-8")
        paths[kind] = p
    return paths


def test_scope_is_send_only():
    assert SCOPES == ["https://www.googleapis.com/auth/gmail.send"]   # Rule 30


def test_send_mode_attaches_all_four_artifacts(tmp_path):
    fake = _FakeService()
    cfg = Config(SHARED, {"email": {"mode": "send", "recipient": "grader@example.com"}})
    sender = GmailSender(cfg, service_factory=lambda: fake, outbox_dir=tmp_path)
    out = sender.send_series_report(_artifacts(tmp_path),
                                    {"game_id": "a-vs-b", "winner": "us"})
    raw = base64.urlsafe_b64decode(fake.sent[0]["raw"])
    msg = message_from_bytes(raw)
    assert msg["To"] == "grader@example.com"
    assert "a-vs-b" in msg["Subject"]
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert sorted(names) == ["config_x.json", "declaration_x.json",
                             "log_x.json", "result_x.json"]
    assert out["status"] == "sent"


def test_draft_mode_writes_eml_and_never_touches_the_service(tmp_path):
    def bomb():
        raise AssertionError("service must not be constructed in draft mode")

    cfg = Config(SHARED, {"email": {"mode": "draft"}})
    sender = GmailSender(cfg, service_factory=bomb, outbox_dir=tmp_path)
    out = sender.send_series_report(_artifacts(tmp_path), {"game_id": "a-vs-b"})
    assert out["status"] == "draft"
    eml = Path(out["path"])
    assert eml.exists() and eml.suffix == ".eml"
    assert b"declaration_x.json" in eml.read_bytes()


def test_default_recipient_is_the_mandated_league_address():
    cfg = Config(SHARED, {})                       # nothing configured
    sender = GmailSender(cfg, service_factory=lambda: _FakeService())
    assert sender.recipient == "rmisegal+uoh26finalgame@gmail.com"   # Rule 51
    assert sender.mode == "draft"                                    # safe default


def test_reporting_never_crashes_the_peer(tmp_path):
    class _Broken:
        def users(self):
            raise ConnectionError("network down")

    from police_thief.shared.gatekeeper import ApiGatekeeper
    cfg = Config(SHARED, {"email": {"mode": "send"}})
    sender = GmailSender(cfg, service_factory=lambda: _Broken(), outbox_dir=tmp_path,
                         gatekeeper=ApiGatekeeper(30, sleeper=lambda s: None))
    out = sender.send_series_report(_artifacts(tmp_path), {"game_id": "a-vs-b"})
    assert out["status"] == "failed" and "network down" in out["error"]


def test_secrets_are_gitignored():
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    assert "credentials.json" in ignored and "token.json" in ignored   # Rules 39-40
