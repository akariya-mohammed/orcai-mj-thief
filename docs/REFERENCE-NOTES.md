# Reference notes — facts pulled from the lecturer's repo (via NotebookLM)

Structural/interface alignment only — our logic is our own. Reference is educational
(Rule: "starting point, not a submission solution"). Kept so a grader recognizes the shape.

## Package layout (reference `src/police_thief/`)
```
__init__ · __main__ · cli · constants · exceptions
domain/   belief board brains crypto game_ids negotiation own_state protocol rules scoring smell
gui/      board_view game_mode live_apply live_controls player replay replay_controls replay_data window
infra/    email_sender llm_provider mcp_client mcp_server
peer/     control_link controls handshake runtime runtime_control sealing summary turn_handler turn_sender
report/   artifact_helpers artifact_schemas artifacts emit report_writer
sdk/      sdk series
shared/   config gatekeeper rate_limiter sysinfo version
strategy/ talk_providers trash_talk
```
(We also keep `domain/state_machine.py` — the book gives its code verbatim in Ch. 8.)

## Brain interface (verbatim, `docs/STRATEGY.md`)
- **`_pick_move(moves, state, belief)`** — THIEF.
  - `moves`: `list[(Direction, (row, col))]`, already filtered legal (edges + barriers, per `move_set`).
  - `state`: `OwnGameState` → `state.position`, `state.visited`, `state.barriers`, `state.board` (with `board.distance(a, b)`).
  - `belief`: `BeliefGrid` → `belief.most_likely()` returns the single most-likely opponent cell.
  - **Returns** the `(direction, cell)` tuple to play.
- **`_decide_move(state, belief, barriers_max)`** — POLICE. **Returns** `(MoveType, Direction | None)`.
- Public entry: **`brain.decide(state, belief, opponent_hint, play_setting, barriers_max, deadline_seconds=, short_threshold=)`** → `Decision(move_type, direction, hint)`.

## Turn loop (`peer/runtime.py`): wait green → think → move → seal → send
See `src/police_thief/peer/runtime.py` docstring for the exact reference sequence.
Key calls: `state.apply_move(...)` (falls back to `HOLD` if illegal), `sealed_step_record(...)`
→ `record["commit"]`, `my_scent.deposit(pos, smell.emit_intensity)` + `my_scent.decay_all()`,
`build_turn_message(...)`, `transport.send_turn(...)`.

Config access is dotted: `config.get("rules.barriers_max")`, `"smell.emit_intensity"`,
`"play.setting"`, `"llm.short_prompt_threshold_seconds"`.

## Belief, gatekeeper, architecture (Batch C)
- **BeliefGrid** (`domain/belief.py`): probability grid over the board for the opponent's cell;
  updated from received (decaying) smell grids + (possibly lying) hints, **diffused each turn**
  (opponent moved one step). Shown as the GUI heatmap.
- **Reliability coefficient** = `smell_trust_weight = 4.0` in each side's PRIVATE `game.toml`
  `[belief]` (not shared, not signed).
- **No central Orchestrator** — forbidden (no server/referee/shared state, Rule 1/2). The per-peer
  single entry point (Rule 3) is the **`SimulationSdk`** facade ("Facade over the whole simulation").
- **Gatekeeper** = `ApiGatekeeper.execute()` — ALL LLM/email/network calls go through it:
  sliding-window rate limit, FIFO queue on overflow, retry on transient errors, logging.
  `RateLimiter` is a **sliding-window** (`WINDOW_SECONDS = 60.0`) that **queues rather than errors**.
  Policy lives in per-side `config/**/rate_limits.json` (operational) + signed `rate_limiter_gatekeeper`.
- **Scripts:** `sync_versions.py` deep-links code version (`shared/version.py` `CODE_VERSION`) + book
  version into README, bundles the book PDF into docs/ (pre-commit hook, no-op if unchanged).
  `render_docs_images.py` renders the README GUI images (belief heatmap + annotated screenshot,
  Pillow) from a saved match log — **this is how the mandatory screenshots are generated**.

## Still needed
- **Sealing preimage:** `peer/sealing.py` `sealed_step_record` + how `record["commit"]` is
  computed (which payload fields are hashed, serialization, nonce placement).
