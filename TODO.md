# TODO

## Stage 1 — Base logic
- [ ] Board model: 7×7, coordinates, barriers set
- [ ] Legal-move generator (orthogonal only; reject diagonals)
- [ ] Barrier quota enforcement (max 14)
- [ ] Capture rules: overlap, barrier-on-thief (R46), thief with no legal move (R47)
- [ ] Scoring table (R48): 20/5, 5/10, 2/2, 0/0
- [ ] GATE: two agents move legally; over-quota barrier rejected; overlap = capture

## Stage 2 — MCP infra
- [ ] FastMCP server exposing `receive_move` tool
- [ ] Client that calls the opponent's tool over localhost
- [ ] Orchestrator = single gateway (R3)
- [ ] State machine wired (R4–5) — see `domain/state_machine.py`
- [ ] Deadline tracker + watchdog (R6–7)
- [ ] GATE: message from A decoded correctly by B

## Stage 3 — Blind strategy
- [ ] `BrainBase` + `ManhattanBayesBrain` (`_pick_move`, cop `_decide_move`)
- [ ] Bayesian belief map
- [ ] GATE: known target → shortest legal path, unaided

## Stage 4 — Language + scent
- [ ] Pheromone emit/decay (0.9 / 0.10 / 5×5)
- [ ] Belief update from opponent scent + verbal hint (with reliability weight)
- [ ] Lie-detection: scent-vs-claim cross-check (the showcase tactic)
- [ ] LLM bluff text (local Ollama, provider="template" default)
- [ ] GATE: hint→inference; scent decays; LLM emits truth/lie hint

## Stage 5 — Cloud + tunnel
- [ ] ngrok/Localtonet public URL
- [ ] Cross-machine match
- [ ] GATE: remote peer connects, full match runs

## Stage 6 — Security
- [ ] Commit-reveal wired into the turn loop (`domain/crypto.py`)
- [ ] Nonce kept secret until final audit (R18)
- [ ] Step-0 declaration: OS/CPU/RAM/GPU + model + commit hash (R24, R53)
- [ ] GATE: commit→reveal valid; audit passes; tampered log → disqualify

## Stage 7 — Reporting shell
- [ ] Gmail API send-only (OAuth), Gatekeeper (`infra/gatekeeper.py`)
- [ ] Live GUI heatmap + turn banner
- [ ] Replay Viewer with Verified OK / TAMPERED
- [ ] 4 output JSONs: declaration / config / log / result, with token totals (R54)
- [ ] GATE: both sides email JSON; Replay stamps Verified OK

## Professionalism artifacts (the road to 100)
- [ ] `docs/RESEARCH-REPORT-Performance-Analysis.md` (token/cost analysis per provider)
- [ ] Academic `README.md` (6-part, Ch. 9)
- [ ] pytest suite green in CI
- [ ] Two repos, cross-linked, tagged `v1.0-submission`
