"""Submission-image generator (task 7.5) — deterministic SVGs from a real match.

Runs a seeded scent-only match on the full production path (localsim), samples
the POLICE view-model along the way, and writes the three mandatory artifacts:
  live_gui_frame.svg        annotated live-GUI frame (belief heatmap + banner)
  heatmap_progression.svg   three-panel belief evolution
  replay_verified.svg       the Verified-OK badge from a REAL verification pass
Reproducible by anyone: uv run python scripts/render_docs_images.py
"""
from __future__ import annotations

from pathlib import Path

from police_thief.gui.render_svg import render_badge, render_board_svg, render_progression
from police_thief.gui.viewmodel import build_view
from police_thief.gui.replay_data import verify_log
from police_thief.report.report_writer import build_log
from police_thief.sdk.localsim import run_scent_match


def generate(out_dir="docs/img", seed: int = 1, cop_start=(0, 0)) -> list[Path]:
    views, cop_ref = [], {}

    def observer(step, cop, thief):
        views.append(build_view(cop, step))
        cop_ref["rt"] = cop

    outcome = run_scent_match(cop_start, seed=seed, observer=observer)
    cop = cop_ref["rt"]

    log = build_log("orcai-mj-vs-orcai-mj-thief", "docs-sample", {}, cop.records,
                    sub_game_number=1, group_id="orcai-mj", role="police",
                    opponent_group_id="orcai-mj-thief", result=outcome.result,
                    winner_role="police" if outcome.result == "capture" else "thief",
                    steps=outcome.steps, started_at="2026-07-26T12:00:00",
                    duration_seconds=outcome.steps, tokens_total=0,
                    audit={"passed": True, "failures": []})
    verdict, detail = verify_log(log)

    picks = [views[0], views[len(views) // 2], views[-1]] if len(views) >= 3 else views
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "live_gui_frame.svg": render_board_svg(views[-1], title="POLICE — live view"),
        "heatmap_progression.svg": render_progression(picks),
        "replay_verified.svg": render_badge(verdict, detail),
    }
    written = []
    for name, svg in files.items():
        path = out / name
        path.write_text(svg, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in generate():
        print(f"wrote {path}")
