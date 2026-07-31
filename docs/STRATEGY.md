# STRATEGY.md — the brains, and how to replace them

## What ships

| Role | Class | Policy |
|---|---|---|
| Thief | `strategy/heuristic.py:ManhattanBayesThief` | flee: maximize Manhattan distance to the belief argmax; prefer unvisited cells; HOLD when walled in |
| Police | `strategy/trapping.py:TrapperPolice` | A* forced-capture search over moves + Barrier-Law placements against a deterministic opponent model; shortest capture line wins (R46/overlap/R47); interception chase as fallback |

Both subclass `domain/brains.py:BrainBase`. The contract (mirrors the reference):

```python
decide(state, belief, opponent_hint, play_setting, barriers_max, ...) -> Decision
# role-specific internals:
_pick_move(moves, state, belief)          # thief:  (direction, cell) from legal moves
_decide_move(state, belief, barriers_max) # police: (MoveType, Direction | None)
```

`Decision(move_type, direction, hint, bluff)` — the hint/bluff fields are filled by the
verbal layer (`strategy/trash_talk.py`), never by the movement logic (Rule 25: the move
is always pure Python; an LLM may only ever produce banter text).

## Inputs a brain may use (all local truth)

- `state` — own position, own visited set, board with barriers (`board.distance`,
  `board.legal_moves`).
- `belief` — `BeliefGrid` over the opponent: `most_likely()`, full `grid`. Updated for
  you by the receive path (diffusion → scent fusion → hint reweighting with trust EMA).
- `opponent_hint` — the last verbal claim, already judged upstream; treat as color.
- Tunables live in the PRIVATE toml (never signed): `[belief] smell_trust_weight`, seed.

## How to swap a brain (current mechanism)

Selection happens in `peer/runner.py:PeerProcess.__init__` — replace the constructor
call with your class (or subclass `TrapperPolice` and override `_score`-adjacent pieces).
Keep two invariants or the runtime will degrade your decisions: a thief returning
`BARRIER` is converted to HOLD (cop-only privilege), and any illegal move falls back to
HOLD (never stall the loop).

*Honest note:* dynamic class loading from the toml (`[strategy] thief_class = "pkg:Cls"`,
as the reference supports) is **not implemented** — selection is in code. If needed, it
is a ~15-line change in `PeerProcess.__init__` (import by dotted path, instantiate).

## Why not RL

Reinforcement learning is optional per the course book. The decisive empirical fact
(RESEARCH-REPORT §3): capture on this grid is a *planning* problem — a lone cop is
robber-win without barriers, and 1-ply reward shaping produces guarding, not capturing.
A deterministic forced-capture search solves it with milliseconds of compute, zero
training, and full auditability.
