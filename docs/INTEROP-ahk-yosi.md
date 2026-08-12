# Interoperability audit — Orcai-MJ vs Team ahk-yosi

Opponent repos (read-only inspection, 2026-08-12):

* police: https://github.com/yosefshanaa/p2p-police-agent @ `8413c732877c8220d20e9fa5a54dfcb41d97b8ae`
* thief:  https://github.com/yosefshanaa/p2p-thief-agent @ `35b457b3b29d72fcc3e899925398a6d0e0e5abfb`

Both of their repos are the identical `p2p_pursuit` codebase differentiated by a
one-line `ROLE` file. Both of ours are the identical `police_thief` codebase
differentiated by private config.

## Dialect determination (not guessed)

* **Their native dialect**: 4-phase request/response tools `handshake`,
  `receive_commit`, `receive_reveal`, `receive_event`, `audit_exchange`
  (`p2p_pursuit/infra/mcp_server.py`).
* **Their reference-compat dialect**: push-and-inbox tools `negotiate`,
  `receive_turn`, `submit_audit`, `receive_control`
  (`infra/interop_bridge.py`, enabled via `[interop] dialect="reference"` /
  `P2P_DIALECT=reference`). Their RUNBOOK 3b documents a full six-sub-game
  series against a reference-derived peer passing all audits with
  `alternate_roles=true`, `handshake_per_sub_game=true`, `claim_enclosure=false`.
* **Our dialect before this work**: a reference-*derived* single-game peer
  (tools `receive_move`, `handshake`; commit = SHA256 of canonical JSON
  `{state,move,intent,nonce}` — scheme `canonical-json-v1`). Neither of their
  dialects verbatim: **"other"**.
* **Negotiated dialect for this match**: their **reference** dialect. We add the
  reference tool surface + digest to our engine (`police_thief/interop/`);
  they set `P2P_DIALECT=reference`, `P2P_ALTERNATE_ROLES=1`,
  `P2P_HANDSHAKE_PER_SUB_GAME=1`, `P2P_CLAIM_ENCLOSURE=0` — the exact
  configuration their own RUNBOOK prescribes and has battle-tested.

## Compatibility matrix

| Area | Theirs (p2p_pursuit) | Ours (police_thief) before | Resolution (implemented in `police_thief/interop/`) |
|---|---|---|---|
| MCP transport | FastMCP, HTTP, stateless mode on | FastMCP, HTTP | Same framework; compatible |
| `/mcp` endpoint | `http://host:port/mcp` | same | identical |
| Handshake | reference dialect: each side pushes `negotiate` `{terms, nonce, signature, identity}`; terms compared by dict equality; `signature = sha256(canonical(terms)+"|"+nonce)` | request/response `handshake` payload w/ `config_sha256`, `sealing_scheme` | We implement push-and-inbox `negotiate` with their exact terms vocabulary (`interop_codec.interop_terms`) |
| Contract hashing | `sha256(json.dumps(game.json_dict, sort_keys=True, separators=(",",":"), ensure_ascii=False))` = `3835f6a1…aac443` | same formula (`ensure_ascii` default True — equal for this ASCII file) | game.json adopted byte-for-byte; regression test pins the hash |
| Serialization | canonical JSON: sorted keys, `(",",":")`, UTF-8, `ensure_ascii=False` | same but `ensure_ascii=True` | interop layer uses `ensure_ascii=False` exactly |
| Role strings | `"police"` / `"thief"` | same | identical |
| Sub-game numbers | 1–6; **not carried on the reference wire** — sync by re-negotiation boundary | n/a (single game) | local counter, lockstep advance after audit window |
| Six-game series | `run_series` loops 1..num_games; counted requires exactly 6 | local self-play only | full networked series implemented |
| First mover | thief, every sub-game | thief (structural) | thief opens each sub-game |
| Timeout | turn 180 s; response 30 s ×(3 retries+5 s backoff); audit wait ≤20 s at re-handshake boundary; re-negotiate window ~60 s | 30 s single wait | 180 s turn wait; audit sent immediately at sub-game end; ≤20 s wait for theirs; 60 s agreement wait |
| Commit | reference: `sha256(canonical(payload) + b"\|" + nonce_utf8)`; hash rides ON the turn message; move/positions/intent/nonce sealed until audit | `sha256(canonical({state,move,intent,nonce}))` | reference formula implemented (`refcrypto.reference_commit`); payload includes `step` + `position` their auditor reads |
| Acknowledgement | tool return `{"ok": true}` acks/locks the pushed turn | `{"status":"ok","acknowledged_commit":…}` | we return `{"ok": true}` from `receive_turn` |
| Reveal | end-of-sub-game `submit_audit` reveals `{payload, nonce, commit}` per step | disclosure dict of our records | reference envelope implemented |
| Nonce handling | 16-byte hex, secret until `submit_audit` | same generation | identical; disclosed only in final audit |
| Canonical JSON | sorted keys, `(",",":")` | same | identical |
| SHA-256 | hashlib hexdigest | same | identical |
| Commit golden vector | — | — | pinned test (see `tests/test_interop_crypto.py`) |
| Barrier placement | declared as `barrier_placed=[r,c]` on the turn; quota 14; adjacency settled at audit | `barrier` field, quota guard `accept_barrier` | wire field mapped; same quota rule |
| Enclosure (§3.4) | implemented, but **negotiated off** vs reference peers (`claim_enclosure=false`) because an unmodified reference peer cannot answer it (their RUNBOOK measured desync 2026-08-01) | thief-trapped rule exists in local rules only | claim_enclosure negotiated **false** both sides; captures end via capture-claim/answer; nobody claims enclosure; tests assert no double-report |
| Capture claims | police: `capture_claim=[r,c]` on the turn; thief must answer next turn `claim_response={"claim":[r,c],"caught":bool}` (unsealed side-channel) | claim `[r,c]`; response `{type,step,confirmed,position}` | wire response translated to their exact `{"claim","caught"}` shape; inbound accepts both |
| Win claims | thief survival → `win_claim={"type":"survival_claim"}` (from `KIND_SURVIVAL_CLAIM`), **no step field**; their thief may also push `{"type":"captured_event"}` (rules #46/#47 confession) | only `{"type":"survival","step":n}` understood | inbound: `survival`/`survival_claim` confirmed against *our count of their steps* ≥ threshold; `captured_event`/`captured` → capture, winner police. Outbound: we send `{"type":"survival","step":n}` (their bridge reads only `type`, validates via their own step count) |
| Scent emission | fixed 5×5 kernel (Fig. 4 values), `min(0.9, 0.9·τ+Δτ)`, round 4 digits, dust floor 0.001, **serve BEFORE the step's emission** | Gaussian `0.9·e^(−0.375·d²)` (reproduces Fig. 4 ±0.01), clamp at 0.9, prune < 1e-3, no rounding, **serve AFTER emission+decay** | **Known, declared divergence.** Contract-fixed params (ρ=0.10, centre 0.9, 5×5) identical. In the reference dialect scent is advisory (belief input) and is NOT cross-audited (`interop_audit.py` explicitly skips it), so no protocol failure. Golden-vector test pins OUR formula; divergence reported to opponent in Q&A |
| Scent serving order | pre-emission field | post-emission field | see above — declared, not silently adopted |
| Scent rounding / dust floor | 4 decimals / 0.001→0.0 | none / prune <1e-3 | see above |
| Final nonce disclosure | `submit_audit` `{sender, records:[{payload,nonce,commit}], result_claim}` | log disclosure | implemented exactly |
| Final audit | of us they verify: (1) each record hash-binds; (2) every live commit revealed; (3) trajectory continuity (`payload["position"]`), on-board (`infra/interop_audit.py`) | hash chain + move chain + scent P0–3 | our records satisfy all three; our audit of them mirrors the same three checks plus barrier quota, over their `pos_after` chain |
| Result serialization | `report/results.py` — `result_sha256 = sha256(canonical(body))`; endings `capture/survival/technical_loss`; winners `police/thief/none`; series winner `police/thief/tie` | Table-20 artifacts, different schema | our interop result artifact uses the same ending/winner strings and a canonical `result_sha256`; each side files its own result (per #35 both teams report separately) — byte-identical cross-team result files are NOT required by either implementation |
| Result digest/signature | `digest(body)` canonical JSON | `canonical_sha256` | same construction; golden-vector test |
| Role alternation | `role_for`: natural role on odd sub-games, opposite on even (`peer/series_protocol.py`) | none | same function implemented + tests |
| Renegotiation frequency | once per sub-game (`handshake_per_sub_game=true` for reference peers) | once per match | per sub-game implemented |
| Reconnect/recovery | inbound agreement queued anytime, consumed at next boundary; audit missing after wait ⇒ `"no package received"`, series still advances; watchdog persists state | none | same policy: bounded waits, deterministic advance, no infinite restart loop |
| Index disagreement | wire carries no sub-game index; boundaries are the negotiate exchanges; their duplicate terminal flush re-sends the last turn (same step) with `win_claim` attached | n/a | duplicate-step messages processed for claims only, never as movement; queued turns between boundaries belong to the next sub-game; tests cover it |
| Friendly reporting | `email_mode=draft` writes local file, never sends | same (`mode="draft"`) | friendly mode structurally cannot construct a sender (hard guard + test) |
| Counted reporting | `mode="send"` via Gmail API to configured recipient | same | counted requires explicit confirmation + friendly gate + hash + endpoint checks (launcher) |

## Fixed-spec cross-check

`police_thief_p2p.pdf` is not present in either team's repository or locally;
the binding minimums from the book that our loader enforces
(`shared/config.py BOOK_MINIMUMS`: grid ≥7, barriers ≥14, moves ≥35,
survival ≥35) all hold in the adopted constitution. Scoring 20/5/5/10/2,
ρ=0.10, centre 0.9, 5×5 field match both codebases' book citations.

## Open, explicitly-declared divergences (no silent adoption)

1. **Scent serving order + rounding** — see matrix row. Advisory data in this
   dialect; each side's own formula is locked by its `scent_model` declaration.
2. **Unsealed side-channels** — their protocol carries `claim_response` and
   `win_claim` outside the commitment (their own docs acknowledge this). We
   follow the wire format and record outcomes as protocol consensus.
