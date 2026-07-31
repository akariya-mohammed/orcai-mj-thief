"""Post-game mutual audit — the violation matrix (tasks 6.5 + P0-3, Book Ch. 5).

Governing principle: **declare only what we can prove**. The book punishes a
false accusation as harshly as a real violation, so every check here is one an
honest opponent cannot fail, and anything merely suspicious is reported as a
finding for a human rather than auto-escalated.

Layers
  hash   — every revealed preimage must reproduce its committed digest
  move   — the revealed position chain must be legal: single orthogonal steps,
           no thief-placed walls, quota respected, declared start honoured
  scent  — P0-3: the broadcast trail must be explicable by the revealed walk
"""
from __future__ import annotations

from police_thief.domain.board import DELTAS
from police_thief.domain.crypto import verify

Finding = dict


def _finding(rule: str, step, detail: str) -> Finding:
    return {"rule": rule, "step": step, "detail": detail}


def audit_hash_chain(records) -> list[Finding]:
    """Recompute every commitment from its revealed preimage (Rule 19)."""
    out = []
    for i, rec in enumerate(records, start=1):
        try:
            ok = verify(rec["state"], rec["move"], rec["intent"],
                        rec["nonce"], rec["commit"])
        except (KeyError, TypeError):
            out.append(_finding("hash", i, "record is missing reveal fields"))
            continue
        if not ok:
            out.append(_finding("hash", i, "revealed preimage does not match the "
                                           "digest committed that turn"))
    return out


def audit_move_chain(records, role: str, start, barriers_max: int) -> list[Finding]:
    """Walk the revealed positions and check every transition was legal."""
    out, walls, previous = [], 0, tuple(start)
    for i, rec in enumerate(records, start=1):
        position = tuple(rec.get("position", previous))
        move = rec.get("move", "")
        if move.startswith("BARRIER"):
            if role == "thief":
                out.append(_finding("move", i, "thief placed a barrier (cop-only)"))
            walls += 1
            if walls > barriers_max:
                out.append(_finding("move", i,
                                    f"barrier {walls} exceeds the quota of {barriers_max}"))
            if position != previous:
                out.append(_finding("move", i, "moved while placing a barrier"))
        elif move.startswith("MOVE:"):
            delta = next((d for d in DELTAS if d.value == move.split(":", 1)[1]), None)
            expected = (previous[0] + DELTAS[delta][0],
                        previous[1] + DELTAS[delta][1]) if delta else None
            if expected is None:
                out.append(_finding("move", i, f"unknown direction in {move!r}"))
            elif position != expected:
                out.append(_finding("move", i, f"declared {move} from {list(previous)} "
                                               f"but revealed {list(position)}"))
        elif position != previous:
            out.append(_finding("move", i, f"HOLD from {list(previous)} but revealed "
                                           f"{list(position)}"))
        previous = position
    return out


def _windows(positions, radius: int) -> set:
    """Every cell any emission window could ever have touched along the walk."""
    seen = set()
    for r, c in positions:
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                seen.add((r + dr, c + dc))
    return seen


def audit_scent_history(positions, broadcasts, pheromones: dict, size: int,
                        strict: bool = False, tol: float = 1e-6) -> list[Finding]:
    """P0-3: can the trail they broadcast be explained by the walk they revealed?

    STRUCTURAL (default): every cell they ever claimed scent in must lie inside
    an emission window around somewhere they had actually been by that turn. No
    honest emission model can violate this, whatever its falloff curve.

    STRICT: replay OUR locked model and demand equality. Only fair when both
    peers declared the same scent model at handshake — our falloff was fitted to
    the book's figure and never confirmed against another implementation.
    """
    if not broadcasts:
        return []                      # incomplete data is not proof of cheating
    radius = int(pheromones.get("pheromone_grid_size", 5)) // 2
    out: list[Finding] = []
    for i, snapshot in enumerate(broadcasts, start=1):
        reachable = _windows(positions[:i], radius)
        stray = [cell for cell in snapshot if cell not in reachable]
        if stray:
            out.append(_finding("scent", i,
                                f"scent broadcast at {sorted(stray)[:3]} — no revealed "
                                f"position could have emitted there"))
    if strict and not out:
        out.extend(_audit_scent_strict(positions, broadcasts, pheromones, size, tol))
    return out


def _audit_scent_strict(positions, broadcasts, pheromones, size, tol) -> list[Finding]:
    from police_thief.domain.smell import ScentGrid

    grid = ScentGrid(size, pheromones.get("pheromone_center_intensity", 0.9),
                     pheromones.get("pheromone_decay", 0.10),
                     int(pheromones.get("pheromone_grid_size", 5)))
    out = []
    for i, (pos, snapshot) in enumerate(zip(positions, broadcasts), start=1):
        grid.deposit(pos)
        grid.decay_all()
        expected = grid.snapshot()
        if any(abs(expected.get(c, 0.0) - v) > tol for c, v in snapshot.items()) or \
           any(abs(snapshot.get(c, 0.0) - v) > tol for c, v in expected.items()):
            out.append(_finding("scent-model", i,
                                "broadcast trail deviates from the agreed emission model"))
    return out


def audit_opponent(records, *, role: str, start, barriers_max: int,
                   broadcasts=None, pheromones=None, size: int = 7,
                   strict_scent: bool = False) -> dict:
    """Run the whole matrix. passed=False means we can PROVE a violation."""
    findings = audit_hash_chain(records)
    findings += audit_move_chain(records, role, start, barriers_max)
    if broadcasts is not None:
        findings += audit_scent_history([tuple(r.get("position", start)) for r in records],
                                        broadcasts, pheromones or {}, size, strict_scent)
    return {"passed": not findings, "failures": findings,
            "checked": {"records": len(records), "broadcasts": len(broadcasts or [])}}
