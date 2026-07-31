# PRD 3 — Blind Strategy Module

**Goal:** a working decision brain that plays on the belief map, with no scent, language, or
LLM yet ("blind"). Proves the spatial reasoning is correct before uncertainty is layered on.

## Scope
- `strategy/heuristic.py` — `ManhattanBayesThief` (`_pick_move`) and `ManhattanBayesPolice`
  (`_decide_move`), both subclassing `BrainBase`.
- Cop **minimizes** Manhattan distance to the belief argmax (chase); thief **maximizes** it (flee).
- Deterministic tie-breaking (unvisited preference for the thief; N/S/E/W order otherwise).
- The move is pure Python (Rule 25). The `hint` stays empty until Stage 4.

## Out of scope (later)
Scent-fused belief updates, verbal hints + lie-detection (Stage 4), barrier-trap tactics
(edge e3), Q-learning (optional).

## Milestone gate
- Automated (`tests/test_strategy.py`): given a belief concentrated on a known cell, the cop
  moves to reduce distance and reaches it in the minimum number of steps (shortest path); the
  thief moves to a max-distance cell; a fully walled-in agent holds.
- This is the baseline that already satisfies the **Adaptation** success metric.
