# PLAN — Distributed Cops-and-Robbers (P2P)

Bottom-up, 7 layers. **Each layer runs end-to-end before the next is added** (Book Ch. 10).
Do not advance past a stage until its milestone gate is an *observed behavior*, not "code written".

| Stage | PRD | Build | Milestone gate | Rules |
|------|-----|-------|----------------|-------|
| 1 | `docs/PRD-1-base-logic.md` | 7×7 grid, N/S/E/W/STAY, barriers, capture/scoring — single process | 2 agents move legally; over-quota barrier rejected; overlap = capture | 13–16, 46–48 |
| 2 | `docs/PRD-2-mcp-infra.md` | 2 processes, FastMCP server+client, geometric msgs over localhost | msg from A decoded correctly by B | 1, 3–7 |
| 3 | `docs/PRD-3-blind-strategy.md` | `BrainBase` subclass; Manhattan + Bayesian belief, no scent/LLM | known target → shortest legal path, unaided | 25 |
| 4 | `docs/PRD-4-language-scent.md` | pheromone emit/decay (0.9 / 0.10 / 5×5), belief update, LLM bluff text only | hint→inference; scent decays; LLM emits truth/lie hint | 4, 23, 26–27 |
| 5 | `docs/PRD-5-cloud-tunnel.md` | ngrok/Localtonet public URLs, cross-machine play | remote peer connects, full match runs | 10 |
| 6 | `docs/PRD-6-security.md` | SHA-256 commit-reveal, nonce secrecy, Step-0 hardware+commit-hash decl | commit→reveal valid; audit passes; tamper→disqualify | 17–22, 24, 53 |
| 7 | `docs/PRD-7-reporting.md` | Gmail API (send-only), Live GUI heatmap, Replay Viewer | both sides email JSON; Replay stamps Verified OK | 28–40, 49–52, 54 |

## Non-negotiables locked up front
- `config/game.json` agreed **byte-identical** with the opponent, then signed (Rule 11).
- Secrets in `.gitignore` **before the first commit** (Rules 39–40).
- Move decision is **always pure Python**; the LLM only writes bluff text (Rule 25).

## Success metrics (Ch. 11) — demonstrate each with an artifact
Coordination · Adaptation · Integrity · Architecture.

## Critical-path dependency
An **opponent team** — needed for the ≥2 counted league games. Secure this in Week 1; it is not a code task.
