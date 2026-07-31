# PRD 7 — Reporting & Visualization Shell (retro, mostly delivered)

**Goal:** the outward face — artifacts, verification verdicts, GUI, submission images.

## Delivered
- `report/report_writer.py` — the 4 mandatory artifacts (declaration/config/log/result),
  conformance-tested against the pinned schemas; Table-20 filenames; series tie rule.
- `gui/replay_data.py` + CLI `replay` — dual-layer tamper detection, binary verdict.
- `gui/viewmodel.py` + `gui/window.py` — local-truth-only belief heatmap + phase banner
  (structural Rule-8/9 test); thin Tk poller, game loop in a worker thread.
- `gui/render_svg.py` + `gui/docs_images.py` — zero-dependency deterministic SVGs from a
  real match + real verification pass; embedded in README §5.
- `sdk/series.py` + CLI `series` — N sub-games → aggregation → self-audited artifacts.

## Remaining
- 7.2 Gmail sender (OAuth `gmail.send` only) — blocked on the user's `credentials.json`;
  gatekeeper hardening (call log + DOS counter) rides along.
- 7.8 two-repo split, cross-links, `v1.0-submission` tags, secrets-history scan.

## Gate evidence
`uv run police-thief series --games 2` writes all six files; `replay` returns Verified
OK on them; images in `docs/img/` regenerate byte-identically.
