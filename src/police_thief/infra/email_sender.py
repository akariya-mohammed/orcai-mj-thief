"""Gmail sender (task 7.2; Book appendix א; Rules 28-30, 51).

Least privilege: the gmail.send scope ONLY — this agent can dispatch reports, it
can never read or delete mail. Draft mode is the DEFAULT: the fully-composed
message is written to outbox/*.eml instead of sent, so development can never
accidentally email the lecturer; mode="send" is the explicit league setting.
All live dispatches route through the ApiGatekeeper (pacing + DOS lock), and a
failed send returns a failure dict — reporting must NEVER crash the peer.
Google libraries are imported lazily; the OAuth first run (credentials.json ->
token.json via the Desktop-App flow) is interactive and user-driven.
"""
from __future__ import annotations

import base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from police_thief.shared.gatekeeper import ApiGatekeeper

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]     # Rule 30: send-only
LEAGUE_ADDRESS = "rmisegal+uoh26finalgame@gmail.com"        # Rule 51


def default_service(credentials_path="credentials.json", token_path="token.json"):
    """Build the Gmail service (interactive OAuth on first run — user-driven)."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token = Path(token_path)
    if token.exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        creds = flow.run_local_server(port=0)
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


class GmailSender:
    def __init__(self, config, service_factory=default_service,
                 gatekeeper: ApiGatekeeper | None = None, outbox_dir="outbox") -> None:
        self.recipient = config.get("email.recipient", LEAGUE_ADDRESS)
        self.mode = config.get("email.mode", "draft")        # safe default
        self.outbox_dir = outbox_dir
        self._service_factory = service_factory
        self.gatekeeper = gatekeeper or ApiGatekeeper(
            config.get("rate_limiter_gatekeeper.requests_per_minute", 30),
            config.get("rate_limiter_gatekeeper.queue_depth", 100))

    def _compose(self, artifact_paths: dict, summary: dict) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["To"] = self.recipient
        msg["Subject"] = (f"[police-thief] series report {summary.get('game_id', '?')} "
                          f"— winner: {summary.get('winner', 'n/a')}")
        msg.attach(MIMEText(
            f"Automated end-of-series report.\nSummary: {summary}\n"
            f"Attached: {', '.join(sorted(artifact_paths))} (JSON, Rule 33-34).", "plain"))
        for kind in sorted(artifact_paths):
            path = Path(artifact_paths[kind])
            part = MIMEApplication(path.read_bytes(), _subtype="json")
            part.add_header("Content-Disposition", "attachment", filename=path.name)
            msg.attach(part)
        return msg

    def send_series_report(self, artifact_paths: dict, summary: dict) -> dict:
        msg = self._compose(artifact_paths, summary)
        if self.mode == "draft":
            out = Path(self.outbox_dir)
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"report_{summary.get('game_id', 'game')}.eml"
            path.write_bytes(msg.as_bytes())
            return {"status": "draft", "path": str(path)}
        try:
            service = self._service_factory()
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            result = self.gatekeeper.execute(
                lambda: service.users().messages().send(
                    userId="me", body={"raw": raw}).execute(),
                label="gmail_send")
            return {"status": "sent", "id": result.get("id", "")}
        except Exception as exc:                     # reporting never crashes the peer
            return {"status": "failed", "error": str(exc)}
