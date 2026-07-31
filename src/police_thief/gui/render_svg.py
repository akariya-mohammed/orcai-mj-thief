"""Pure-string SVG rendering (task 7.5) — zero dependencies, byte-deterministic,
embeds natively in GitHub READMEs. All submission images come from here."""
from __future__ import annotations

from police_thief.gui.viewmodel import color_for

CELL = 40
HEADER = 64
_BANNER_FILL = {"green": "#1a7f37", "gray": "#6b7280", "red": "#cc0000"}


def _board_group(view: dict, ox: int = 0, oy: int = 0) -> str:
    size = view["size"]
    parts = [f'<g transform="translate({ox},{oy})">']
    for r in range(size):
        for c in range(size):
            fill = color_for(view["heat"][r][c])
            parts.append(f'<rect x="{c * CELL}" y="{r * CELL}" width="{CELL}" '
                         f'height="{CELL}" fill="{fill}" stroke="#999"/>')
    for (r, c) in view["barriers"]:
        parts.append(f'<rect x="{c * CELL}" y="{r * CELL}" width="{CELL}" '
                     f'height="{CELL}" fill="#111111"/>')
    pr, pc = view["own_pos"]
    parts.append(f'<circle cx="{pc * CELL + CELL // 2}" cy="{pr * CELL + CELL // 2}" '
                 f'r="{CELL // 3}" fill="#1d4ed8" stroke="#ffffff" stroke-width="3"/>')
    parts.append("</g>")
    return "".join(parts)


def render_board_svg(view: dict, title: str = "") -> str:
    size = view["size"]
    w, h = size * CELL, size * CELL + HEADER
    text, color = view["banner"]
    banner_fill = _BANNER_FILL[color]
    head = (
        f'<rect x="0" y="0" width="{w}" height="{HEADER}" fill="#f3f4f6"/>'
        f'<text x="8" y="20" font-family="monospace" font-size="14" '
        f'font-weight="bold">{title or view["role"].upper()}</text>'
        f'<text x="8" y="40" font-family="monospace" font-size="12">'
        f'step {view["step"]} · trust {view["trust"]:.2f} · phase {view["phase"]}</text>'
        f'<rect x="{w - 130}" y="8" width="122" height="24" rx="4" fill="{banner_fill}"/>'
        f'<text x="{w - 69}" y="25" font-family="monospace" font-size="12" '
        f'fill="#ffffff" text-anchor="middle">{text}</text>'
        f'<text x="8" y="58" font-family="monospace" font-size="11" '
        f'fill="#374151">hint: {view["hint"]}</text>'
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
            f"{head}{_board_group(view, 0, HEADER)}</svg>")


def render_progression(views: list[dict], gap: int = 20) -> str:
    size = views[0]["size"]
    bw, bh = size * CELL, size * CELL
    w = len(views) * bw + (len(views) - 1) * gap
    panels = []
    for i, view in enumerate(views):
        panels.append(_board_group(view, i * (bw + gap), 24))
        panels.append(f'<text x="{i * (bw + gap)}" y="16" font-family="monospace" '
                      f'font-size="13">step {view["step"]}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{bh + 24}">'
            f'{"".join(panels)}</svg>')


def render_badge(verdict: str, detail: dict) -> str:
    ok = verdict == "Verified OK"
    fill = "#1a7f37" if ok else "#cc0000"
    sub = (f'{detail.get("steps_checked", 0)} steps cryptographically verified'
           if ok else f'tamper at step {detail.get("step")} ({detail.get("layer")})')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="90">'
            f'<rect x="2" y="2" width="416" height="86" rx="10" fill="#ffffff" '
            f'stroke="{fill}" stroke-width="3"/>'
            f'<text x="210" y="40" font-family="monospace" font-size="24" '
            f'font-weight="bold" fill="{fill}" text-anchor="middle">{verdict}</text>'
            f'<text x="210" y="68" font-family="monospace" font-size="13" '
            f'fill="#374151" text-anchor="middle">{sub}</text></svg>')
