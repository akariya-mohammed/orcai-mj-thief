# PRD 6 — Security & Cryptography (COMPLETE)

**Goal:** commit-reveal sealing, Step-0 declaration, reveal/verify loop, mutual audit.

## Delivered
- `domain/crypto.py` — canonical-JSON SHA-256 commit/verify primitive with 128-bit nonce
  (every live turn already seals through it).
- Replay verification engine (`gui/replay_data.py`) — per-record + consensus-signature
  audit layers (built with 7.4; it IS the audit engine this stage completes).
- **6.1 sealing module** (`peer/sealing.py`) — records carry step + position as unhashed
  metadata for the final audit; the digest preimage is canonical JSON over
  {state, move, intent, nonce}. Scheme id `canonical-json-v1`.
- **Rule 15 barrier declaration** — placements are declared on the wire, quota-checked on
  receipt, and applied to the receiver's board. This closed a live-play defect that local
  simulation could not surface (shared Board object): without it the two peers' boards
  diverge and every later legality check disagrees.

- **6.2 Step-0** (`shared/sysinfo.py` + `sealing.step_zero_record`) — spec, model and the
  exact playing commit sealed before turn 1; the handshake REQUIRES a step0 commitment and
  a matching sealing scheme, so an unauditable peer is refused at initialisation.
- **6.4 terminal claims** (`domain/termination.py`) — capture and survival claims; a denial
  ships the denier's own position, making a false denial provable at audit (Rules 21-22).
- **6.5 mutual audit + P0-3** (`peer/audit.py`) — three provable layers: digest chain,
  revealed move-chain legality (single steps, HOLD really held, no thief walls, quota), and
  scent history. **P0-3 has two modes:** structural (default) asserts only what any honest
  emission model satisfies — scent appears near where you have been — so a differing but
  legal falloff is never accused; strict replays our model and is used only when both peers
  declared the same scent model. Accusing an honest opponent loses US the game.

## Remaining
- 6.3 wiring the terminal claims into the live loop (the engine and claims exist and are
  tested; `run()` still ends on turn count rather than by protocol consensus).
- 6.6 adversarial tamper sweep as an end-to-end regression pack.
- **Interop decision (Intel I1 closed as unobtainable):** the reference's exact
  serialization was never extractable — its published samples are internally
  inconsistent (a `state` string whose coordinates contradict the record's own
  `position`, on a board where they cannot exist) and elide the fields required to
  recompute a digest. We therefore use our own scheme, `canonical-json-v1`, and declare
  it explicitly at handshake so an opponent can match or refuse it before play begins.

## Risk posture
Local integrity is complete and tested; cross-team audit interop is the open risk
(RESEARCH-REPORT §7).
