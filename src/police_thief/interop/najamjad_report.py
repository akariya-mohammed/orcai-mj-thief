"""NajAmjad POST-MATCH aggregator — reporting only, never gameplay.

Project §2.4.2 requires the cop and thief agents to run completely separated:
no shared files, memory, IPC or state between our two role processes. Each
gameplay process therefore writes ONLY its own role-owned artifacts (rows,
logs, configs, declaration, a partial role result) into its OWN directory,
and this module — run as a SEPARATE step by the launcher, strictly AFTER the
whole six-window series has finished — is the single place where the two
independent artifact sets are merged into the one six-row team report.

Hard properties, all pinned by tests:

* runs after gameplay only; it refuses to aggregate an incomplete series;
* reads the two role directories READ-ONLY and never rewrites a source
  artifact — the merged report is written to its own separate output dir;
* missing or contradictory role artifacts SUPPRESS reporting (and email)
  rather than inventing values;
* exactly one team ``result_<game_id>.json`` and exactly one email dispatch
  path exist, with a sentinel duplicate guard;
* counted -> the lecturer only, friendly -> the team only, never crossed;
* it feeds nothing back into either gameplay agent.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from police_thief.interop import najamjad
from police_thief.interop.refcrypto import digest

CAPTURE, SURVIVAL = "capture", "survival"
_ROW_RE = re.compile(r"^row_(?P<game_id>.+)_g(?P<n>\d{2})\.json$")


class AggregationError(ValueError):
    """A condition under which no team report may be produced."""


def _load_rows(role_dir: Path) -> dict[int, tuple[dict, str]]:
    """Read ``row_<game_id>_gNN.json`` files from ONE role directory.

    Returns {window: (row, game_id)}. Read-only: this function never writes.
    """
    rows: dict[int, tuple[dict, str]] = {}
    for path in sorted(role_dir.glob("row_*.json")):
        match = _ROW_RE.match(path.name)
        if not match:
            continue
        n = int(match.group("n"))
        row = json.loads(path.read_text(encoding="utf-8"))
        if n in rows:
            raise AggregationError(
                f"duplicate row for window {n} inside {role_dir}")
        rows[n] = (row, match.group("game_id"))
    return rows


def _load_partial(role_dir: Path, role: str) -> dict | None:
    hits = sorted(role_dir.glob(f"result_*_{role}.json"))
    if not hits:
        return None
    return json.loads(hits[-1].read_text(encoding="utf-8"))


def collect_series(cop_dir: str | Path, thief_dir: str | Path,
                   num_games: int = 6) -> dict[str, Any]:
    """Validate and merge the two finalized role artifact sets.

    Raises AggregationError when the series is incomplete or the two sets
    contradict each other — the caller must then suppress reporting instead
    of inventing values.
    """
    cop_dir, thief_dir = Path(cop_dir), Path(thief_dir)
    cop_rows = _load_rows(cop_dir)
    thief_rows = _load_rows(thief_dir)

    overlap = sorted(set(cop_rows) & set(thief_rows))
    if overlap:
        raise AggregationError(
            f"windows {overlap} claimed by BOTH role processes — "
            f"contradictory artifacts, refusing to report")
    merged = {**{n: r for n, (r, _) in cop_rows.items()},
              **{n: r for n, (r, _) in thief_rows.items()}}
    missing = [n for n in range(1, num_games + 1) if n not in merged]
    if missing:
        raise AggregationError(
            f"series incomplete: windows {missing} have no finalized row — "
            f"aggregation runs only AFTER all {num_games} windows")

    game_ids = {gid for _, gid in cop_rows.values()} | \
               {gid for _, gid in thief_rows.values()}
    if len(game_ids) != 1:
        raise AggregationError(
            f"role artifacts disagree on game_id: {sorted(game_ids)}")
    game_id = game_ids.pop()

    cop_partial = _load_partial(cop_dir, "police")
    thief_partial = _load_partial(thief_dir, "thief")
    if cop_partial is None or thief_partial is None:
        raise AggregationError(
            "a role process has not finalized its partial result yet — "
            "aggregation runs only after gameplay is fully finished")
    for partial in (cop_partial, thief_partial):
        if partial.get("game_id") != game_id:
            raise AggregationError(
                f"partial result game_id {partial.get('game_id')!r} "
                f"contradicts the rows' {game_id!r}")
    if cop_partial.get("game_uid") != thief_partial.get("game_uid"):
        raise AggregationError(
            "the two role processes derived different game_uids")

    return {
        "game_id": game_id,
        "game_uid": cop_partial.get("game_uid", ""),
        "rows": [merged[n] for n in sorted(merged)],
        "cop_partial": cop_partial,
        "thief_partial": thief_partial,
    }


def build_team_result(series: dict[str, Any], mode: str,
                      num_games: int = 6, tie_award: int = 2) -> dict[str, Any]:
    """The one six-row team report with the §7.2 signature and tie rule."""
    rows = series["rows"]
    cop_partial = series["cop_partial"]
    game_id, game_uid = series["game_id"], series["game_uid"]
    groups = list(cop_partial.get("groups", []))
    our_group = najamjad.OUR_GROUP_ID
    their_group = next((g for g in groups if g != our_group),
                       najamjad.THEIR_GROUP_ID)

    grouped = najamjad.group_rows(rows, our_group, their_group)
    mutual_doc = najamjad.build_mutual_doc(game_id, grouped, our_group,
                                           their_group, tie_award=tie_award)
    aggregate = mutual_doc["aggregate"]
    # Display-only raw sub-game sums (75-75 on a clean tie). The SIGNED
    # total_score already folds the +2 series-tie award in (77-77, per
    # NajAmjad's filed golden example) — raw figures never enter the preimage.
    raw_total: dict[str, int] = {our_group: 0, their_group: 0}
    for cr in grouped:
        for group, score in cr["score"].items():
            raw_total[group] = raw_total.get(group, 0) + score
    sub_games_report = [
        najamjad.row_report(row, cr, our_group, their_group, game_id)
        for row, cr in zip(rows, grouped)]
    clean = len(rows) == num_games and all(
        r["ending"] in (CAPTURE, SURVIVAL)
        and str(r.get("audit_of_opponent", "")).startswith("Verified OK")
        and r.get("audit_delivered", True)
        and not r.get("protocol_violations")
        for r in rows)

    body = {
        "report_type": "final_game_result",
        "schema_version": cop_partial.get("schema_version", "1.2"),
        "game_id": game_id,
        "game_uid": game_uid,
        "groups": sorted([our_group, their_group]),
        "timezone": "UTC",
        "game_started_at": cop_partial.get("game_started_at", ""),
        "game_ended_at": datetime.now(UTC).isoformat(),
        "sub_games": sub_games_report,
        "links": cop_partial.get("links", {}),
        "group_details": cop_partial.get("group_details", {}),
        # The signed consensus: sha over EXACTLY {game_id, aggregate,
        # sub_games} in the SPACED serialisation (their §7.2). Compared with
        # NajAmjad before either team files — no wire exchange here.
        "mutual_agreement": {
            "sha256": najamjad.mutual_digest(mutual_doc),
            "signed_over": ["game_id", "aggregate", "sub_games"],
            "serialization": "json.dumps(sort_keys=True, ensure_ascii=False)"
                             " — default spaced separators",
            "confirmed": False,
        },
        "final_result": dict(aggregate) | {
            "raw_total_score": raw_total,      # display only — NOT signed
            "tie_award": (tie_award if aggregate["series_tie"] else 0),
            "tokens_total_series": 0,
        },
        "dialect": "najamjad",
        "spec_profile": "najamjad",
        "match_mode": ("FRIENDLY (UNCOUNTED)" if mode == "friendly"
                       else "COUNTED"),
        "num_sub_games": len(rows),
        "config_sha256": cop_partial.get("config_sha256", ""),
        "terms_sha256": cop_partial.get("terms_sha256", ""),
        "totals": {"police": sum(r["police_score"] for r in rows),
                   "thief": sum(r["thief_score"] for r in rows)},
        "series_winner": aggregate["winner_group"] or "tie",
        "all_audits_verified": clean,
        "aggregated_from": {
            "cop_windows": cop_partial.get("windows_played", []),
            "thief_windows": series["thief_partial"].get("windows_played", []),
        },
    }
    body["result_sha256"] = digest(body)
    return body


def dispatch_report(body: dict[str, Any], out_dir: Path, mode: str,
                    cop_dir: Path, thief_dir: Path,
                    sender_factory=None,
                    digest_confirmed: bool = False) -> dict[str, Any]:
    """The ONE email dispatch path for the NajAmjad profile (their §7.4).

    counted -> the lecturer, from our team separately; friendly -> the team
    only, NEVER the lecturer. One email per completed series (sentinel).
    Attachments are read from the two role directories READ-ONLY.

    For counted mode the caller MUST pass digest_confirmed=True after both
    operators have compared the mutual SHA256 digit-for-digit with NajAmjad.
    This prevents the lecturer email from going out before the comparison step.
    """
    from police_thief.infra.email_sender import LEAGUE_ADDRESS
    game_id = body.get("game_id", "najamjad-series")
    recipient = (najamjad.FRIENDLY_RECIPIENT if mode == "friendly"
                 else LEAGUE_ADDRESS)
    if os.environ.get("P2P_EMAIL_DISABLE") == "1":
        return {"status": "suppressed (P2P_EMAIL_DISABLE=1)",
                "recipient": recipient}
    if mode == "counted" and not body.get("all_audits_verified"):
        return {"status": "suppressed (audit failures — all audits must pass "
                          "before the lecturer is mailed)",
                "recipient": recipient}
    if mode == "counted" and not digest_confirmed:
        return {"status": "suppressed (counted dispatch requires explicit digest "
                          "confirmation — call with digest_confirmed=True after "
                          "both operators have verified the mutual SHA256)",
                "recipient": recipient}
    sentinel = out_dir / f"najamjad_report_sent_{game_id}.lock"
    if sentinel.exists():
        return {"status": "duplicate_suppressed", "sentinel": str(sentinel),
                "recipient": recipient}
    result_path = out_dir / f"result_{game_id}.json"
    artifact_paths: dict[str, Path] = {}
    if result_path.exists():
        artifact_paths["result"] = result_path
    if sender_factory is None:
        from police_thief.infra.email_sender import GmailSender
        from police_thief.shared.config import Config
        config = Config.load(shared_path="config/game.najamjad.json",
                             private_path="config/najamjad/police.toml")
        sender = GmailSender(config)
    else:
        sender = sender_factory()
    sender.recipient = recipient           # explicit; never the config default
    sender.mode = "send"
    summary = {"game_id": game_id, "winner": body.get("series_winner")}
    report = sender.send_series_report(artifact_paths, summary)
    report["recipient"] = recipient
    if report.get("status") == "sent":
        sentinel.write_text(json.dumps(report, ensure_ascii=False),
                            encoding="utf-8")
    return report


def send_corrective_friendly(result_path: str | Path, out_dir: str | Path,
                              sender_factory=None) -> dict[str, Any]:
    """Send a corrective friendly report attaching ONLY the result file.

    Has its own sentinel so the original najamjad_report_sent_*.lock is
    preserved. Does NOT alter the normal dispatch_report duplicate guard.
    """
    result_path = Path(result_path)
    out_dir = Path(out_dir)
    game_id = result_path.stem[len("result_"):]
    sentinel = out_dir / f"najamjad_corrective_sent_{game_id}.lock"
    if sentinel.exists():
        return {"status": "duplicate_suppressed", "sentinel": str(sentinel)}
    if os.environ.get("P2P_EMAIL_DISABLE") == "1":
        return {"status": "suppressed (P2P_EMAIL_DISABLE=1)"}
    artifact_paths: dict[str, Path] = {}
    if result_path.exists():
        artifact_paths["result"] = result_path
    recipient = najamjad.FRIENDLY_RECIPIENT
    if sender_factory is None:
        from police_thief.infra.email_sender import GmailSender
        from police_thief.shared.config import Config
        config = Config.load(shared_path="config/game.najamjad.json",
                             private_path="config/najamjad/police.toml")
        sender = GmailSender(config)
    else:
        sender = sender_factory()
    sender.recipient = recipient
    sender.mode = "send"
    summary = {
        "game_id": f"[CORRECTED] {game_id}",
        "winner": "najamjad",
        "note": ("Prior email included unnecessary separate internal artifacts. "
                 "This is the canonical single-file friendly report."),
    }
    report = sender.send_series_report(artifact_paths, summary)
    report["recipient"] = recipient
    if report.get("status") == "sent":
        sentinel.write_text(json.dumps(report, ensure_ascii=False),
                            encoding="utf-8")
    return report


def aggregate(cop_dir: str | Path, thief_dir: str | Path,
              out_dir: str | Path, mode: str, num_games: int = 6,
              tie_award: int = 2, sender_factory=None,
              digest_confirmed: bool = False,
              log=print) -> dict[str, Any]:
    """Full post-match step: validate, merge, write ONE team result, dispatch.

    On incomplete/contradictory inputs: no result is written, no email is
    sent, and the returned status names the reason.
    """
    cop_dir, thief_dir = Path(cop_dir), Path(thief_dir)
    out_dir = Path(out_dir)
    try:
        series = collect_series(cop_dir, thief_dir, num_games)
    except AggregationError as exc:
        log(f"[najamjad-report] SUPPRESSED: {exc}")
        return {"status": "suppressed", "reason": str(exc),
                "result_written": False,
                "report_status": {"status": f"suppressed ({exc})"}}
    body = build_team_result(series, mode, num_games, tie_award)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / f"result_{body['game_id']}.json"
    result_path.write_text(json.dumps(body, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    report = dispatch_report(body, out_dir, mode, cop_dir, thief_dir,
                             sender_factory=sender_factory,
                             digest_confirmed=digest_confirmed)
    body["report_status"] = report
    log(f"[najamjad-report] team result -> {result_path.name} "
        f"winner={body['series_winner']} "
        f"mutual={body['mutual_agreement']['sha256'][:12]}... "
        f"report={report['status']}")
    return {"status": "ok", "reason": "", "result_written": True,
            "result_path": str(result_path), "body": body,
            "report_status": report}
