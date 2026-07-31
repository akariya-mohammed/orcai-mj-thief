# Research Report — Performance Analysis & Empirical Findings

> Police-vs-Thief, distributed P2P pursuit (Dec-POMDP) · Dr. Segal, "Orchestration of AI
> Agents" · code v0.1.0, 182 automated tests. Every number below is reproducible from the
> repository: `pytest` (unit/integration), `uv run police-thief selftest --scent` (headline
> metrics), `uv run python scripts/render_docs_images.py` (figures).

## 1. Headline results

| Metric | Value | Conditions |
|---|---|---|
| **Capture rate vs a talkative opponent** | **94 % (17/18)** | full production path, strict partial observability; 6 start positions × 3 seeds |
| **Capture rate vs a silent opponent** | **67 % (12/18)** | same, opponent emitting no parseable hints (our own doctrine, §4) |
| **Avg. steps to capture** | **14.0–14.6** | survival threshold 35 |
| Perfect-information benchmark | 100 % (6/6), 9–15 steps | delta belief (upper bound) |
| Blind-chase baseline | **0 %** — provably never captures | see §3 |
| Lies caught / truths confirmed | 3 / 244 | scent-vs-claim judge, talkative opponent |
| Trust EMA, live network run | 0.65 → 0.88 over 5 turns | honest template hints, fastmcp 3.4.5 |
| Token consumption | **0** of the 200,000/series budget | template verbal layer |
| Barriers spent per match | ≈5 of 14 (max 10) | search commits walls only inside short capture lines |

The 27-point spread between the talkative and silent columns is the measured
value of the verbal channel — and, read from the other side, the measured value
of our own decision to stay silent (§4).

The gap between 94 % (belief cloud) and 100 % (perfect information) is the measured price
of partial observability; the gap between 0 % (blind chase) and 94 % is the measured value
of the barrier-search strategy.

## 2. Finding I — trail-head ambiguity is intrinsic (scent clamping)

Emission is clamped at the center intensity (0.9): continuous presence plateaus rather than
accumulates (Book Fig. 5). Consequence, discovered by a failing test: when the opponent
moves one step, the fresh field re-saturates the cell *behind* the head
(0.81 + 0.62 → clamp 0.9), so after decay the head and the cell behind it are **identical
(0.81 each)**. A one-step trail is therefore *head-ambiguous by construction* — no reader,
however clever, can resolve it below a ~1-cell radius. This is the book's "probability
cloud, not a sharp point" made quantitative. Engineering consequences: (a) the belief
argmax is treated as a *blob center to herd*, never a point to pounce on blindly; (b) our
acceptance criterion for belief fusion is argmax-within-1-of-head (met in 2 messages);
(c) head-exact tracking only emerges for trails longer than the emission radius (2 cells).

## 3. Finding II — the guarding pathology, and why capture requires search

A lone cop on a Cartesian grid is **robber-win** (the grid is not dismantlable —
Nowakowski–Winkler, cited by the course book): empirically, blind pursuit plateaus at
Manhattan distance 6 forever. Barriers are therefore not an optimization — they are the
*only* capture mechanism. Two reward-shaping designs failed before the working one:

1. **Mobility-weighted barrier score** (reduce the thief's legal moves, belief-weighted):
   at plateau range the cop's placeable cells never intersect the thief's mobility —
   the score is ≈0 forever; no barrier is ever placed.
2. **k-step reachable-area score**: produced the *guarding pathology* — the cop herded the
   thief into a corner, then discovered that approaching makes the predicted thief break
   out (area term jumps), so it **oscillated at a safe distance, "containing" forever**
   (first from across the board; after proximity-scaling the weight, in a range-5 mirror
   dance). Any 1-ply containment reward optimizes guarding, not capture, because capture
   value lies 2–3 plies deep.

**Working design — forced-capture search** (the book's minimax/own-algorithm track; this
is *not* reinforcement learning — nothing is learned): an A*-style forward search over cop
action sequences (moves + every legal Barrier-Law placement, including the cop's own
cell), with our own flee heuristic serving as a deterministic opponent model; the cop
plays the first action of the shortest capture line found (barrier-on-thief R46, overlap,
or full enclosure R47), else falls back to pure interception chase. Budget ≤800 nodes,
depth ≤10 per decision (≈ milliseconds). Two emergent properties we did not hand-design:
**quota thrift** (barriers are only ever spent inside a found capture line) and a **novel
tactic invented by the search itself**: wall your *own*
cell, forcing the cornered thief to step adjacent, then capture by overlap.

## 4. Finding III — deception is self-disclosing (lie detection)

Verbal hints are the only fakeable channel; scent is unfakeable. The judge therefore
tests every parsed claim against the claimant's *own* scent snapshot (the book's Ch. 4
worked example): a "heading north" claim whose region holds <10 % of the total scent mass
while the mass sits south-east is a proven lie → the claimed region is suppressed ×0.1
and the speaker's trust EMA (α=0.3) drops; a proven truth builds trust and rewards the
scent-backed cells only (see below). An
early-game guard (total mass < 0.5 → verdict *unknown*) prevents accusations without
evidence.

Two refinements followed from adversarial self-review, both empirically driven:

**Truth-washing resistance.** A verdict based on mass share alone is exploitable: a broad
claim propped up by a decaying tail can clear the 30 % threshold while the true scent peak
lies elsewhere, and rewarding it *hijacks the posterior into the wrong quadrant*
(reproduced: argmax moved (5,5) → (2,2), peak confidence 0.25 → 0.18). TRUTH therefore now
requires the scent **peak** inside the claim, and the reward is confined to scent-backed
cells (≥ 50 % of peak). Confinement is what makes a strong reward safe — every boosted
cell is real evidence, so no decoy can be amplified. *Note for the record:* our initial
hypothesis, that a uniform region boost "smears" a sharp peak, was tested and found
**false** (uniform multiplication preserves within-region ratios); the true failure mode
was the verdict, not the boost magnitude.

**Zero-information doctrine.** Symmetrically, the same detector runs on the other side of
the table: a truthful compass hint is free localization for a competent opponent, and a
caught lie leaks identically once inverted. Our peers therefore default to silence and
speak only under threat, mixing bluffs with silence so that speaking is not itself a tell.
The measured cost to an opponent facing this doctrine is 27 points of capture rate (§1).

## 5. Token & cost analysis

- **Verbal layer:** template provider — pre-written, compass-parameterized, digit-free
  (Rule 27), ≤15 words. **0 tokens consumed** against the signed 200,000/series budget;
  `tokens_total` in every artifact is measured, not assumed. An Ollama provider (local,
  0 API tokens) was scoped (task 4.10) and deliberately skipped: the league default is
  template mode and the move is never LLM-driven (Rule 25), so the marginal value was
  rhetorical only. Under the course's computational-fairness normalization, near-zero
  resource use with a 94 % capture rate is the favorable corner of the score surface.
- **Outbound API protection:** all external calls route through `ApiGatekeeper` — a
  sliding 60-second window (30 requests/min signed config, queue depth 100, retry with
  backoff) that queues rather than errors, protecting against the 429-lockout failure
  mode of the Gmail quota.
- **Compute profile:** the full 182-test suite runs in ≈9 s; a complete scent-only match
  costs ≈0.15 s of CPU. The bottleneck in live play is network round-trip, not
  computation — measured on the live localhost run (fastmcp 3.4.5), where turn cadence
  was dominated by HTTP session setup per call.

## 6. Cryptographic integrity (verification, not trust)

Every move is sealed before it is revealed (SHA-256 commit over canonical JSON with a
128-bit nonce). The replay engine audits **two layers**: per-record commitment
recomputation (a rewritten move fails its own hash; the exact tampered step is reported)
and a **consensus signature** over the whole record set (catching wholesale substitution
of individually-valid records). The verdict is binary — "Verified OK" / "TAMPERED" — and
machine-decidable; the submission badge in `docs/img/replay_verified.svg` is generated by
an actual verification pass over a real match log, not drawn.

## 7. Threats to validity (stated plainly)

- **Adversarial re-audit (2026-07-31).** Our evasion was rebuilt after red-teaming showed
  plain max-distance flight survives 0/6 against our own cop while an inner-ring runner
  survives 6/6; `RingRunnerThief` now ships (18/18 across a search cop, a chase cop and a
  pre-walled board). The same audit found the reverse honestly: **our cop captures 0/4
  against an edge-hugging evader.** Every capture line it finds opens with a step, so it
  never spends a wall, and it mirror-locks at distance 4 — the robber-win result asserting
  itself, since the Barrier Law only permits walling adjacent to oneself and a mirroring
  evader never lets the pursuer close. Capturing an elite evader needs sustained
  fence-building we do not claim to have.
- Both capture rates are measured against **our own deterministic thief** (talkative and
  silent variants); league opponents will differ. The opponent model degrades gracefully
  (re-planned every turn), but no claim is made about unknown opponents. The tuned
  constants (barrier-line depth ceiling, truth-reward magnitude) were fitted on this same
  self-play population and may be mildly over-fitted to it.
- Hash **interop with reference-derived teams is unverified**: the reference's exact
  sealed-record serialization has resisted extraction (elided sources). Until it is
  confirmed, cross-team audits may require negotiating the sealing scheme at handshake.
- Hint parsing is lexicon-based (EN+HE compass + landmarks); adversarial phrasing outside
  the lexicon parses to *no claim* — safe (no false accusations) but information is lost.
- The live termination protocol (capture claims, win agreement) is the remaining Stage-6
  work; live runs are currently bounded-turn.

## 8. Reproduction

```bash
uv sync
pytest                                          # 134 tests, ~5 s
uv run police-thief selftest --scent            # headline metrics line
uv run police-thief series --games 2            # full artifact pipeline -> artifacts/
uv run python scripts/render_docs_images.py     # regenerate all figures
uv run police-thief peer --role police --gui    # live window (2nd terminal: --role thief)
```
