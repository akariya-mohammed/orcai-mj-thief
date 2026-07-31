# PRD 1 — Base Logic

**Goal:** the physical core of the game in a single process, no networking or AI. Prove the
board, movement, barriers, capture, and scoring are correct before anything is layered on top.

## Scope
- 7×7 board (`[grid_size]`), (row, col), origin top-left, 0-indexed.
- Movement: N/S/E/W + STAY (HOLD). **No diagonals** (Rule 14).
- Barriers: cop may place up to `[max_barriers]`=14 (Rule 12); impassable to both; irreversible.
- Capture: overlap · barrier-on-thief (Rule 46) · thief fully walled in (Rule 47).
- Scoring table (Rule 48): capture 20/5 · survival 5/10 · tie 2/2 · technical loss 0/0.

## Out of scope (later stages)
FastMCP, tunneling, scent/pheromones, belief, LLM, crypto, GUI, reporting.

## Modules
- `domain/board.py` — geometry, legal moves, Manhattan distance.
- `domain/own_state.py` — local state + `apply_move` (returns False on illegal → HOLD fallback).
- `domain/rules.py` — capture/survival resolution.
- `domain/scoring.py` — outcome → (cop, thief) points from the signed config.

## Milestone gate (must be an OBSERVED behavior)
Two agents move legally on the 7×7; a barrier over quota is rejected; overlapping cells
trigger capture; a diagonal move is rejected. Verified by `tests/test_board.py`.
