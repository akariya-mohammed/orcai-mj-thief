"""Headless view-model (task 7.3) — the ONLY bridge between runtime and any renderer.

LOCAL TRUTH ONLY (Rules 8-9): the view carries this peer's position, its own
barriers knowledge, and the BELIEF heatmap over the opponent — never the
opponent's actual position, which this process does not and must not know.
Pure snapshot: renderers (Tk window, SVG artifacts) consume the same dict.
"""
from __future__ import annotations


def color_for(intensity: float) -> str:
    """White -> strong red as belief intensity rises (book Ch. 7 heatmap)."""
    t = max(0.0, min(1.0, intensity))
    r = round(0xFF + (0xCC - 0xFF) * t)
    gb = round(0xFF * (1.0 - t))
    return f"#{r:02x}{gb:02x}{gb:02x}"


_BANNERS = {
    "WAITING_FOR_OPPONENT": ("LOCKED", "gray"),
    "TECHNICAL_LOSS": ("TECHNICAL LOSS", "red"),
}


def build_view(runtime, step: int) -> dict:
    grid = runtime.belief.grid
    peak = max(max(row) for row in grid) or 1.0
    return {
        "size": runtime.state.board.grid_size,
        "role": runtime.role.value,
        "own_pos": runtime.state.position,
        "barriers": sorted(runtime.state.barriers),
        "heat": [[cell / peak for cell in row] for row in grid],   # normalized belief
        "banner": _BANNERS.get(runtime.phases.state, ("YOUR TURN", "green")),
        "trust": runtime.trust_ema,
        "hint": (runtime.last_opponent_hint or "")[:60],
        "phase": runtime.phases.state,
        "step": step,
    }
