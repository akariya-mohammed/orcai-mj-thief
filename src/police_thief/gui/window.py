"""Live Tk window (task 7.3) — a WINDOW on the game, never a brake on it.

Threading contract: the game loop (PeerProcess.run) moves to a daemon worker
thread; Tk owns the main thread and polls a read-only view-model snapshot every
200 ms. The runtime never waits on the GUI — rendering cannot stall the turn
loop. Local truth only (Rules 8-9): everything drawn comes from build_view.
Untested by design (physical UI); all logic lives in viewmodel.py (tested).
"""
from __future__ import annotations

import threading
import tkinter as tk

from police_thief.gui.viewmodel import build_view, color_for

CELL = 40
HEADER = 64
_BANNER = {"green": "#1a7f37", "gray": "#6b7280", "red": "#cc0000"}


def launch_live(process, max_turns=None) -> None:
    threading.Thread(target=lambda: process.run(max_turns), daemon=True).start()

    root = tk.Tk()
    root.title(f"police-thief — {process.role_name} (local truth)")
    size = process.runtime.state.board.grid_size
    canvas = tk.Canvas(root, width=size * CELL, height=size * CELL + HEADER,
                       bg="#f3f4f6")
    canvas.pack()

    def refresh() -> None:
        view = build_view(process.runtime, step=len(process.runtime.records))
        canvas.delete("all")
        text, color = view["banner"]
        canvas.create_text(8, 14, anchor="w", font=("Consolas", 11, "bold"),
                           text=f"{view['role'].upper()}  step {view['step']}  "
                                f"trust {view['trust']:.2f}")
        canvas.create_rectangle(size * CELL - 130, 6, size * CELL - 8, 30,
                                fill=_BANNER[color], outline="")
        canvas.create_text(size * CELL - 69, 18, fill="#ffffff",
                           font=("Consolas", 10, "bold"), text=text)
        canvas.create_text(8, 34, anchor="w", font=("Consolas", 9),
                           text=f"phase {view['phase']}")
        canvas.create_text(8, 52, anchor="w", font=("Consolas", 9),
                           text=f"hint: {view['hint']}")
        for r in range(size):
            for c in range(size):
                canvas.create_rectangle(c * CELL, r * CELL + HEADER,
                                        (c + 1) * CELL, (r + 1) * CELL + HEADER,
                                        fill=color_for(view["heat"][r][c]),
                                        outline="#999999")
        for (r, c) in view["barriers"]:
            canvas.create_rectangle(c * CELL, r * CELL + HEADER, (c + 1) * CELL,
                                    (r + 1) * CELL + HEADER, fill="#111111")
        pr, pc = view["own_pos"]
        canvas.create_oval(pc * CELL + 8, pr * CELL + HEADER + 8,
                           (pc + 1) * CELL - 8, (pr + 1) * CELL + HEADER - 8,
                           fill="#1d4ed8", outline="#ffffff", width=3)
        root.after(200, refresh)

    refresh()
    root.mainloop()
