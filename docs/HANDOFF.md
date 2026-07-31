# HANDOFF — Complete Technical Engineering Report

> **Purpose:** enable an AI model (or engineer) that has never seen this project to continue it
> without asking basic questions. Everything below is verified against the repository, git
> history, test runs, and on-disk documents as of commit `51f747e`. Claims that cannot be
> verified from those sources are explicitly marked **UNKNOWN**.
>
> **Companion documents (read in this order):**
> 1. This file — history, state, verification status.
> 2. `docs/ARCHITECT-PLAN.md` — the living roadmap: 33 atomic remaining tasks with full specs,
>    dependency graph, testing strategy, living TODO checklist. **That file is the task source
>    of truth; this file is the state source of truth.**
> 3. `docs/REFERENCE-NOTES.md` — verbatim facts extracted from the lecturer's reference
>    implementation (via NotebookLM), incl. exact brain interface and turn-loop shape.

---

## 1. Project Overview

### What this is
Final capstone ("פרויקט גמר") for Dr. Yoram Segal's **"Orchestration of AI Agents"** course
(University of Haifa). Course id prefix used in past submissions: `orcai-mj`.

**The system:** a fully distributed pursuit game — **Police (cop) vs Thief** — on a 7×7 discrete
grid. Two completely independent peer processes (potentially on different machines, different
teams' code) play against each other with **no central server, no referee, no shared state**.
Each peer runs its own FastMCP server (exposing tools the opponent calls), its own MCP client,
its own config, GUI, and log. Game integrity rests on **per-step SHA-256 commit-reveal** and a
**mutual post-game log audit** — cheating is made cryptographically detectable rather than
prevented by an authority.

### Authoritative specification (in priority order on any conflict)
1. **Binding parameters table** — appendix ו of the rules book.
2. **The rules book**: `police_thief_p2p.pdf` v3.0.0, 160 pp., Hebrew — located OUTSIDE this
   repo at `c:\ai orc\final oroject\police_thief_p2p.pdf` (verified on disk, 1,333,362 bytes).
3. Course assignment brief (Moodle screenshots, same folder).
4. Lecturer's public reference repo: `github.com/rmisegal/Game-P2P-Cop-Chase` (educational
   starting point; solutions must independently satisfy the spec).
5. `docs/ARCHITECT-PLAN.md` (this project's plan).

### Game rules (core, from the book — full mapping in §8)
- 7×7 grid, (row, col), origin top-left, 0-indexed. Thief starts [3,3], cop [0,0].
- Moves: N/S/E/W or STAY. **No diagonals.**
- Cop only: on a turn it forgoes movement, may place an irreversible barrier on **its own cell
  or one of the 4 orthogonal neighbors**; quota 14; impassable to both players; every placement
  must be truthfully declared.
- Capture = same cell | barrier placed on thief's cell | thief has no legal move.
  Thief wins by surviving 35 valid steps. Scoring: capture 20/5, survival 5/10, tie 2/2,
  technical loss 0/0 (cop/thief).
- Partial observability: nobody sees the opponent. Each agent reads the opponent's **decaying
  scent field** (center 0.9, decay 0.10/turn, 5×5 emission) + a free-text verbal hint
  (≤15 words) **that may be a lie**. Each side maintains a Bayesian belief grid.
- Every move: commit (SHA-256 hash sent) → acknowledge → reveal (move+hint; nonce withheld)
  → post-game audit (all nonces revealed, every record re-verified). Tamper = void game.
- League: ≥2 counted games vs different teams to qualify; grade band 75 (last) → 100 (first).

### Technology
- **Language:** Python ≥ 3.11 (tested on 3.13 per bytecode in `__pycache__`).
- **Packaging:** `uv` + hatchling; `pyproject.toml`; console script `police-thief`.
- **Dependencies (declared, NOT yet installed/verified live):** `fastmcp>=2.0`,
  `google-api-python-client`, `google-auth-oauthlib`. Dev: `pytest`, `ruff`.
- **Core code has zero third-party imports** — fastmcp is lazy-imported inside functions so the
  entire test suite runs on a bare Python install.
- **External services (planned per spec, not yet integrated):** ngrok/Localtonet tunneling,
  Gmail API (OAuth2, `gmail.send` scope only), optional local Ollama for bluff text.

---

## 2. Development Timeline

Git history is compressed: the entire Stages 1–3 scaffold arrived as one baseline commit, then
the "H-batch" hygiene fixes as individual commits. All commits dated **2026-07-26** (author
`akariya-mohammed <makree29@gmail.com>`, co-author `Claude Fable 5` on every commit).
Development order WITHIN the scaffold commit is reconstructed from `docs/` (PRD-1..3,
ARCHITECT-PLAN §2 audit) — marked *[reconstructed]* where git cannot prove sequence.

| # | Commit | Date | What | Why | Files (adds) | Tests after |
|---|---|---|---|---|---|---|
| 1 | `0c96942` | 2026-07-26 | **Baseline scaffold: Stages 1–3** — domain core (board, own-state, rules, scoring, belief, crypto, state machine, protocol), FastMCP server/client wrappers, peer runtime skeleton, Manhattan+Bayes brains, report schemas, config defaults, docs (PRD 1–3, REFERENCE-NOTES, ARCHITECT-PLAN) | Foundation per the book's 7-layer build order (Ch. 10) | 59 files, ~1,450 LOC | 23 |
| 2 | `5e49098` | 2026-07-26 | **H2:** `pythonpath=["src"]` for pytest | Bare `pytest` previously died with 5 collection errors — a grader running it would see a broken project | pyproject.toml | 23 |
| 3 | `f4e0369` | 2026-07-26 | **H3:** CLI (`cli.py`, `__main__.py`): `peer`, `replay` (exit 2, honest stage pointers), `selftest` (local dev sim) + truthful README run section | pyproject declared entry point `police_thief.__main__:main` that didn't exist → README commands were false claims | cli.py (104), __main__.py, test_cli.py, README | 27 |
| 4 | `b86c508` | 2026-07-26 | **H4:** Barrier Law fidelity — `apply_move(BARRIER, direction=None)` = place on own cell; runtime degrades an (illegal) thief BARRIER to HOLD with warning | Book p.21 explicitly allows own-cell placement; nothing guarded the cop-only privilege | own_state.py, runtime.py, +7 tests | 30 |
| 5 | `51f747e` | 2026-07-26 | Living TODO updated: H-batch ✅ | Plan maintenance contract | ARCHITECT-PLAN.md | 30 |
| 6 | `c12bf17` | 2026-07-26 | This handoff document | Project continuity | HANDOFF.md | 30 |
| 7 | `b9a31c2` | 2026-07-26 | **Task 4.1 (TDD):** ScentGrid emission — Gaussian `0.9·exp(−3d²/8)` reproducing Book Fig-4 values ±0.01; edge clipping; clamp-at-center plateau; sparse detached snapshot | Partial-observability core; formula isolated in `emission_at()` pending reference confirmation | domain/smell.py, tests/test_smell.py | 35 |
| 8 | `cd183d2` | 2026-07-26 | **Task 4.2 (TDD):** decay `τ←(1−ρ)τ` (ρ=0.10) + prune <1e-3; half-life proven at turn 7 (Book Fig-5) | Trail must be history (~6–7 readable turns), not a live beacon | domain/smell.py, tests/test_smell.py | 39 |
| 9 | `9c067d1` | 2026-07-26 | **Task 4.3:** ScentGrid wired into PeerRuntime send path (deposit→decay→snapshot, reference order); params from signed pheromones config w/ book-default fallbacks | Turn messages now carry the real decaying trail | peer/runtime.py, tests/test_protocol.py | 40 |
| 10 | `fb70a34` | 2026-07-26 | **Task 4.5 (TDD):** belief diffusion king-step → von-Neumann+stay, barrier-aware (`diffuse(barriers=None)`); stranded mass relocates off walls; walled-in cells keep mass | No diagonal moves exist → tighter transition model, sharper posterior; deliberate documented deviation from reference (belief is private, zero interop risk) | domain/belief.py, tests/test_belief.py | 44 |
| 19 | `8388135`+`d32341e` | 2026-07-31 | **Tasks 6.3+6.6 (TDD) — STAGE 6 COMPLETE:** capture claims restricted to good faith (we were attaching one to EVERY move — Rule 22 sanction is zero score + technical loss, no appeal); `peer/claims.py` adjudicates the terminal exchange; runtime carries an outcome and stops on consensus; `peer/finish.py` performs the end-of-game reveal, runs the opponent's history through the violation matrix, delivers the owed verdict, and writes evidence; `tests/test_adversarial_sweep.py` drives every violation end to end plus the honest-opponent mirror | A refereeless game must END by agreement and be provable afterwards; two disqualification-grade bugs (false claims, undeclared barriers) were only visible in live play | peer/claims.py, peer/finish.py, peer/receive.py, peer/runtime.py, peer/runner.py, 2 test modules | 251 |
| 18 | `5e88467` | 2026-07-31 | **Task 6.2 (TDD):** `shared/sysinfo.py` best-effort machine probe (degrades, never raises; timeout-bounded GPU shell-out) + sealed step-0 declaration incl. the exact playing commit; handshake now requires `step0_commit` + matching `sealing_scheme` | Hardware/code identity must be unrevisable after the fact (Rules 24/53), and an audit whose digests we cannot recompute is theatre | shared/sysinfo.py, peer/sealing.py, domain/negotiation.py, peer/runner.py, tests/test_step_zero.py | 221 |
| 17 | `36a157e` | 2026-07-31 | **Tasks 6.4+6.5+P0-3 (TDD):** `domain/termination.py` capture/survival claims (a denial ships its own position → false denial provable); `peer/audit.py` violation matrix — digest chain, revealed move-chain legality, and scent-history audit with **structural** (default) vs **strict** modes | Post-game proof is what makes a refereeless game trustworthy; the two-mode P0-3 exists because our falloff was never confirmed against another implementation and a false accusation loses us the match | domain/termination.py, peer/audit.py, tests/test_protocol_termination.py, tests/test_scent_audit.py | 212 |
| 16 | `9db97be`+`8715cb1`+`6890e88` | 2026-07-31 | **P1 strategy hardening (TDD, pre-league):** TRUTH verdict now requires the scent **peak** inside the claim and its reward is confined to scent-backed cells (a mass-share-only verdict was truth-washable — reproduced hijacking our argmax to the wrong quadrant); hint policy extracted to `peer/hint_policy.py`; barrier spending gated by capture-line depth + a hard quota reserve (ceiling tuned empirically to 6 — the proposed 3 cost 17 points of capture rate); peers default to **silence** (a parseable hint is free localization for the opponent's own detector) and lies draw from all non-containing directions rather than the invertible opposite. **Metrics: 94 % capture vs a talkative opponent, 67 % vs a silent one, ~14 avg steps.** Published docs re-synced to the new numbers and behavior | Every one of these was a way our own algorithm could be turned against us in league play | domain/hints.py, peer/hint_policy.py, peer/runtime.py, strategy/trapping.py, strategy/trash_talk.py, sdk/localsim.py, 5 test files, 4 docs | 182 |
| 15 | `f40a0ce`+`1b523f3` | 2026-07-28 | **P0 protocol hardening (TDD, pre-league):** `TurnMessage.from_dict` validates every inbound envelope (type, required fields, role, 64-hex commit, hint type, flood ceilings) and raises named `ProtocolViolation` instead of `KeyError`; `peer/violations.py` records strikes with capped raw evidence and declares TECHNICAL_LOSS against the sender after 3; every live phase keeps a TECHNICAL_LOSS edge; the **signed** `response_timeout_sec` (30s) replaces the private 180s value as the sole waiting authority; technical-loss snapshots now carry `at_fault` + evidence; `_on_turn` has a last-resort net | A crashed peer forfeits the match, and inbound data is opponent-controlled — the receive path must be unkillable and every declaration must ship its proof | exceptions.py, domain/protocol.py, domain/state_machine.py, peer/violations.py, peer/runtime.py, peer/runner.py, tests/test_adversarial.py | 168 |
| 14 | `6b3446b`+`b0b7bea` | 2026-07-26 | **Tasks 4.9+4.11 (TDD) — STAGE 4 COMPLETE:** template trash-talk (digit-free, ≤15 words, honest-contains/lie-excludes, seeded; intent policy: honest at range, bluff under threat) + `sdk/localsim.py` loopback harness running two REAL PeerRuntimes on the full production path, no perfect-info. `Decision.bluff` intent flag; runtime verbal layer (Rule 25 kept); CLI `selftest --scent`. **METRICS (for RESEARCH-REPORT): scent-only capture 83% (15/18), avg 18.3 steps, 13 lies caught / 336 truths confirmed.** 4.10 Ollama skipped by decision (template = league default, 0 tokens) | Stage-4 gate ≥60% passed with margin; numbers grader-reproducible via CLI | strategy/trash_talk.py, sdk/localsim.py, brains.py, runtime.py, cli.py, 3 test files | 79 |
| 13 | `3f02f8c` | 2026-07-26 | **Tasks 4.6+4.7 (TDD):** `domain/hints.py` — zero-dep lexicon parser (EN+HE, extensible landmarks, contradiction→None, NO coordinates per Rule 27) + `judge_claim` vs the claimant's own scent (book Ch.4 method; thin-evidence→UNKNOWN); `runtime._weigh_hint` — trust EMA α=.3, lie→suppress ×0.1, truth→boost ×3, known-liar preemptive distrust; verdict stored for sealed record | The deception channel is the only fakeable signal — judging it against the unfakeable one is the showcase tactic | domain/hints.py, peer/runtime.py, tests/test_hints.py, tests/test_lie_detection.py | 70 |
| 12 | `4e965af` | 2026-07-26 | **Task 4.8 (TDD):** `TrapperPolice` (strategy/trapping.py) — A* forced-capture search over cop actions with deterministic opponent model (own flee heuristic); R46 pounce shortcut; interception-chase fallback; barriers spent only inside found capture lines. **Empirical: 6/6 starts captured in 9–15 steps (blind baseline: 0%).** Two failed containment-score designs (guarding pathology) documented in module docstring — honest label: NOT RL, it is the book's minimax/own-algorithm track | Capture is impossible by chase alone (grid is robber-win); this is the league-rank centerpiece | strategy/trapping.py, tests/test_strategy_traps.py | 56 |
| 11 | `258d270` | 2026-07-26 | **Task 4.4 (TDD):** receive path `PeerRuntime.on_opponent_turn` — diffuse→fuse order spy-asserted; hint stored, flows into next `decide()`; ack = `{status, acknowledged_commit}`; wire-scent parsing hardened (malformed entries dropped) | Closes the sense→believe→act loop; ack locks the opponent's commitment (Ch. 5 stage 2). **Discovery:** emission clamp re-saturates the cell behind a moving head → one-step trails are head-ambiguous by design (book's "cloud, not point"); acceptance = argmax within 1 of head; head-exact tracking needs trail > emission radius (strategy layer, 4.7/4.8) | peer/runtime.py, domain/protocol.py, tests/test_fusion.py | 50 |

**Stage order within the baseline** *[reconstructed from PRD-1..3 + plan §2]*: Stage 1 board/
rules/scoring → Stage 2 protocol/MCP/state-machine/runtime → Stage 3 heuristic brains. An
integration finding recorded in plan §3/N2: on an open board with equal speed, the blind cop
NEVER captures the blind thief (distance plateaus) → barrier traps (task 4.8) are the only
capture mechanism — this drives the roadmap's prioritization.

**Pre-git history:** UNKNOWN beyond what the docs record. No fabricated history exists — the
baseline commit honestly states it is a snapshot of already-built work.

---

## 3. AI Model Usage History

Verifiable evidence: git trailers (`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` on
all 5 commits) + role statements inside `docs/ARCHITECT-PLAN.md` (header: "maintained by the
Architect (Fable), executed by the Implementer (Opus)").

| Task | Model Used | Role | Result |
|------|------------|------|--------|
| Spec analysis (160-pp book), grade-model analysis | Claude Fable 5 *(per plan header + trailers)* | Analyst | Completed (REFERENCE-NOTES, plan §1, §8 of this doc) |
| Stages 1–3 implementation (baseline commit) | Claude Fable 5 *(sole co-author trailer on `0c96942`)*; any other model: **UNKNOWN** | Coding | Completed, 23 tests |
| Repository audit + 33-task roadmap (`ARCHITECT-PLAN.md`) | Claude Fable 5 | Architect / QA / reviewer | Completed |
| H-batch (git, pytest cfg, CLI, barrier rules) | Claude Fable 5 *(trailers on `5e49098..b86c508`)* — **note: plan §13 assigned this to Opus; git shows Fable co-authorship; no Opus evidence exists in the repo** | Coding | Completed, 30 tests |
| Reference-repo intelligence (structure, interfaces, schemas) | NotebookLM (Google), operated by the human | Research | Captured in REFERENCE-NOTES.md + artifact_schemas.py |
| Course deliverables direction, league ops, submissions | Human (`akariya-mohammed <makree29@gmail.com>`) | Owner / decisions | Ongoing |
| Claude Opus | — | Designated implementer per plan; **no repo evidence of use yet** | Not started |

---

## 4. Current Architecture

### 4.1 Folder structure (verified, commit `51f747e`)

```
final-project/                       git repo, branch main, 5 commits
├─ config/
│  ├─ game.json                      SIGNED shared contract (defaults = book's binding table)
│  └─ game.toml.example              PRIVATE per-peer template (port, opponent_url, [belief], [llm], [email])
├─ docs/                             ARCHITECT-PLAN, HANDOFF (this), REFERENCE-NOTES, PRD-1..3
├─ pyproject.toml                    uv/hatchling; police-thief = police_thief.__main__:main; pytest pythonpath=src
├─ src/police_thief/
│  ├─ cli.py  __main__.py            entry points (peer|replay|selftest)
│  ├─ constants.py exceptions.py     EMPTY stubs (0 bytes)
│  ├─ domain/                        pure logic, zero I/O — the testable core
│  │   board.py own_state.py rules.py scoring.py belief.py brains.py
│  │   crypto.py state_machine.py protocol.py
│  │   [EMPTY] smell.py negotiation.py game_ids.py
│  ├─ strategy/ heuristic.py         ManhattanBayesThief / ManhattanBayesPolice
│  │   [EMPTY] trash_talk.py
│  ├─ peer/ runtime.py               turn loop + phase machine   [EMPTY] sealing.py turn_sender.py handshake.py
│  ├─ infra/ mcp_server.py mcp_client.py   [EMPTY] email_sender.py llm_provider.py
│  ├─ shared/ rate_limiter.py gatekeeper.py [EMPTY] config.py sysinfo.py version.py
│  ├─ report/ artifact_schemas.py    verbatim JSON field lists   [EMPTY] report_writer.py
│  ├─ sdk/ sdk.py (facade stub)      [EMPTY] series.py
│  └─ gui/                           EMPTY package
└─ tests/  test_board(12) test_belief(4) test_cli(4) test_crypto(3) test_protocol(3) test_strategy(4) = 30
```

### 4.2 Key classes/functions (all verified by reading + tests)

| Module | Symbol | Contract |
|---|---|---|
| domain/board.py | `Board(grid_size, barriers)` | `legal_moves(pos) -> [(Direction, cell)]` orthogonal-only; `distance()` Manhattan; `passable()` |
| domain/own_state.py | `OwnGameState` | `apply_move(move_type, direction, barriers_max) -> bool`; **False on illegal (caller falls back to HOLD — never raises in-game)**; BARRIER: own cell (direction=None) or adjacent; quota enforced |
| domain/rules.py | `resolve(cop, thief, board, steps, survival_threshold)` | → `CAPTURE` (overlap \| barrier-on-thief \| walled-in) / `SURVIVAL` / `ONGOING` |
| domain/scoring.py | `scores_for(outcome, scoring_cfg)` | → (cop, thief) points; raises on unknown outcome |
| domain/belief.py | `BeliefGrid(size, smell_trust_weight=4.0)` | uniform prior; `diffuse()` (3×3 — see §6 assumptions); `update_from_smell({cell: τ})` posterior ∝ prior·exp(trust·τ); `penalize(cells)` — lie-detection lever; `most_likely()` |
| domain/brains.py | `BrainBase` | `decide(state, belief, opponent_hint, play_setting, barriers_max, …) -> Decision(move_type, direction, hint)`; role-specific `_pick_move(moves, state, belief)` (thief) / `_decide_move(state, belief, barriers_max)` (police) — signatures mirror the reference (REFERENCE-NOTES) |
| domain/crypto.py | `commit(state, move, intent)` / `verify(...)` | canonical JSON {state,move,intent,nonce} → SHA-256; `secrets.compare_digest`. **Primitive only — the full sealed record belongs to peer/sealing.py (not yet built)** |
| domain/state_machine.py | `GamePhaseMachine` | table-driven; WAITING_FOR_OPPONENT→COMPUTING_MOVE→COMMITTING→AWAITING_REVEAL→VERIFYING→(loop); TECHNICAL_LOSS terminal; illegal jump raises |
| domain/protocol.py | `TurnMessage` / `build_turn_message` | wire dict carries: role, **commit hash**, hint, scent (keys "r,c"), capture_claim, claim_response, win_claim — **never the move or nonce** |
| strategy/heuristic.py | `ManhattanBayesPolice/Thief` | chase = argmin distance to `belief.most_likely()`; flee = argmax (tie-break: prefer unvisited); walled-in → HOLD |
| peer/runtime.py | `PeerRuntime.run_turn(opponent_hint)` | think → (thief-BARRIER guard) → apply (HOLD fallback) → seal via crypto.commit → build+send message → phases cycle. **Receive side does not exist yet** |
| infra/mcp_server.py | `build_server(name, on_turn)` | FastMCP + `receive_move` tool → on_turn callback; **fastmcp lazy-imported** |
| infra/mcp_client.py | `OpponentLink.send_turn(dict)` | ⚠ KNOWN BUG: uses async fastmcp `Client` synchronously (see §6) |
| shared/rate_limiter.py | `RateLimiter(max_in_window)` | sliding 60 s window, `try_acquire()` refuses (caller queues) — matches reference behavior notes |
| shared/gatekeeper.py | `ApiGatekeeper.execute(call)` | rate-limit → bounded queue (busy-wait; debt D8) → retry w/ backoff |
| report/artifact_schemas.py | field-list constants | verbatim keys of the 4 output JSONs (declaration/config/log/result) + the 2 sealed-payload shapes (step-0 system_spec, move) |
| cli.py | `main(argv) -> int` | `selftest` runs; `peer`/`replay` exit 2 with stage pointers |

### 4.3 Data flow / turn loop (current — send side only)

```
opponent hint (str)          config (plain dict today)
        │                          │
        ▼                          ▼
PeerRuntime.run_turn ── phases: WAITING→COMPUTING
        │ brain.decide(state, belief, hint, …)            [pure Python decision — LLM never moves]
        │ thief-BARRIER? → degrade HOLD
        │ state.apply_move(…) ── False? → HOLD            [never stall]
        ├─ phases: →COMMITTING
        │ crypto.commit(state_str, move_str, intent) → (h_commit, nonce)
        │ records.append({commit, nonce, move, state, intent, hint})   [ad-hoc; sealing.py will own this]
        ├─ phases: →AWAITING_REVEAL
        │ build_turn_message(role, hint, my_scent, h_commit, capture_claim)
        │      capture_claim = own cell on every police MOVE (implicit landing-cell claim)
        │ transport.send_turn(message.to_dict())
        └─ phases: →VERIFYING→WAITING     [★ FAKE today: no reveal is received/verified — Stage 6]
```

**Receive side (target, per plan 4.4/6.3 — NOT built):** `on_opponent_turn(msg)`:
belief.diffuse → belief.update_from_smell(msg.scent) → store hint → (Stage 6) verify reveals,
apply declared barriers to local board, answer capture claims truthfully.

**AI decision flow:** belief argmax is the single target abstraction; brains never see the
opponent, only `BeliefGrid`. Scent does not exist yet (`my_scent` is an empty dict placeholder;
`domain/smell.py` is empty — Stage 4 tasks 4.1–4.3).

**State management:** each peer owns `OwnGameState` (position/visited/barriers) + `BeliefGrid` +
phase machine + records list, all inside `PeerRuntime`. No global state. `SimulationSdk`
(sdk/sdk.py) is the designated single per-peer facade (Rule 3) — currently a stub. There is
deliberately **no cross-peer orchestrator** (forbidden by spec).

---

## 5. Completed Features

**F1 — Board & movement physics.** Purpose: the shared physical contract. Implementation:
orthogonal deltas dict, bounds+barrier passability, legal-move enumeration, Manhattan distance.
Files: domain/board.py. Tests: corner=2 moves, barrier blocks, no-diagonal-by-construction,
distance via strategy tests. Status: ✅. Confidence: **high**. Hidden issues: none known.

**F2 — Local state + move application.** apply_move contract (False=illegal, HOLD fallback
upstream), barrier quota, own-cell + adjacent placement, irreversibility. Files: own_state.py.
Tests: 5 direct. Status: ✅. Confidence: **high**. Hidden issues: `barriers` property aliases the
shared `Board.barriers` set — two `OwnGameState`s sharing one Board share barriers (fine for dev
sim, must NOT be done for real peers; see §6 assumptions).

**F3 — Win conditions + scoring.** All three capture modes incl. book rules 46/47; scoring table
from signed config. Files: rules.py, scoring.py. Tests: 5. Status: ✅. Confidence: **high**.
Hidden issues: `resolve()` checks barrier-on-thief via membership — if the thief legally stands
on a cell BEFORE a barrier existed there, semantics are correct (barrier can only appear via cop
placement → capture at placement moment); no timestamping needed.

**F4 — Bayesian belief grid.** Prior/diffuse/scent-fusion/penalize/argmax; private
smell_trust_weight=4.0 knob documented in game.toml.example. Files: belief.py. Tests: 4 + used
throughout strategy tests. Status: ✅. Confidence: **medium-high**. Hidden issues: `diffuse()`
uses a 3×3 (king) neighborhood while the game has no diagonal moves — deliberate reference
parity, flagged for change in task 4.5; barrier cells are not excluded from diffusion yet.

**F5 — Commit-reveal cryptographic primitive.** Canonical-JSON SHA-256 commit/verify with
nonce, constant-time compare. Files: crypto.py. Tests: 3 (roundtrip, tamper, + used in runtime
test). Status: ✅ as a primitive. Confidence: **high for the primitive; LOW for interop** — the
full sealed record (reference seals step/position/hint/verdict/prompt_discussion/model/tokens)
is NOT implemented; other teams' audits may hash a richer payload (plan task 6.1 + Intel I1).

**F6 — Game phase machine.** Table-driven legal transitions, terminal TECHNICAL_LOSS, loud
failure on illegal jumps. Files: state_machine.py. Tests: 2 (+cycle in runtime test). Status:
✅. Confidence: **high**. Hidden issues: VERIFYING today passes without any verification input
(honest skeleton; must not be mistaken for implemented security).

**F7 — Turn wire protocol.** TurnMessage to_dict/from_dict, scent key encoding, commit+hint
only. Files: protocol.py. Tests: roundtrip. Status: ✅. Confidence: **medium-high**. Hidden
issues: field-name interop with other teams' implementations is unverified (they will likely
derive from the reference; our names came from reference call-sites per REFERENCE-NOTES —
Intel I3 pending).

**F8 — Peer runtime (send side).** Full think→seal→send with HOLD fallback + thief-barrier
guard. Files: peer/runtime.py. Tests: 2 integration-style with fake brain/transport. Status: ✅
skeleton. Confidence: **medium**. Hidden issues: synchronous straight-line flow will be
restructured when the receive side lands (planned, task 6.3); records dict is scaffolding.

**F9 — Heuristic brains.** Chase/flee on belief argmax; deterministic tie-breaks; walled-in →
HOLD. Files: strategy/heuristic.py. Tests: 4 (incl. shortest-path optimality proof). Status: ✅
for "blind" scope. Confidence: **high** within scope. Hidden issues: cop cannot capture without
barrier play (proven empirically — see selftest); deterministic = predictable to a modeling
opponent.

**F10 — MCP server/client wrappers.** build_server + OpponentLink, lazy imports. Files: infra/.
Tests: none live (lazy import verified by suite running without fastmcp). Status: ◐ written,
**live-unproven**. Confidence: **low**. Hidden issues: client is sync-over-async → certain
runtime failure (§6 known bugs); server transport string unverified against installed fastmcp.

**F11 — Rate limiter + gatekeeper.** Sliding window + guarded execute with queue/retry. Files:
shared/. Tests: none direct (⚠). Status: ◐. Confidence: **medium**. Hidden issues: busy-wait
loop; no call logging; no DOS anomaly detector yet (plan 7.2).

**F12 — Report schemas.** Verbatim field lists of all 4 artifacts + 2 payload shapes from the
reference sample run. Files: report/artifact_schemas.py. Tests: none (constants). Status: ✅ as
data. Confidence: **high** (copied from reference sample). Hidden issues: none — but builders
don't exist yet.

**F13 — CLI + selftest.** peer/replay honest stubs; selftest = local dev sim reading signed
config. Files: cli.py, __main__.py. Tests: 4. Status: ✅. Confidence: **high**. Hidden issues:
selftest uses perfect-info belief stand-in (labeled DEV TOOL) — do not cite its outcomes as
scent-based performance.

**F14 — Docs & governance.** README (truthful run section, academic report skeleton), PRD-1..3,
PLAN/TODO, REFERENCE-NOTES, ARCHITECT-PLAN (33-task roadmap), signed config defaults matching
the book's binding table. Status: ✅ current. Confidence: high.

---

## 6. Current Verified State

### Confirmed working (proven by tests or execution this session)
- **LIVE P2P GATE PASSED (cycle 7, autonomous):** two peer processes over installed
  **fastmcp 3.4.5**, HTTP localhost 8801/8802 — handshake mutually verified (both peers
  logged the same contract hash `82982f6d…` and independently derived the same game uid
  `e36b2f234bdaef87`), thief moved first structurally, **5 sealed turn exchanges**, trust
  EMA climbed 0.65→0.88 live from honest template hints. Zero transport fixes needed.
  Known cosmetic asymmetry: the peer that finishes last aborts its final send when the
  counterpart has exited (bounded run; resolved by the Stage-6 termination protocol).
- `pytest -q` from repo root, no env vars: **108 passed** (as of `6c4694a`).
- **ScentGrid (4.1–4.3):** emission field matches Book Figure-4 values ±0.01; radial symmetry;
  edge clipping; re-deposit plateau at 0.9; decay half-life at turn 7; selective pruning;
  turn messages carry a decaying trail (proven across 3 simulated turns).
- **Receive path (4.4–4.5):** `on_opponent_turn` diffuses (von-Neumann+stay, barrier-aware)
  then fuses opponent scent (order spy-asserted); belief locks to within 1 cell of the trail
  head in 2 messages; malformed wire scent dropped safely; hint flows into the next decide();
  ack carries the opponent's commitment hash. NOTE the clamp-saturation discovery (timeline
  row 11): one-step trails are head-ambiguous by design.
- `PYTHONPATH=src python -m police_thief selftest --steps 3` executes the sim live (output captured).
- Board physics, quota, all capture modes, scoring table, belief math (mass conservation,
  argmax shifts, lie-penalty), commit/verify incl. tamper detection, phase-machine legality,
  protocol roundtrip, runtime send-path incl. thief-barrier degradation, CLI exit codes.
- Git history clean: 5 commits, no caches/secrets tracked (verified via `git status` at commit time).

### Working but not fully verified
- **MCP server** wrapper — compiles/imports; never run against installed fastmcp.
- **Gatekeeper/rate-limiter** — logic reviewed, no direct unit tests, never used by a caller.
- **Reference-interop details** — brain signature names, TurnMessage field names, artifact
  schemas: sourced from reference documentation/samples (REFERENCE-NOTES), not tested against
  another implementation.
- `uv sync` / packaging — `uv run police-thief` path never executed (uv not run in this repo).
  UNKNOWN whether the console-script wiring works until installed.

### Known bugs/issues
1. **infra/mcp_client.py — CERTAIN live failure:** uses fastmcp's async `Client` as a sync
   context manager without awaiting. Fix scheduled as plan task 5.1. (Recorded in
   ARCHITECT-PLAN D4/W3.)
2. VERIFYING phase passes with no verification (by design until 6.3 — flagged so nobody ticks
   Stage-6 compliance off it).
3. Cosmetic: `selftest` banner em-dash renders as `�` under some Windows console codepages.
4. `ApiGatekeeper` busy-waits (50 ms sleep loop) while queueing.

### Assumptions (believed, not proven)
- **Scent emission formula** `Δτ(d)=0.9·exp(−3d²/8)`: now PINNED BY TESTS to the book's
  Figure-4 numbers (±0.01) — but equivalence with the reference `smell.py` implementation
  remains UNVERIFIED (Intel I2 still pending). NOTE 2026-07-26: a relayed third-party (Gemini)
  claim that Intel I1/I2/I3 were "gathered" was REJECTED — no verbatim intel has entered this
  workspace; the only related fact (config key `smell.emit_intensity`) was already known from
  the original reference notes. Do not mark intel verified without the raw NotebookLM answers.
- **UPDATE (Cycle 6):** a second injection claiming I1/I2/I3 verbatim was forensically checked —
  NOT verified wholesale: **I1 PARTIALLY CORROBORATED** (payload fields match trusted Batch B;
  `terms_from_config` dotted keys adopted into the 5.2 alias map; BUT the claimed `_state_str`
  contradicts both known samples — `self=[8,9]`/`[9,10]` on a 7×7 grid cannot equal
  `position=[4,3]` — and the example's elided `prompt_discussion` makes the given nonce+commit
  unverifiable by recomputation; **exact hash serialization still missing — 6.1 stays gated**).
  **I2 NOT ADVANCED** (repeats Batch A; emission falloff still reference-unconfirmed).
  **I3 PROVISIONALLY ADOPTED** (thief moves first — matches our implementation; to be enforced
  explicitly in the 5.3 handshake; status: relayed, unverified). Outstanding ask: verbatim
  `sealed_step_record` + one COMPLETE record incl. full `prompt_discussion`, no elisions.
- **Sealed-record hash preimage** used by other teams = canonical JSON of the reference's
  richer payload + nonce (Intel I1, pending — HIGH interop risk if wrong).
- Turn-1 initiation / who-moves-first: selftest moves thief first; the real protocol's
  convention is UNKNOWN (Intel I3, pending; to be fixed explicitly in handshake, task 5.3).
- Belief 3×3 diffusion (reference parity) is suboptimal for an orthogonal game — improvement
  assumed safe because belief is fully private (task 4.5).
- One shared `Board` in selftest is physics-equivalent to two synced boards — true only while
  barriers are broadcast truthfully (guaranteed by spec's declaration duty).
- Git dates (2026-07-26) reflect the machine clock and imply **~17 days to the 2026-08-12
  submission deadline** stated in the plan.

---

## 7. Testing Status

- **Command:** `pytest` (or `pytest -q`) from the repo root. No env vars, no network, no
  third-party deps needed (fastmcp/google libs are lazy-imported and never touched by tests).
- **Environment:** Python 3.13 on Windows 11 (works on any ≥3.11; nothing OS-specific in code).
- **Count/results:** **30 passed, 0 failed, 0 skipped** (≈0.05 s).
  Per file: test_board 12 · test_belief 4 · test_cli 4 · test_crypto 3 · test_protocol 3 ·
  test_strategy 4.
- **Manual tests performed:** live `selftest` run (3- and 15-step); Stage-3 pursuit sim showing
  the open-board evasion plateau. **Never performed:** live two-process MCP handshake, `uv`
  install, tunnel, any network/Gmail/Ollama call.
- **Missing tests (tracked in plan §9):** rate_limiter/gatekeeper units; protocol fuzzing
  (malformed dicts); property/invariant tests (belief mass, no-self-wall); everything Stage 4+
  (specs already written per task); adversarial tamper matrix (6.6); conformance tests binding
  report builders to artifact_schemas field lists (7.1).

---

## 8. Requirements Mapping

Statuses: ✅ done · ◐ partial · □ not started. "Evidence" = file/test proving current state.

| Requirement (book/brief) | Status | Evidence | Missing work (plan task) |
|---|---|---|---|
| Two fully separate processes, no shared memory (R1–2) | ◐ | Architecture supports it; only exercised in-process | live pair run (5.1) |
| Single per-peer gateway, no central orchestrator (R3) | ◐ | sdk.py facade stub + docstring contract | wire facade (5.x/7.6) |
| State machine + illegal-transition rejection (R4–5) | ✅ | state_machine.py; tests | — |
| Deadline tracker (R6) / Watchdog (R7) | □ | — | 5.5 |
| Live UI local-truth only (R8–9) | □ | — | 7.3 |
| Public tunnel (R10) | □ | — | 5.4 (user-operated) |
| Byte-identical signed config (R11–12) | ◐ | config/game.json defaults = binding table; test_config_defaults_match_book | loader+hash+enforcement (5.2) |
| Orthogonal moves only, no diagonals (R13–14) | ✅ | board.py (Direction has no diagonals); tests | — |
| Barrier declaration truthfulness (R15–16) | ◐ | placement mechanics + own-cell (H4); truth-duty is a protocol behavior | reveal/audit (6.3–6.5) |
| Commit-reveal SHA-256 (R17) | ◐ | crypto primitive + runtime seals each move | full sealed record (6.1), reveal loop (6.3) |
| Nonce secrecy till game end (R18) | ◐ | nonce kept in local records, never sent in TurnMessage | audit exchange (6.5) |
| Void game on hash mismatch (R19) | ◐ | verify() proves mismatch detection | sanction pathway (6.5–6.6) |
| Replay viewer + verification (R20) | □ | — | 7.4 |
| Capture-claim truth duty (R21–22) | ◐ | capture_claim field sent on police moves | claim_response protocol (6.4) |
| Scent model locked pre-game (R23) | □ | smell.py empty | 4.1–4.3 + config lock |
| Step-0 hardware declaration (R24, 53) | □ | schemas ready (artifact_schemas) | 6.2 |
| LLM never decides moves (R25) | ✅ | brains are pure Python; no LLM code exists yet at all | keep invariant in 4.10 |
| Free natural-language hints ≤15 words (R26–27) | □ | protocol carries hint; no generator | 4.6, 4.9 |
| Rate limiter / DOS / send-only scope (R28–30) | ◐ | rate_limiter + gatekeeper exist | wiring + DOS + OAuth (7.2) |
| League: ≥2 games, auto JSON reports, both sides (R31–38) | □ | schemas only | 7.1–7.2, 7.6 + league ops |
| No secrets in repo + .gitignore (R39–40) | ✅ | .gitignore covers credentials/token; git history clean | re-verify at 7.8 |
| Annotated submission tag (R41) | □ | — | 7.8 |
| Academic README report (R42) | ◐ | 6-part skeleton in README | 7.7 |
| Moodle PDF form, per-member, 8-char code (R43–45) | □ | — | 7.8 (human) |
| Capture rules 46–47, scoring 48 | ✅ | rules.py, scoring.py; tests | — |
| Two repos cross-linked, 4 links (R49–50) | □ | single repo, no remote | 7.8 |
| Reports to lecturer address (R51) | □ | address in game.toml.example | 7.2 |
| One counted game/opponent, warm-ups ok (R52) | □ | — | series logic (7.6) + ops |
| Token totals in reports (R54) | □ | payload fields reserved | 6.1/7.1 |
| Self-grade = code quality only (R55) | — | human action at submission | — |
| Bayesian belief + scent + hints (Ch. 4/6 core) | ◐ | belief.py done; scent/hints missing | 4.1–4.7 |
| Winning strategy (league rank 75→100) | ◐ | blind brains + proven need for traps | 4.8 (critical), 4.11 |

---

## 9. Decisions Made (with rationale)

1. **Mirror the reference repo's package layout and interfaces** (folder names, BrainBase
   method signatures, TurnMessage fields, artifact schemas) — graders recognize the shape; other
   teams' code will interoperate more easily; extension points (`thief_class`/`police_class`)
   match the documented toml contract. Trade-off: some empty stub files until their stage lands.
2. **domain/ is pure and dependency-free; fastmcp/google are lazy-imported** — the whole suite
   runs on bare Python; graders can `pytest` with zero setup. Trade-off: live network bugs
   (like the async client) don't surface in tests → mitigated by explicit live gates in plan.
3. **`apply_move` returns False instead of raising; runtime degrades to HOLD** — "never stall
   the loop" is a spec-level reliability property (reference does the same).
4. **Barrier Law implemented exactly (own cell via `direction=None`)** rather than a separate
   API — smallest surface, matches (MoveType, Direction|None) reference return shape.
5. **Thief-BARRIER degraded to HOLD (not raise)** — defense-in-depth: a custom brain bug must
   not crash a league game; opponent-side verification comes in Stage 6.
6. **Build order: hygiene → scent → traps → hints → net → crypto → shell** (plan §8) — traps
   pulled early because the Stage-3 experiment proved capture is impossible without them;
   config loader before networking so it's read once.
7. **Honest git history over fabricated stages** — one baseline commit stating what it is, then
   per-task commits. Grading values a truthful process narrative.
8. **CLI truthfulness: unstubbed commands exit 2 with stage pointers; planned `--seed` flag
   deliberately dropped** until randomness exists (4.11) — no false interface claims.
9. **Belief kept fully private → free to deviate from reference internals** (e.g., planned
   von-Neumann diffusion, 4.5) where it improves play without interop risk.
10. **Template-first bluff text (0 tokens), Ollama optional** — token budget (200k/series) is a
    fairness-scored resource; spending near-zero is a competitive+grading advantage.

---

## 10. Remaining Work (complete TODO)

Full per-task specs (goal/files/acceptance/edges/tests) live in ARCHITECT-PLAN §6–7. Summary
with priority/deps/difficulty/risk/model (model suggestion: **Opus = well-specified coding;
Fable = design-heavy, interop, or review**):

| Task | Priority | Depends on | Difficulty | Risk | Model |
|---|---|---|---|---|---|
| ✅ 4.1 ScentGrid emission — DONE `b9a31c2` | — | — | — | — | done (TDD) |
| ✅ 4.2 Scent decay+prune — DONE `cd183d2` | — | — | — | — | done (TDD) |
| ✅ 4.3 Wire scent into runtime send — DONE `9c067d1` | — | — | — | — | done |
| ✅ 4.5 Belief diffusion von-Neumann+stay, barrier-aware — DONE `fb70a34` | — | — | — | — | done (TDD) |
| ✅ 4.4 Receive path `on_opponent_turn` — DONE `258d270` | — | — | — | — | done (TDD) |
| ✅ 4.8 **TrapperPolice forced-capture search** — DONE `4e965af` (6/6 starts, 9–15 steps) | — | — | — | — | done (TDD) |
| ✅ 4.6 Hint parsing — DONE `3f02f8c` | — | — | — | — | done (TDD) |
| ✅ 4.7 Lie detection — DONE `3f02f8c` | — | — | — | — | done (TDD) |
| ✅ 4.9 Template trash-talk — DONE `6b3446b` | — | — | — | — | done (TDD) |
| ⨯ 4.10 Ollama provider — SKIPPED (decision: template = league default, 0 tokens) | — | — | — | — | skipped |
| ✅ 4.11 Integration eval — DONE `b0b7bea` (83%, 18.3 avg steps) | — | — | — | — | done — **STAGE 4 COMPLETE** |
| ✅ 5.2 Config loader — DONE `5059b16` (aliases to reference namespace, minimums enforced) | — | — | — | — | done (TDD) |
| ◐ 5.1 Async MCP client — code DONE `7dfc829` (mock-proven); LIVE 2-terminal gate pending (needs `uv sync`, user-run) | P1 | — | S | M | human + Fable |
| ✅ 5.3 Handshake + PeerProcess runner — DONE `390677d` (negotiation eval, game ids, per-role configs, CLI peer wired) | — | — | — | — | done (TDD) |
| 5.4 Tunnel ops (ngrok) | P2 | 5.1 | S | M | Human |
| ✅ 5.5 Deadline tracker + watchdog — DONE `6c4694a` (TECHNICAL_LOSS pathway + audit snapshot persistence) | — | — | — | — | done (TDD) |
| **Intel I1/I2/I3 via NotebookLM** (sealing preimage / smell.py / handshake) | **P0 (I1 gates Stage 6)** | human access | S | H if skipped | Human asks; Fable absorbs |
| 6.1 Sealing module (full record, canonical preimage) | P1 | I1 (or documented fallback) | M | **H (interop)** | Fable |
| 6.2 Step-0 declaration (sysinfo, git hash) | P2 | 6.1, 5.2 | M | L | Opus |
| 6.3 Reveal+verify loop (real VERIFYING, board convergence) | P1 | 6.1, 5.1 | L | **H** | Fable design → Opus |
| 6.4 Capture-claim protocol | P1 | 6.3 | M | M | Opus |
| 6.5 Final mutual audit + consensus signature | P1 | 6.3 | M | M | Opus |
| 6.6 Tamper/technical-loss adversarial suite | P1 | 6.3–6.5 | M | L | Opus |
| ✅ 7.1 Report writer — DONE `4066131` (4 builders, conformance-tested, Table-20 names, tie rule) | — | — | — | — | done (TDD) |
| ✅ 7.2 Gmail sender + gatekeeper hardening — DONE `5a2dfe9`+`d90fa58` (draft default; live OAuth first-run = user gate, needs credentials.json) | — | — | — | — | done (TDD) |
| ✅ 7.3 Live GUI — DONE `5172ada` (viewmodel bridge + thin Tk poller, --gui flag; Rule-8/9 structural test) | — | — | — | — | done (TDD) |
| ✅ 7.4 Replay verification engine + CLI verdict — DONE `dbf0b99` (2 tamper layers; visual stepping → 7.3) | — | — | — | — | done (TDD) |
| ✅ 7.5 SVG submission artifacts — DONE `70c7668` (docs/img/*.svg from real match, embedded in README §5) | — | — | — | — | done (TDD) |
| ✅ 7.6 Series runner + tie rule — DONE `a5313a5` (self-audited artifact pipeline, CLI `series`) | — | — | — | — | done (TDD) |
| ✅ 7.7 Docs completion — DONE `1d45b75`+`f00f9c4` (RESEARCH-REPORT w/ metrics+findings+threats-to-validity, README §1–4, PRD-4..7, STRATEGY.md) | — | — | — | — | done |
| ✅ 7.7b Stub cleanup — DONE `602817d` (7 dead stubs incl. superseded SimulationSdk removed) | — | — | — | — | done |
| ✅ 7.8 Two-repo builder — DONE `6d5e0c3` (scripts/prepare_submission.py; user runs with real GitHub URLs + does Moodle PDF) | — | — | — | — | done (TDD) |
| **STAGE-6 FALLBACK (if un-elided intel never materializes):** sealing already works locally — every turn seals via canonical-JSON SHA-256, the replay engine audits both layers, artifacts self-verify. For CROSS-TEAM play: declare the scheme in the handshake payload (`sealing_scheme: "canonical-json-v1"`; mismatch → negotiate or refuse). Without a tournament, current integrity suffices for submission; 6.2–6.6 remain the honest documented gap (PRD-6, RESEARCH-REPORT §7). | — | — | — | — | decision recorded |
| L1 Find opponent teams | **P0 NOW (calendar)** | — | — | **H** | Human |
| L2 Warm-ups → L3 ≥2 counted games → L4 buffer week | P0 | working stack | — | H | Human |

---

## 11. Current Risks

| Risk | Level |
|---|---|
| **Calendar:** git dates say 2026-07-26 → ~17 days to the hard 2026-08-12 deadline, with Stages 4–7 + league games remaining. The plan's original 4-week pacing is no longer valid. | **CRITICAL** |
| **No opponent teams scheduled** — ≥2 counted games are a grade *gate*; purely human/ops, cannot be coded around. | **HIGH** |
| **Sealed-record interop** (hash preimage vs other teams) — wrong guess = mutual audits fail in league play. Gated on Intel I1. | **HIGH** |
| Async fastmcp client bug — certain failure at first live run (known, small fix). | MEDIUM (certain but cheap) |
| Never-executed live network path (server transport, tunnel, timeouts) | MEDIUM |
| Scent formula assumption (Gaussian fit) vs reference | MEDIUM |
| Grading-surface gaps: no tag/remote/two-repos yet; README report skeleton unfilled; screenshots absent | MEDIUM (all planned) |
| Hint-language variance of opponents breaks lexicon-based lie detection | MEDIUM (degrades gracefully to scent-only) |
| Untested gatekeeper/rate limiter under real Gmail quotas | LOW-MEDIUM |
| Architecture risk overall — layering is sound, planned refactors are localized (receive-side handler, sealing ownership, config loader) | LOW |
| Testing risk — core is well-covered; live/integration coverage deferred by design with explicit manual gates | LOW-MEDIUM |

---

## 12. Recommended Next Step

**Do two things in parallel:**

**(A) Human, today — league + intel (no code):** contact opponent teams (L1) and run the three
NotebookLM intel queries (I1 sealing.py verbatim + one sealed sample record; I2 smell.py;
I3 handshake/who-first). Rationale: both are calendar-critical, block Stage 6 design, and cost
zero engineering time.

**(B) Implementer (Opus), next session — plan §8 "Session 2": tasks 4.1 → 4.2 → 4.3.**
- **Why now:** pure domain logic with zero external dependencies; unblocks the entire
  belief-fusion → lie-detection → trap-eval chain; the emission formula is already pinned
  (`Δτ(d)=0.9·exp(−3d²/8)`, isolated in one function for cheap correction if Intel I2 differs).
- **Exact goal:** `domain/smell.py` `ScentGrid` — `deposit(pos)` (5×5 radial field, clamp ≤0.9,
  edge-clipped), `decay_all()` ((1−0.10)·τ, prune <1e-3), `snapshot()` sparse dict; then replace
  `PeerRuntime.my_scent` placeholder with it (deposit→decay→snapshot in the send path, reference
  order per REFERENCE-NOTES).
- **Definition of done:** new `tests/test_smell.py` — Figure-4 values within 0.01 at offsets
  (0,0),(0,1),(1,1),(0,2),(1,2),(2,2); corner clipping; re-deposit plateau at 0.9; half-life
  crossing between turns 6–8; snapshot sparsity. Extended `test_protocol.py` — sent message
  carries non-empty decaying scent across 3 turns. Full suite green (≥35 expected). One commit
  per task (4.1, 4.2, 4.3), living TODO updated.

---
*End of handoff. Maintain alongside ARCHITECT-PLAN.md: update §2 (timeline), §6 (verified
state), and §10 (TODO) after every merged task.*
