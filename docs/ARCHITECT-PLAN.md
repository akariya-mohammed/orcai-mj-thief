# ARCHITECT-PLAN — Living Implementation Plan & Project Review

> **Role contract:** This document is maintained by the Architect (Fable) and executed by the
> Implementer (Opus). Opus should be able to complete any single task below using ONLY: this
> document, the task's listed files, and `docs/REFERENCE-NOTES.md`. Do not re-derive context.
> **Status legend:** □ not started ◐ in progress ✅ done
> **Authority order on any conflict:** binding parameters table (book appendix ו) → book body →
> assignment brief → reference repo → this plan.

---

## 1. Project Architecture

### 1.1 What this system is
Two fully independent peer processes (Police, Thief) play pursuit on a 7×7 grid. No central
server, no referee, no shared state (Rules 1–2). Each peer: own FastMCP server (exposes
`receive_move`), own MCP client (calls the opponent's URL), own config, own GUI. Trust comes
from per-step SHA-256 commit-reveal + a mutual post-game log audit. Grade = qualify (55 rules,
2 repos, ≥2 league games) then league rank maps 75→100; strategy strength is critical path.

### 1.2 Folder structure & module responsibilities (current, verified on disk)

```
final-project/
├─ config/
│  ├─ game.json            SIGNED shared contract (byte-identical between peers)
│  └─ game.toml.example    PRIVATE per-peer template (port, opponent_url, [belief], [llm], [email])
├─ docs/                   PRD-1..3, REFERENCE-NOTES.md (verbatim reference facts), this file
├─ src/police_thief/
│  ├─ domain/              Pure game logic — NO I/O, NO network. Fully unit-testable.
│  │  ├─ board.py          Board: bounds, barriers, legal_moves (orthogonal), Manhattan distance
│  │  ├─ own_state.py      OwnGameState: position/visited/barriers; apply_move → False on illegal
│  │  ├─ rules.py          resolve(): CAPTURE (overlap | barrier-on-thief R46 | walled-in R47) / SURVIVAL / ONGOING
│  │  ├─ scoring.py        outcome → (cop, thief) points from signed scoring block
│  │  ├─ belief.py         BeliefGrid: uniform prior, diffuse(), update_from_smell (exp(trust·τ)), penalize(), most_likely()
│  │  ├─ brains.py         BrainBase interface: decide() → _pick_move (thief) / _decide_move (police); Role/MoveType/Direction/Decision
│  │  ├─ crypto.py         commit()/verify(): canonical-JSON {state,move,intent,nonce} → SHA-256 (PRIMITIVE — sealing.py will own the full record)
│  │  ├─ state_machine.py  GamePhaseMachine: WAITING→COMPUTING→COMMITTING→AWAITING_REVEAL→VERIFYING→WAITING; TECHNICAL_LOSS terminal
│  │  ├─ protocol.py       TurnMessage (role, commit, hint, scent "r,c"-keyed, capture_claim, claim_response, win_claim) + build_turn_message
│  │  └─ [EMPTY] smell.py, negotiation.py, game_ids.py
│  ├─ strategy/
│  │  ├─ heuristic.py      ManhattanBayesThief (flee argmax), ManhattanBayesPolice (chase argmax)
│  │  └─ [EMPTY] trash_talk.py
│  ├─ peer/
│  │  ├─ runtime.py        PeerRuntime.run_turn: think→move(HOLD fallback)→seal→send→(fake verify)→wait
│  │  └─ [EMPTY] sealing.py, turn_sender.py, handshake.py
│  ├─ infra/
│  │  ├─ mcp_server.py     build_server(name, on_turn) → FastMCP + receive_move tool (fastmcp lazy-imported)
│  │  ├─ mcp_client.py     OpponentLink.send_turn (⚠ sync usage of async fastmcp Client — hidden bug, task 5.1)
│  │  └─ [EMPTY] email_sender.py, llm_provider.py
│  ├─ shared/
│  │  ├─ rate_limiter.py   RateLimiter: sliding 60s window, try_acquire (queues, never errors)
│  │  ├─ gatekeeper.py     ApiGatekeeper.execute: rate-limit → queue → retry (busy-wait sleep = debt)
│  │  └─ [EMPTY] config.py, sysinfo.py, version.py
│  ├─ report/
│  │  ├─ artifact_schemas.py  Verbatim field lists: 4 artifacts + 2 sealed-payload shapes (step0/move)
│  │  └─ [EMPTY] report_writer.py
│  ├─ sdk/  sdk.py (SimulationSdk facade stub — the Rule-3 single gateway; NO central orchestrator exists or may exist)
│  │        [EMPTY] series.py
│  ├─ gui/  [EMPTY package]
│  └─ [EMPTY] constants.py, exceptions.py   [MISSING] __main__.py, cli.py  ← pyproject declares entry point that doesn't exist
└─ tests/  test_board (9) · test_belief (4) · test_crypto (3) · test_protocol (2) · test_strategy (4) = 23, all passing WITH PYTHONPATH=src
```

### 1.3 Dependency graph (current modules)

```
board ← own_state ← rules          brains ← heuristic
board ← belief                      brains ← runtime
crypto ← runtime                    protocol ← runtime
state_machine ← runtime             mcp_server/mcp_client ←(lazy) fastmcp
rate_limiter ← gatekeeper           artifact_schemas (leaf, data only)
```
`domain/` has zero inward dependencies on infra/peer/gui — keep it that way (it is why 23
tests run with no network deps installed).

### 1.4 Control flow — one turn (current skeleton, `peer/runtime.py`)
1. `WAITING_FOR_OPPONENT` — (opponent's message would arrive via `receive_move` → on_turn)
2. `COMPUTING_MOVE` — `brain.decide(state, belief, opponent_hint, play_setting, barriers_max)`
3. apply: `state.apply_move(...)`; on `False` → `apply_move(HOLD)` — **never stall**
4. `COMMITTING` — `crypto.commit(state_str, move_str, intent)` → record appended (commit+nonce+move+state+intent+hint)
5. `AWAITING_REVEAL` — `build_turn_message(role, hint, my_scent, commit, capture_claim)` → `transport.send_turn(dict)`
   - `capture_claim = position` on every police MOVE (mirrors reference — implicit landing-cell claim)
6. `VERIFYING` → `WAITING_FOR_OPPONENT` — **currently fake**: no opponent reveal is received or verified (Stage 6)

### 1.5 Game lifecycle (target, per book/reference — mostly not built)
handshake (config-hash match, Step-0 exchange) → N sub-games ([num_games]=6 for full series;
default 1) → per sub-game: turn loop until CAPTURE/SURVIVAL/max_moves → mutual log audit →
4 JSON artifacts → both peers email result → series aggregate + tie rule.

### 1.6 AI lifecycle (target)
receive turn msg → belief.diffuse() → belief.update_from_smell(msg.scent) → hint parse →
lie-check (scent vs claim) → penalize/reweight → brain.decide (pure Python) → optional LLM
bluff text (never the move) → seal → send.

---

## 2. Progress Audit

| Stage | Claimed | Audit verdict | Notes |
|---|---|---|---|
| 1 Base logic | ✅ | **Mostly complete — 2 rule gaps** | Barrier-on-own-cell not supported (book Ch.3 allows own cell OR 4 adjacent; `own_state` requires a direction). Thief-may-not-barrier not enforced anywhere. Movement/capture/scoring/quota verified correct. |
| 2 MCP infra | ✅ | **Automated gate only — live path unproven + 1 hidden bug** | Protocol round-trip and phase cycle are real. But `mcp_client` uses fastmcp's async `Client` synchronously (will fail live); `mcp.run(transport="http")` unverified against installed fastmcp version; the 2-process localhost handshake has never been run. |
| 3 Blind strategy | ✅ | **Complete for "blind" scope** | Chase/flee/shortest-path/walled-in verified. Known finding: open-board evasion is indefinite → cop cannot win without barrier traps (4.8). Tie-breaking is deterministic (fixed N/S/E/W order) — predictable to opponents; acceptable now, revisit in 4.8. |
| Hygiene | — | **3 hard gaps (verified this session)** | (a) NOT a git repo — no history, no tag possible, Rule 41/50 unmet, grading "process story" absent. (b) Bare `pytest` fails collection; only `PYTHONPATH=src pytest` passes. (c) `pyproject` entry point `police_thief.__main__:main` doesn't exist → README run commands are false. |
| 4–7 | pending | — | 22 empty stub files mark the intended homes. |

**Assumptions currently baked in (each must be revisited at the marked task):**
- Belief diffusion is 3×3 king-step (reference parity) though movement is orthogonal+stay → task 4.5.
- `crypto.commit` hashes only {state, move, intent, nonce}; reference seals a richer record → task 6.1 (interop-critical).
- Turn-1 initiation / who-moves-first semantics undefined → task 5.3.
- Simulations share one `Board` between both `OwnGameState`s (fine for dev physics; real peers each hold a copy synced by declared placements) → task 6.3.

---

## 3. Stage Validation (1–3)

### Stage 1 — Base logic: **PASS with 2 WARNINGS**
- Correctness: movement, bounds, Manhattan, quota, all three capture modes, scoring — verified by 9 tests driven from the signed config (good pattern: tests read `config/game.json`, so a renegotiated contract re-validates automatically).
- **WARNING W1 (rule fidelity):** barrier placement on the cop's *own* cell is legal per book Ch.3 but unimplementable in `own_state.apply_move` (direction required). Low competitive impact, but a rules-compliance reviewer could flag it. Fix task H4.
- **WARNING W2 (missing guard):** nothing prevents a Thief brain from returning `BARRIER`; `apply_move` would accept it. Never triggers with shipped brains, but it's a latent illegal-move generator if a custom brain misbehaves, and legality of *opponent* moves must be verified anyway (Stage 6). Fix task H4 (role guard) + 6.3 (verify side).
- Maintainability: clean; `rules.resolve` is a pure function — ideal.
- Performance: trivial (49 cells). No concerns.

### Stage 2 — MCP infra: **WARNING**
- Protocol design: PASS. TurnMessage carries commit+hint, never move/nonce (Rule 27 honored); scent wire-format survives JSON; `from_dict(to_dict(m))` proven.
- State machine: PASS — table-driven, illegal jumps raise, terminal state modeled.
- **WARNING W3 (hidden bug, certain):** `OpponentLink.send_turn` does `with Client(...)` + bare `call_tool` — fastmcp's Client is **async** (`async with` + `await`). This compiles, imports, and passes tests (lazy import) but fails on first live use. Fix task 5.1.
- **WARNING W4 (unproven path):** live two-process handshake never executed; `transport="http"` vs installed fastmcp version unverified. Gate is only half-earned. Task 5.1 closes it.
- **WARNING W5 (fake verify):** run_turn transitions VERIFYING→WAITING with no reveal exchange. Correct as a Stage-2 skeleton, but the phase machine currently asserts a flow that isn't real; do not tick Stage-6 boxes off this. Task 6.3 makes it real.

### Stage 3 — Blind strategy: **PASS with 1 note**
- Correctness: proven chase-optimality (reaches target in exactly Manhattan-distance steps), max-distance flee, HOLD when walled.
- Architecture: `BrainBase.decide()` public + role-specific overrides matches the reference extension contract (`thief_class` / `police_class` in toml) — graders and opponents will recognize it.
- **Note N1 (predictability):** deterministic tie-breaks make our thief exploitable by a modeling opponent (they can simulate our flee). Acceptable for the blind stage; 4.8/4.7 should add belief-aware variation. Not a bug.
- **Note N2 (grading):** the open-board-evasion finding is a *strength* — write it into the README/RESEARCH-REPORT as an empirical result motivating the barrier-trap design (evidence-driven engineering is exactly what Segal rewards).

---

## 4. Technical Debt (ranked)

| # | Debt | Where | Priority | Resolution |
|---|---|---|---|---|
| D1 | Not a git repo (no history/tag/branches; Rules 41, 50; grading story) | repo root | **P0** | H1 |
| D2 | Bare `pytest` broken (needs PYTHONPATH) — any grader/CI running `pytest` sees 5 collection errors | pyproject | **P0** | H2 |
| D3 | Declared CLI entry point missing → README commands false (grading: "README claims must run") | `__main__.py`/`cli.py` | **P0** | H3 |
| D4 | Sync-over-async fastmcp client (certain live failure) | infra/mcp_client.py | P1 (before any live run) | 5.1 |
| D5 | Barrier-on-own-cell unsupported + thief-barrier unguarded | domain/own_state.py, rules | P1 | H4 |
| D6 | `crypto.commit` payload ≠ reference sealed record (interop with other teams' audits) | domain/crypto.py, peer/sealing.py | P1 (blocks 6.x) | 6.1 + intel |
| D7 | runtime builds its own ad-hoc record dict — record construction belongs to sealing.py | peer/runtime.py | P2 | 6.1 refactor |
| D8 | ApiGatekeeper busy-waits (`sleep(0.05)` loop), no logging, no DOS detector | shared/gatekeeper.py | P2 | 7.2 hardening |
| D9 | `my_scent` is a bare dict placeholder on runtime | peer/runtime.py | P2 (dissolves in 4.3) | 4.3 |
| D10 | Config access is `dict.get("dotted.key")` against a plain dict nobody constructs | everywhere config is read | P2 | 5.2 |
| D11 | Duplicated "belief concentrated on cell" helper in two test files | tests | P3 | conftest fixture, next test touch |
| D12 | Empty stubs could mislead a reviewer into thinking features exist | 22 files | P3 | each stage fills its own; delete leftovers at 7.7 |

No large files (biggest module 3.5 KB), no circular imports, no premature abstractions found.

---

## 5. Dependency Graph — remaining work

```
H1 git ──────────────┐ (everything after this is committed work)
H2 pytest cfg ───────┤
H3 CLI entry ────────┼─→ 4.11 selfplay eval harness (uses CLI)
H4 barrier rules ────┼─→ 4.8 barrier traps (needs own-cell rule correct)
                     │
4.1 scent emission ─→ 4.2 decay ─→ 4.3 runtime wiring ─→ 4.4 belief×scent fusion ─┐
4.5 diffusion model (independent of 4.1–4.3, before 4.4 lands is ideal)           ├─→ 4.7 lie detection ─→ 4.11 integration eval
4.6 hint parsing (independent; needs 4.4 for effect) ─────────────────────────────┘
H4 ─→ 4.8 barrier trap (independent of scent; needs belief argmax only) ─→ 4.11
4.9 template trash-talk (independent) ─→ 4.10 Ollama provider (optional) ─→ 4.11
                     │
5.1 async transport fix + live localhost gate  (blocks all live play)
5.2 config loader (blocks 5.3, 6.2, 7.1)
5.3 handshake/negotiation (needs 5.1, 5.2; finalized by 6.2 Step-0)
5.4 tunnel/ngrok (needs 5.1; user-operated)
5.5 deadline tracker + watchdog (needs 5.1 real network to be meaningful)
                     │
[INTEL: sealing.py verbatim] ─→ 6.1 sealing module ─→ 6.3 reveal+verify loop ─→ 6.4 capture-claim protocol
5.2 ─→ 6.2 Step-0 record (needs sysinfo, git hash, sealing)                     └─→ 6.5 final audit ─→ 6.6 tamper/technical-loss tests
                     │
6.5 ─→ 7.1 report writer (4 artifacts; needs game_ids/version/sysinfo from 6.2/7.0)
5.2, 7.1 ─→ 7.2 Gmail sender via Gatekeeper
4.4 ─→ 7.3 Live GUI (heatmap = belief render)     7.1 ─→ 7.4 Replay viewer (verify engine = 6.1 verify)
7.3/7.4 ─→ 7.5 screenshot generator ─→ submission
7.1 ─→ 7.6 series runner + tie rule
all ─→ 7.7 docs (PRDs 4–7, RESEARCH-REPORT, README completion) ─→ 7.8 two-repo split + tag ─→ league ops
```

---

## 6.–7. Master Roadmap — atomic tasks (full spec each)

Format per task: **Goal / Why / Files / Functions / Deps / Accept / Risks / Edges / Tests / Output / Cx / Risk**.
Cx: S ≈ ≤1 h, M ≈ 1–3 h, L ≈ 3–6 h (focused Opus session ≈ one M or two S).

### Hygiene (do first — one session, task H1–H4 batch)

**H1 · Initialize git**
Goal: `git init`, root commit of current tree, `master` + `develop` branch, meaningful message.
Why: Rule 41 (tag), Rule 50 (repo contents), grading values history-as-process; every later task must be a commit.
Files: repo root. Deps: none. Accept: `git log` shows root commit; `.gitignore` respected (no `__pycache__`, `.pytest_cache` tracked). Risks: committing caches — check `git status` first. Edges: CRLF on Windows (`core.autocrlf=true` default is fine). Tests: n/a. Output: initialized repo. **Cx S, Risk L.**

**H2 · Fix bare pytest**
Goal: add `pythonpath = ["src"]` under `[tool.pytest.ini_options]`.
Why: D2 — a grader running `pytest` currently sees 5 collection errors; that alone can cost quality points.
Files: pyproject.toml. Accept: `pytest -q` (no env vars) → 23 passed. Risks: none. **Cx S, Risk L.**

**H3 · CLI entry point**
Goal: create `src/police_thief/__main__.py` + `cli.py` with argparse: `peer --role {police,thief} [--config PATH]` (prints "not yet wired" + exits 2 for now), `replay --log PATH` (same), `selftest` (runs a 15-turn local sim like the Stage-3 sanity run, prints trajectory — **label output DEV TOOL, not a league mode**).
Why: D3 — README documents `uv run police-thief peer --role police`; a false README is a direct grading hit. `selftest` also becomes the 4.11 eval vehicle.
Files: `__main__.py`, `cli.py`. Functions: `main()`, `cmd_selftest()`. Deps: H1. Accept: `PYTHONPATH=src python -m police_thief selftest` runs the sim; `--help` correct; README updated if flags differ. Risks: keep `cli.py` free of fastmcp imports (import-time crash w/o dep). Edges: unknown role string → argparse error exit 2. Tests: `tests/test_cli.py` — selftest returns 0, peer without fastmcp exits cleanly with message. **Cx M, Risk L.**

**H4 · Barrier rule fidelity**
Goal: (a) `apply_move(BARRIER, direction=None)` places a barrier on the agent's **own** cell (book Ch.3: own cell or 4-adjacent); agent may stand on it (may move off later; if it's the thief's cell → capture, already handled by R46 logic). (b) Add role guard: `PeerRuntime` rejects a thief `BARRIER` decision → converts to HOLD + logs warning (defense-in-depth before Stage-6 opponent-side verification).
Why: W1/W2 — rules-compliance gaps a grader can find by reading the book next to the code.
Files: domain/own_state.py, peer/runtime.py. Deps: none. Accept: new tests below pass; existing 23 unaffected. Risks: barrier-on-own-cell must NOT mark the cop captured (R46 applies to the *thief's* cell only — verify rules.resolve args order). Edges: own-cell barrier when quota exhausted → False; own-cell barrier then attempt to re-place there → False (already barrier). Tests: `test_board.py` add: own-cell placement legal & occupiable, quota still enforced, thief BARRIER via runtime → HOLD applied, record shows HOLD. **Cx S, Risk L.**

### Stage 4 — Language + scent (the league-rank stage)

**4.1 · ScentGrid emission**
Goal: `domain/smell.py` — `ScentGrid(size, center_intensity=0.9, field_size=5)`; `deposit(pos)` adds a 5×5 radial field centered on pos, clipped at board edges; per-cell add `Δτ(d) = center · exp(−3d²/8)` (Euclidean d over window offsets — reproduces book Fig-4 values 0.90/0.62/0.42/0.20/0.14/0.04); clamp cell value to ≤ center after add.
Why: partial-observability core; the opponent's *only* unfakeable signal.
Files: domain/smell.py. Functions: `deposit`, `snapshot() -> dict[Cell,float]` (sparse, only >ε cells). Deps: none. Accept: depositing at center of empty 7×7 yields Fig-4 values within 0.01 at offsets (0,0),(0,1),(1,1),(0,2),(1,2),(2,2). Risks: **formula is derived from the book figure, not confirmed against reference `smell.py` — see Pending Intel I2; isolate the falloff in one function `emission_at(d)` so a differing reference formula is a one-line swap.** Edges: deposit at corner (field clipped, no wraparound); re-deposit same cell (clamp at 0.9, no growth) — matches book Fig-5 plateau. Tests: new `tests/test_smell.py`: field values, edge clipping, clamp, snapshot sparsity. Output: ScentGrid class. **Cx M, Risk M (formula).**

**4.2 · Scent decay**
Goal: `decay_all()`: every cell `τ ← (1−ρ)·τ` with ρ=0.10 from config; prune cells < 1e-3.
Why: book equation `τ(t+1)=max(0,(1−ρ)τ(t)+Δτ)`; decay is what makes trails *history* (readable ~6–7 turns).
Files: domain/smell.py. Deps: 4.1. Accept: single 0.9 deposit decays below 0.45 (half) between turns 6–8 (book: half-life ≈ 7); pruned cells absent from snapshot. Edges: decay on empty grid (no-op); decay+deposit same turn ordering = decay applies to *existing* scent, then deposit adds (reference order: deposit → decay_all — replicate reference order exactly and document it). Tests: half-life curve, prune, order-of-operations. **Cx S, Risk L.**

**4.3 · Wire scent into the turn loop**
Goal: replace `PeerRuntime.my_scent` dict with a `ScentGrid`; in the send path (after sealing, mirroring reference): `my_scent.deposit(state.position)`, `my_scent.decay_all()`, message carries `my_scent.snapshot()`.
Why: reference `turn_sender` order, verbatim in runtime docstring.
Files: peer/runtime.py, domain/protocol.py (snapshot already dict — no change expected). Deps: 4.1, 4.2. Accept: test_protocol's fake-transport turn shows a non-empty scent in the sent message; after 3 turns the trail has 3 decayed deposits. Risks: don't double-deposit on HOLD fallback (deposit happens once per turn regardless of move legality — presence emits, per book). Tests: extend test_protocol. **Cx S, Risk L.**

**4.4 · Belief × scent fusion (receive path)**
Goal: `PeerRuntime.on_opponent_turn(msg)` (new): `belief.diffuse()` then `belief.update_from_smell(msg.scent)`; store `msg.hint` for next `decide()`; return ack dict. Wire as the `on_turn` handler for `infra.mcp_server.build_server`.
Why: closes the sense→believe→act loop; heatmap = this belief (GUI later renders it).
Files: peer/runtime.py. Functions: `on_opponent_turn`. Deps: 4.3 (message shape), 4.5 ideally first. Accept: feeding a synthetic opponent trail moves `belief.most_likely()` to the trail head within 2 messages. Risks: diffuse-before-update order (opponent moved, THEN left evidence) — assert order in test. Edges: empty scent (early game) → belief just diffuses; malformed scent keys → ignore cell, don't crash (defensive parse in protocol already). Tests: new `tests/test_fusion.py`. **Cx M, Risk L.**

**4.5 · Diffusion model correction**
Goal: change `BeliefGrid.diffuse()` neighborhood from 3×3 king to **von Neumann + stay** (5 cells), matching actual movement physics (no diagonals exist in this game).
Why: reference uses king-step ("moved one king step" docstring) but our game's move set is N/S/E/W/STAY; a tighter transition model → sharper posterior → better targeting → league rank. Belief is fully private (never exchanged) → **zero interop risk**. Document the deliberate deviation in README §3 (evidence of independent reasoning — grading positive).
Files: domain/belief.py. Deps: none (do before 4.4 merges). Accept: point mass diffuses to exactly 5 cells; mass conserved (existing test adapts). Risks: barrier-aware diffusion (mass shouldn't flow into barrier cells) — add optional `board` param now, pass barriers when known; cells with no legal escape keep their mass (matches walled-in reality). Tests: update test_belief diffusion tests + barrier-blocked diffusion case. **Cx S, Risk L.**

**4.6 · Hint parsing & reliability weighting**
Goal: `domain/hints.py` (new; or fold into belief): parse a ≤15-word free-text hint into a coarse claim — direction mention (north/south/east/west), landmark mention (map_area lexicon), or null; apply to belief as a *weighted* update: `belief.apply_hint(claim, reliability)` multiplying claimed region by `(1 + reliability·w)`.
Why: hints are the only deception channel (book Ch.4); ignoring them wastes signal, trusting them fully is exploitable — reliability is the knob lie-detection (4.7) will tune.
Files: domain/hints.py, domain/belief.py. Deps: 4.4. Accept: "heading north" with reliability 1.0 shifts argmax northward on a flat prior; reliability 0 → no-op. Risks: over-engineering NLP — keep it a lexicon matcher, ≤40 lines; opponents' hints come from LLMs but reference hints are template-English ("I keep moving through the streets"). Edges: contradictory hint ("north... south") → null claim; empty hint; Hebrew hint (league opponents!) → lexicon covers צפון/דרום/מזרח/מערב too. Tests: `tests/test_hints.py` table-driven lexicon cases. **Cx M, Risk M (opponent language variance).**

**4.7 · Lie detection (scent-vs-claim)**
Goal: before applying a hint, compute contradiction: expected fresh-scent mass in the claimed region vs measured. If claim says "north" but northern cells' scent ≈ 0 while mass sits elsewhere (book's worked example: expected ≈(1−ρ)·0.9=0.81 vs measured 0.00), score contradiction → (a) apply `belief.penalize(claimed_region)`, (b) decay a running per-opponent `trust ∈ [0,1]` (EMA) that scales all future hint reliability.
Why: the book's flagship tactic; turns opponent deception into self-disclosure. Showcase in README + RESEARCH-REPORT.
Files: domain/hints.py (detector), peer/runtime.py (trust state). Deps: 4.6, 4.4. Accept: reproduce the book's example — hint "north", scent concentrated SE → argmax stays SE AND trust drops; truthful-hint sequence keeps trust ≈ 1. Risks: false positives early game (scent everywhere ≈ 0 → contradiction undefined — require min total scent mass before scoring); penalize factor too aggressive (make config-tunable in `[belief]`). Edges: opponent never hints (trust untouched); alternating truth/lie (EMA tracks). Tests: `tests/test_lie_detection.py`: book example, early-game guard, trust EMA trajectory. **Cx M, Risk M.**

**4.8 · Police barrier-trap heuristic** ← the win condition
Goal: extend `ManhattanBayesPolice._decide_move`: when `distance(self, argmax) ≤ trap_range` (config, default 2): enumerate thief's likely escape cells = `board.legal_moves(argmax)`; choose `BARRIER` on the escape cell that maximizes (thief_escape_count_reduction, then blocks the max-distance flee direction); else `MOVE` toward argmax biased to drive the thief toward the nearest corner (minimize thief's reachable-cell count, 1-ply). Maintain a quota budget: reserve ≥ 4 barriers for the endgame (config-tunable).
Why: Stage-3 finding — equal-speed pursuit NEVER captures on open board; barriers are the only capture mechanism. This heuristic is the single largest league-rank lever.
Files: strategy/heuristic.py. Functions: `_decide_move`, private `_trap_value(cell)`. Deps: H4 (own-cell rule), 4.4 (belief quality). Accept (empirical gate): in `selftest`-style sim vs the shipped blind thief with perfect-info belief, capture within 35 steps in ≥ 80% of 20 runs from standard start (currently 0%); never self-walls (cop retains ≥1 legal move after every placement); quota never exceeded. Risks: self-trapping (assert escape-move exists before placing); oscillation between MOVE/BARRIER (hysteresis: once trapping starts within range, prefer completing the wall). Edges: argmax on a barrier (stale belief) → fall back to chase; barriers exhausted → pure chase; thief adjacent → place on thief's cell = instant capture R46 (check first, it's the best move!). Tests: `tests/test_traps.py`: R46 immediate capture chosen when adjacent, no self-wall invariant (property test over 50 random games), capture-rate gate (seeded RNG). **Cx L, Risk M. This is the deepest task — allow a full session.**

**4.9 · Template trash-talk provider**
Goal: `strategy/trash_talk.py` + `strategy/talk_providers.py`: `TalkProvider` interface `produce(intent, context) -> hint`; `TemplateProvider` — pre-written English lines parameterized by [map_area] landmark lexicon (NY default) and direction; enforces [hint_max_words]=15; `intent` chosen by brain policy (simple: lie with p=0.5 when cop within distance 3, else truth). 0 tokens.
Why: Rule 26 (free natural language required) + the ≤15-word cap is a *signed* term; template mode lets the whole series run at 0 token cost ([token_budget]=200k is a ceiling, spending less is a fairness-scoring positive).
Files: strategy/trash_talk.py, talk_providers.py; runtime passes produced hint into Decision. Deps: none (parallel-safe). Accept: every produced hint ≤ 15 words, non-empty, direction-consistent with intent (truth → real direction, lie → false direction); `intent` recorded for the sealed record. Risks: hint accidentally leaking coordinates (Rule 27) — assert no digits in output. Edges: map_area unset → generic landmarks (book: default ""). Tests: `tests/test_talk.py`: word cap, no digits, truth/lie consistency vs actual move. **Cx S, Risk L.**

**4.10 · Ollama provider (optional, config-gated)**
Goal: `infra/llm_provider.py`: `OllamaProvider(model, url=localhost:11434, every_n_steps)` implementing `TalkProvider`; on non-LLM turns → delegate to template; hard word-cap post-filter; timeout `[llm].step_deadline_seconds`; ALL calls through `ApiGatekeeper.execute`.
Why: edge e4 — richer psychological texture at 0 API cost; also demonstrates the L08 skill (grading narrative).
Files: infra/llm_provider.py. Deps: 4.9 (interface), gatekeeper. Accept: with Ollama absent, provider falls back to template without crashing (connection-refused path tested via mock); with mock HTTP, produces capped hint. Risks: latency blowing the turn deadline — deadline enforced with fallback-to-template; never let it touch the move. Edges: model returns >15 words (truncate at word boundary), empty reply (template fallback). Tests: mocked-transport tests only; live Ollama = manual. **Cx M, Risk L (well-fenced).**

**4.11 · Stage-4 integration + eval**
Goal: extend `cli.py selftest`: full local match with scent-driven belief (no perfect-info shortcut), hints via template provider, lie-detection on, barrier traps on; print capture step + trust trace; add `--games N --seed S`. Record capture-rate + avg-steps as the Stage-4 empirical result in RESEARCH-REPORT draft.
Why: milestone gate must be observed behavior; also produces the numbers for the report (grading artifact).
Deps: 4.3–4.9 (4.10 optional). Accept: scent-only cop (no perfect info) captures blind thief ≥ 60% within 35 steps over 20 seeded games; regression: full pytest green. Tests: this IS the test (seeded integration test `tests/test_stage4_integration.py`, marked slow). **Cx M, Risk M.**

### Stage 5 — Cloud + tunnel

**5.1 · Async transport + live localhost gate**
Goal: rewrite `OpponentLink` async (`async with Client`, `await call_tool`) with a sync wrapper (`anyio.run`/`asyncio.run`) for the runtime; verify `build_server` run() against installed fastmcp (adjust transport string if needed); add `scripts/run_local_pair.py` launching police+thief configs on ports 8801/8802; document the two-terminal procedure in README.
Why: D4 certain live failure; Stage-2 live gate finally earned.
Files: infra/mcp_client.py, mcp_server.py, scripts/run_local_pair.py. Deps: H3 (CLI), `uv sync` (user machine). Accept (manual, user-run): two terminals exchange ≥ 3 sealed turns on localhost; automated: async wrapper unit-tested with a mocked client. Risks: fastmcp API surface differences by version — pin version in pyproject when verified. **Cx M, Risk M (external dep).**

**5.2 · Config loader**
Goal: `shared/config.py`: load game.json + game.toml (tomllib), **JSON overlay wins on shared keys** (book: shared terms may never be weakened privately); dotted `get("rules.barriers_max")` mapping onto the real key layout; `canonical_sha256(shared_terms)` (sorted-keys separators-(",",":") — same canonicalization as crypto); validation: minimums respected, required keys present.
Why: D10; byte-identical contract enforcement (Rule 11) hinges on this hash; every later stage reads config through it.
Files: shared/config.py. Deps: none. Accept: loads the shipped files; overlay precedence tested; hash stable across key order permutations; a lowered minimum (grid_size 5) raises. Edges: missing toml (defaults), extra unknown keys (preserved — opponents may extend legally). Tests: `tests/test_config.py`. **Cx M, Risk L.**

**5.3 · Handshake & negotiation**
Goal: `peer/handshake.py` + `domain/negotiation.py`: MCP tool `handshake(payload)` exchanging {config_sha256, group_id, role, code_version}; mismatch → refuse to play (book: refuse on any config mismatch); agree who moves first (deterministic: thief first — document; confirm vs reference intel I3); produce game_id/game_uid (`domain/game_ids.py`: naming per Table 20 — `declaration_<game_id>.json` etc.).
Why: the league entrypoint; prevents the #1 disqualifier (config asymmetry) before any move.
Files: peer/handshake.py, domain/negotiation.py, domain/game_ids.py, infra/mcp_server.py (register tool). Deps: 5.1, 5.2. Accept: two local peers with identical config shake hands and agree order; a one-byte config difference → refusal path with clear error. Edges: opponent omits fields (tolerant parse, refuse politely); duplicate handshake (idempotent). Tests: `tests/test_handshake.py` with fake transport. **Cx M, Risk M (interop — see I3).**

**5.4 · Public tunnel (user-operated)**
Goal: docs + config: ngrok/Localtonet procedure, `opponent_url` exchange checklist, firewall notes; `cli peer --public` printing the tunnel checklist.
Why: Rule 10; league requirement. Mostly ops, not code.
Deps: 5.1. Accept (manual): cross-machine match over public URLs. **Cx S, Risk M (network env).**

**5.5 · Deadline tracker + watchdog**
Goal: `peer/` timers: every outgoing request stamped, `[response_timeout_sec]=30` expiry → one retry (`[max_retries]`, `[retry_backoff_sec]` from signed gatekeeper block) → TECHNICAL_LOSS transition; background watchdog thread: no heartbeat for `[watchdog_timeout_sec]`=60 → persist state JSON + controlled shutdown (Rules 6–7).
Why: the reliability rules; also protects league games from hanging opponents (real risk).
Files: peer/runtime.py or peer/watchdog.py, shared/config.py keys. Deps: 5.1. Accept: simulated silent opponent (fake transport never responds) → retry → TECHNICAL_LOSS within budget, state file written; watchdog fires on frozen loop (test with tiny timeout). Edges: response arrives during retry (idempotent accept); shutdown mid-write (atomic write via tmp+rename). Tests: `tests/test_reliability.py` with fake clock where possible. **Cx L, Risk M (threads).**

### Stage 6 — Security (⚠ gated on Intel I1)

**6.1 · Sealing module**
Goal: `peer/sealing.py`: `sealed_step_record(state, decision, usage, tokens_total) -> record` building the full MOVE_PAYLOAD (artifact_schemas.MOVE_PAYLOAD_FIELDS) + step-0 variant; canonical-JSON serialize payload+nonce → SHA-256 → `record = {payload, commit, nonce}` (nonce withheld from wire until audit); refactor runtime to use it (removes D7); `crypto.py` stays as the primitive.
Why: interop-critical — other teams' audits must recompute our hashes. **Do not implement until Intel I1 (reference sealing.py verbatim) answers the exact preimage; if intel unavailable by 07-25, implement per artifact_schemas + canonical JSON and negotiate the scheme explicitly in the handshake (document in declaration).**
Files: peer/sealing.py, peer/runtime.py, domain/crypto.py (unchanged). Deps: I1 (or fallback decision), 4.x record contents. Accept: verify(reveal) round-trip on every field; golden-file test vs a reference sample-run record if I1 provides one. Risks: HIGH interop. Tests: `tests/test_sealing.py` incl. tamper-one-byte → mismatch. **Cx M, Risk H.**

**6.2 · Step-0 declaration**
Goal: `shared/sysinfo.py` (platform/os/psutil-free hardware probe: os, cpu_type, cpu_cores, cpu_freq_mhz, ram_gb, gpu via `wmic`/`nvidia-smi` best-effort, "not exposed" fallbacks per reference sample), `shared/version.py` (CODE_VERSION), git commit hash (`git rev-parse HEAD`), assemble STEP0_PAYLOAD, seal via 6.1, exchange in handshake (Rule 24, 53).
Files: shared/sysinfo.py, version.py, peer/handshake.py. Deps: 6.1, 5.3. Accept: payload matches STEP0_PAYLOAD_FIELDS; commit hash present; graceful "unknown" on exotic hardware. Tests: field completeness, no crash without GPU. **Cx M, Risk L.**

**6.3 · Reveal + verify loop (make the phase machine honest)**
Goal: implement the real exchange: commit → opponent ack → reveal {payload minus nonce} → verify legality of opponent's revealed move (orthogonal step from their last revealed position claim, barrier legality incl. thief-may-not-barrier, quota) → apply opponent's declared barriers to MY board copy → VERIFYING passes/fails → next turn. Removes W5.
Why: the trust core; also where the two boards converge (barrier declarations, Rule 15).
Files: peer/runtime.py, peer/turn_handler.py (new, receive side), protocol.py (reveal message type). Deps: 6.1, 5.1. Accept: two local peers complete a full honest game; injected illegal reveal → opponent flagged, TECHNICAL_LOSS path; boards converge (equal barrier sets at game end). Edges: reveal before ack (queue), duplicate reveal (idempotent), reveal that doesn't hash to commit (tamper → immediate loss). Tests: `tests/test_reveal_loop.py` fake-transport pair harness. **Cx L, Risk H (protocol correctness).**

**6.4 · Capture-claim protocol**
Goal: police MOVE carries landing-cell claim (already sent); thief's `on_opponent_turn` must answer truthfully whether its position == claimed cell (cryptographic truth duty, book Ch.3 iron rule); `claim_response` sealed into thief's next record; police verifies response at audit.
Files: peer/turn_handler.py, sealing payload (`verdict`/claim fields). Deps: 6.3. Accept: true claim → capture ends game with agreed result; false claim → honest "no" continues; lying thief detected in audit test. Tests: three-scenario suite. **Cx M, Risk M.**

**6.5 · Final mutual audit**
Goal: end-of-game exchange: full log + ALL nonces; each side recomputes every record hash, verifies move-legality chain and claim honesty → `audit = {passed, checked, failures[]}`; `consensus_signature(records)` = sha256 over both logs' canonical concat → `mutual_agreement` blocks (log + result artifacts).
Files: peer/summary.py (new), report wiring. Deps: 6.3, 6.1. Accept: honest game → passed=True both sides; single tampered historical record → failure identifies exact step; TAMPERED → game voided (Rule 19). Tests: `tests/test_audit.py` incl. the tamper case. **Cx M, Risk M.**

**6.6 · Tamper & technical-loss test sweep**
Goal: adversarial regression pack: nonce reuse, commit/reveal mismatch, quota breach, diagonal reveal, silent opponent, false capture claim, false game-count declaration shape — each lands in the correct sanction path.
Why: Rules 17–22 sanctions are the disqualification surface; prove we're on the right side of each.
Deps: 6.3–6.5. Accept: every case → documented outcome, no hangs. **Cx M, Risk L.**

### Stage 7 — Reporting, GUI, submission

**7.1 · Report writer (4 artifacts)**
Goal: `report/report_writer.py` (+ artifacts.py builders per artifact_schemas verbatim keys): declaration, config (shared_terms spread + config_sha256), log (summary+records+mutual_agreement), result (sub_games aggregate + tokens_total_series + tie rule per Ch.9: equal cumulative → `tie_score` each); filenames via game_ids (Table 20).
Deps: 6.5, 5.2, game_ids (5.3), sysinfo (6.2). Accept: golden-file diff vs docs sample-run structure (keys exactly match artifact_schemas lists — write a schema-conformance test iterating the field lists). Tests: `tests/test_reports.py`. **Cx M, Risk L (schemas pinned).**

**7.2 · Gmail sender**
Goal: `infra/email_sender.py`: appendix-א flow (`InstalledAppFlow` first run → token.json; `gmail.send` scope ONLY — Rule 30), MIME + attached JSON files, `mode=draft|send` from toml, all sends through `ApiGatekeeper.execute`; harden gatekeeper (D8): remove busy-wait (condition/deque), add call log + simple DOS counter (≥ N calls in window → lock, Rule 29).
Deps: 7.1, 5.2. Accept: mocked googleapiclient send path tested; draft mode produces .eml/draft locally without network; secrets never in repo (test asserts .gitignore covers credentials.json/token.json). Risks: OAuth first-run is user-interactive — document; NEVER auto-send during dev (draft default). **Cx M, Risk M (external).**

**7.3 · Live GUI**
Goal: `gui/window.py` + `board_view.py`: Tkinter window per peer — own position, own barriers, **belief heatmap** (red intensity = P(opponent)), turn banner (green YOUR TURN / gray LOCKED wired to phase machine), hint ticker. Local truth ONLY (Rules 8–9): no opponent position anywhere.
Deps: 4.4 (belief), 6.3 (turn events). Accept: manual run shows live heatmap evolving; automated: renderer unit-tested headless (draw to canvas-mock / Pillow image compare of the color mapping). Risks: Tk on Windows fine; keep GUI optional (`--gui` flag) so headless league runs work. **Cx L, Risk M.**

**7.4 · Replay viewer**
Goal: `gui/replay.py` + `replay_data.py`: load log JSON, step fwd/back, re-verify each record via sealing.verify → green "Verified OK" stamp / red "TAMPERED" banner (Rule 20; disqualification on any tamper).
Deps: 7.1 (log format), 6.1 (verify). Accept: sample honest log → all green + final OK; tampered fixture → red at exact step. **Cx M, Risk L.**

**7.5 · Screenshot generator**
Goal: `scripts/render_docs_images.py` equivalent (Pillow): from a saved log, render (a) belief-heatmap progression figure, (b) annotated GUI frame, (c) replay Verified-OK frame → `docs/img/` for both READMEs (mandatory submission screenshots, reproducible not hand-captured).
Deps: 7.3/7.4 renderers. Accept: images generated deterministically from a fixture log. **Cx M, Risk L.**

**7.6 · Series runner**
Goal: `sdk/series.py` + `sdk.py` real: play `[num_games]` sub-games (6 full series), aggregate scores, tie rule, per-sub-game artifacts + final result; `cli series` command.
Deps: 6.x, 7.1. Accept: local 2-peer 2-sub-game series produces all artifacts + correct aggregate. **Cx M, Risk M.**

**7.7 · Documentation completion**
Goal: PRD-4..7 (retro-written per stage, honest), RESEARCH-REPORT-Performance-Analysis.md (token/cost table per provider incl. measured template=0 + Ollama, RPM math vs gatekeeper config, capture-rate numbers from 4.11/6.x evals, bottleneck analysis), README 6-part academic report fully written (Dec-POMDP §, orchestration dilemmas §, strategies+why incl. the open-board-evasion finding and diffusion-model deviation, screenshots, cross-link), STRATEGY.md (brain extension guide), delete unused stubs.
Deps: everything (rolling — draft alongside stages, finalize here). Accept: every README claim executable; all Rule-42/50 items present. **Cx L, Risk L.**

**7.8 · Two-repo split + tag + submission mechanics**
Goal: create cop repo + thief repo (same engine, role-specific config/README framing — decide: identical code both repos, differing config/ and README header; simplest compliant reading of Rule 49), cross-links, push, `git tag -a v1.0-submission -m ...` both, secrets-history scan (`git log -p | grep`-style or trufflehog-lite manual), Moodle PDF form (`orcai-mj` code), per-member submission.
Deps: 7.7, league games done. Accept: submission-gates checklist (Operation-100 board) 10/10. **Cx M, Risk L (mechanics) — H (calendar).**

### League ops (user-driven, not Opus)
**L1** Find opponent teams (start NOW — critical path). **L2** Warm-up matches (Rule 52) ≥ 1 week before deadline. **L3** ≥2 counted games vs different teams + both-sides reports. **L4** Buffer 08/10–08/12: verify only.

---

## 8. Execution Order (recommended) & rationale

```
Session 1:  H1→H2→H3→H4          (foundation honest; everything after is committed, testable, runnable)
Session 2:  4.1→4.2→4.3           (scent core — pure, formula pinned here)
Session 3:  4.5→4.4               (fix diffusion BEFORE fusion lands → no rework of fusion tests)
Session 4:  4.8                   (barrier traps — biggest league lever, only needs belief argmax; do EARLY so eval data accumulates)
Session 5:  4.6→4.7               (hints + lie detection)
Session 6:  4.9 (+4.10 if time)→4.11  (talk + integration eval → Stage-4 gate + report numbers)
Session 7:  5.2→5.1               (config loader first — handshake/live wiring reads it once, not twice)
Session 8:  5.3→5.5  [user: 5.4 tunnel test]
Session 9+: 6.1 (needs I1 — request intel NOW)→6.3→6.4→6.5→6.2→6.6
Then:       7.1→7.2, 7.3→7.4→7.5, 7.6, 7.7, 7.8  (7.3/7.4 can interleave with league warm-ups)
```
Why this order: (1) hygiene first — every later commit is history the grader reads; (2) 4.8 pulled
ahead of hints because capture capability compounds (all later evals measure real strength) while
hints refine margins; (3) 4.5 before 4.4 avoids rewriting fusion tests; (4) 5.2 before 5.1/5.3
because both consume the loader; (5) 6.1 gated on intel — request it in parallel now so it never
blocks; (6) GUI late but before league (screenshots need real logs). Rework minimized by: sealing
owns records from 6.1 (runtime's ad-hoc records are throwaway by design — don't polish them);
emission formula isolated in one function; provider interface fixed at 4.9 so 4.10 is additive.

---

## 9. Testing Strategy (per remaining area — specify only)

- **Unit:** every new pure function (emission values, decay curve, hint lexicon, trap value,
  canonical hash stability, config overlay precedence). Table-driven where possible.
- **Integration:** fake-transport peer pair (test_reveal_loop harness — build once at 6.3, reuse
  for 6.4/6.5/7.6); seeded selfplay eval (4.11) as slow-marked tests.
- **Edge-case:** board edges (corner scent clipping, corner traps), empty/max scent, quota
  exhaustion, walled-in states, empty/oversized/Hebrew hints, stale belief argmax on barrier.
- **Failure:** silent opponent (timeout→retry→TECHNICAL_LOSS), malformed messages (every protocol
  from_dict given fuzzed dicts must not crash), Ollama down (template fallback), Gmail 429 path
  (gatekeeper blocks, no send), OAuth files missing (clear error, no crash).
- **Adversarial/regression (6.6):** tamper matrix — one test per Rule 17–22 sanction; golden
  sample-run record (if I1 yields one) pinned forever.
- **Conformance:** artifact keys == artifact_schemas lists (iterate the lists, not hand-written
  assertions); config minimums enforcement.
- **Invariant/property:** no-self-wall (cop always retains a legal move), belief mass ≈ 1 after
  every operation, scent τ ∈ [0, 0.9], phase machine never leaves the legal table (random walk).
- **Manual gates (user):** live localhost pair (5.1), tunnel match (5.4), OAuth first-run (7.2),
  GUI visual (7.3), full dress-rehearsal series vs ourselves before first league match.

---

## 10. Architecture Review — sufficient for 4–7?

**Yes, with three planned (not immediate) adjustments — no refactor needed before Stage 4:**
1. **Receive-side runtime (6.3):** run_turn is a synchronous straight line; the real loop is
   event-driven (messages arrive via server callback). Plan: `turn_handler.py` owns the receive
   path; runtime becomes a state holder + two entry points (`run_turn`, `on_opponent_turn`).
   Deferring this is safe because Stage 4 only adds pure domain logic.
2. **Record ownership (6.1):** sealing.py will own record construction; runtime's current dict is
   acknowledged scaffolding. Don't extend it — extend sealing.
3. **Config plumbing (5.2):** today config is a bare dict param; the loader lands before any
   module count > 3 reads it. No migration cost if done at Session 7 as ordered.
The domain/infra/peer/strategy layering, lazy fastmcp imports, and config-driven tests are sound
and match both the book's architecture chapter and the reference. No coupling smells beyond D7/D10.

---

## 11. Risk Analysis

| Risk | Sev | Likelihood | Mitigation |
|---|---|---|---|
| **Sealing preimage interop** with other teams (audits can't verify each other) | H | M | Intel I1 now; else negotiate scheme in handshake + declaration; golden-record test |
| **No opponents scheduled** — can't play the ≥2 counted games | H (grade gate) | M | L1 this week; the deadline risk is calendar, not code |
| **fastmcp live behavior** (async client, transport strings, version drift) | M | H (bug is certain, fix is easy) | 5.1 early; pin version |
| **Emission-formula mismatch** vs reference smell.py | M | M | Derived Gaussian matches book figure exactly; isolated function; Intel I2 |
| **Opponent hint language/format variance** breaks lie-detection value | M | M | Lexicon incl. Hebrew; trust EMA degrades gracefully to scent-only play |
| **Turn-1/who-first ambiguity** vs other implementations | M | M | Intel I3; handshake makes it explicit |
| **Windows/Tkinter/GUI in league runs** | L | L | GUI optional flag; headless league mode |
| **Token budget** (200k/series) if cloud LLM used | L | L | Template default = 0 tokens; Ollama = 0 API tokens |
| **State consistency** (board convergence via declared barriers) | M | M | 6.3 convergence test; audit catches divergence |
| **Grading pitfalls:** broken bare pytest, false README commands, no git history/tag, missing PRDs 4–7, screenshots, self-grade scope | H | — | H1–H3 now; 7.7/7.8 checklist; Operation-100 board |

### Pending intel (ask NotebookLM #2 — request NOW, blocks only 6.1/5.3)
- **I1 (HIGH):** `peer/sealing.py` verbatim — `sealed_step_record`, exact preimage serialization, nonce placement; plus one full record from the sample-run log.
- **I2 (MED):** `domain/smell.py` verbatim — emission falloff + deposit/decay order + clamping.
- **I3 (MED):** `peer/handshake.py` + `control_link.py` — who initiates, who moves first, handshake payload fields.

---

## 12. Living TODO — master checklist (source of truth)

Protocol hardening (pre-league): ✅ P0-1 inbound envelope validation + strike counter + evidence trail `f40a0ce` ✅ P0-2 signed response-window enforcement + fault-attributed technical-loss snapshots `1b523f3`
Strategy hardening (pre-league): ✅ P1-2 truth-washing resistance + scent-confined reward `9db97be` ✅ P1-1 barrier depth/reserve guards `8715cb1` ✅ P1-3 zero-information default hinting `6890e88` — 182 tests
Hygiene: ✅ H1 git init ✅ H2 pytest cfg ✅ H3 CLI entry (—seed deferred to 4.11) ✅ H4 barrier rules — 30 tests, 4 commits (0c96942..b86c508)
Stage 4: ✅ 4.1 emission ✅ 4.2 decay ✅ 4.3 wiring (b9a31c2, cd183d2, 9c067d1 — TDD, 40 tests) ✅ 4.4 fusion (on_opponent_turn; clamp-saturation discovery: one-step trails are head-ambiguous → argmax-within-1 acceptance) ✅ 4.5 diffusion fix (von-Neumann+stay, barrier-aware) — TDD, 50 tests ✅ 4.6 hints ✅ 4.7 lie detection (domain/hints.py + runtime trust EMA — 70 tests) ✅ 4.8 barrier traps (TrapperPolice forced-capture search — 6/6 starts, steps 9–15; 56 tests) ✅ 4.9 template talk ⨯ 4.10 Ollama (SKIPPED by decision — template is league default, 0 tokens) ✅ 4.11 integration eval (83% scent-only capture, avg 18.3 steps, 79 tests) — **STAGE 4 COMPLETE**
Stage 5: ✅ 5.1 async fix `7dfc829` + **LIVE GATE PASSED** (fastmcp 3.4.5, localhost pair, handshake verified, 5 sealed exchanges, trust EMA live — autonomous run, cycle 7) ✅ 5.2 config loader `5059b16` ✅ 5.3 handshake+runner `390677d` (104 tests; peer CLI live; thief-first structural) □ 5.4 tunnel (user) ✅ 5.5 deadline+watchdog `6c4694a` (108 tests)
Stage 6: ✅ **COMPLETE** — ⨯ I1 intel (closed unobtainable; we declare `canonical-json-v1` at handshake) ✅ 6.1 sealing ✅ 6.2 step-0 ✅ 6.3 consensus termination `8388135` ✅ 6.4 claims ✅ 6.5 mutual audit + P0-3 ✅ 6.6 adversarial sweep `d32341e` — 251 tests
Stage 7: ✅ 7.1 reports `4066131` ✅ 7.2 gmail `5a2dfe9`+`d90fa58` (draft default, DOS lock, series --email; live OAuth = user gate — 145 tests) ✅ 7.3 GUI `5172ada` (viewmodel+Tk, --gui) ✅ 7.4 replay engine+CLI `dbf0b99` ✅ 7.5 SVG artifacts `70c7668` (docs/img generated from real match, README §5 embedded — 129 tests) □ 7.5 screenshots ✅ 7.6 series `a5313a5` (134 tests; CLI series cmd; self-audited artifacts) ✅ 7.7 docs `1d45b75`+`f00f9c4` (RESEARCH-REPORT, README §1-4, PRD-4..7, STRATEGY.md; stub cleanup logged as 7.7b follow-up) ✅ 7.7b stub cleanup `602817d` ✅ 7.8 two-repo builder `6d5e0c3` (148 tests; push = user-run with real URLs)
League:  □ L1 opponents found □ L2 warm-ups □ L3 ≥2 counted games □ L4 buffer week clean
Done previously: ✅ Stage 1 (mod H4) ✅ Stage 2 automated ✅ Stage 3 ✅ schemas pinned ✅ belief/gatekeeper/rate-limiter cores

---

## 13. Next Task for Opus — **H-batch (H1→H2→H3→H4), one session**

**Objective:** make the foundation honest: version control begun, bare `pytest` green, CLI real,
two barrier-rule gaps closed. No feature work.

**Exact steps & files:**
1. H1: `git init` in `final-project/`; verify `git status` shows no `__pycache__`/`.pytest_cache`
   (add to .gitignore if tracked — they are currently on disk); commit `chore: scaffold — stages 1-3 (23 tests green)`.
2. H2: pyproject `[tool.pytest.ini_options]` add `pythonpath = ["src"]`. Run bare `pytest -q` → 23 pass.
3. H3: create `src/police_thief/cli.py` (argparse: `peer --role {police,thief} [--config]`,
   `replay --log`, `selftest [--steps N] [--seed S]`) and `__main__.py` calling `cli.main()`.
   `peer`/`replay` print "not wired until Stage 5/7" and exit 2. `selftest` runs the Stage-3 style
   local sim (two brains, perfect-info belief stand-in, capture/step printout, "DEV TOOL — not a
   league mode" banner). No fastmcp import anywhere in cli.py.
4. H4: `own_state.apply_move(BARRIER, None, barriers_max)` → place on own cell (quota + not-already-barrier
   checks); `PeerRuntime.run_turn` converts a thief BARRIER decision to HOLD.
5. Tests: add `tests/test_cli.py` (selftest exit 0; peer exit 2 w/o fastmcp) and extend
   `tests/test_board.py` (+ own-cell placement, quota on own-cell, thief-barrier→HOLD via runtime).
6. Update README run section to match real CLI. Commit each of H2/H3/H4 separately.

**Pitfalls:** don't let `selftest` import infra/; keep Windows paths out of code; ensure
`python -m police_thief` works from repo root with H2's pythonpath (it won't — `-m` needs the
package installed or `PYTHONPATH`; acceptable: document `uv run police-thief` as canonical and
test via pytest imports instead of subprocess).

**Definition of done:** bare `pytest -q` ≥ 27 passed, 0 failed; `git log` shows 4 clean commits;
`selftest` prints a full game; README commands are true.

---
*Maintained by the Architect. Update the checklist and section 2 after every merged task.*
