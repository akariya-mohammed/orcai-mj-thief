# PRD 4 — Language + Scent (retro)

**Goal:** the uncertainty layer — scent physics, belief fusion, verbal hints with lie
detection, and the strategy that converts it all into captures.

## Delivered
- `domain/smell.py` — Gaussian emission `Δτ(d)=0.9·exp(−3d²/8)` (test-pinned to Book
  Fig-4 ±0.01), decay ρ=0.10 (half-life at turn 7), prune, clamp-at-center.
- `domain/belief.py` — von-Neumann+stay diffusion (documented deviation), barrier-aware,
  stranded-mass relocation; scent fusion; penalize/boost as one lever.
- Receive path `on_opponent_turn` — diffuse→fuse order spy-asserted; hardened wire parse.
- `domain/hints.py` + trust EMA — scent-vs-claim judging (Book Ch. 4), EN+HE lexicon,
  early-game guard; lie ×0.1, truth rewarded only on scent-backed cells.
- `strategy/trapping.py` — forced-capture search (see RESEARCH-REPORT §3).
- `strategy/trash_talk.py` — template provider, 0 tokens, digit-free, ≤15 words.
- `sdk/localsim.py` — two real PeerRuntimes over loopback; eval harness.

## Gate (met)
Scent-only capture ≥60 % → **94 % vs a talkative opponent, 67 % vs a silent one**;
lie detection fires in real play. 4.10 (Ollama) skipped by decision — template is the league default.

## Discoveries recorded
Clamp-saturation head ambiguity; guarding pathology of 1-ply containment rewards;
search-invented own-cell-wall tactic. Details: RESEARCH-REPORT §2–3.
