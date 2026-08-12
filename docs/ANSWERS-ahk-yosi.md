# Orcai-MJ — answers to Team ahk-yosi's 10 questions

All answers derive from the code that will actually play
(branch `interop/ahk-yosi`, package `police_thief`, module `police_thief/interop/`).

## 1. Our /mcp endpoint

Generated at runtime by our launcher (`scripts/play_ahk_yosi.ps1 friendly`),
which opens a Cloudflare quick tunnel and prints
`SEND THIS TO YOSEF: https://<random>.trycloudflare.com/mcp`.
There is no permanent endpoint; we will send the live URL when we start the
friendly. Our server is FastMCP over HTTP, path `/mcp`, stateless HTTP
(no MCP session id required).

## 2. Dialect

Our engine is reference-derived ("other" historically: tools `receive_move` /
`handshake`, scheme `canonical-json-v1`). **For this match we speak your
reference dialect natively**: tools `negotiate`, `receive_turn`,
`submit_audit`, `receive_control`. Please run your side with:

```
P2P_DIALECT=reference
P2P_ALTERNATE_ROLES=1
P2P_HANDSHAKE_PER_SUB_GAME=1
P2P_CLAIM_ENCLOSURE=0
```

(the exact configuration your RUNBOOK 3b prescribes for reference-derived
peers — verified against your public implementation locally).

## 3. Roles

Roles **alternate**: natural role on odd sub-games (1,3,5), opposite on even
(2,4,6) — same `role_for` as yours. Handshake (the signed-agreement exchange
via `negotiate`) happens **before every sub-game**: once at series start and a
fresh exchange before each of sub-games 2–6.

## 4. Enclosure

Negotiated per your defaults for this pairing: **claim_enclosure = false on
both sides** — nobody announces §3.4 enclosure. Terminal conditions are
reported by exactly one side each:
* capture — the police side claims via `capture_claim=[r,c]` on its turn; the
  thief answers truthfully on its next message with
  `claim_response={"claim":[r,c],"caught":bool}`;
* survival — the thief side claims via `win_claim={"type":"survival","step":n}`
  at ≥ 35 of its own steps;
* your thief's `captured_event` confession (rule #46/#47) is understood and
  ends the sub-game as capture / police;
* a barrier-capture ending your engine records on receive (cause
  "barrier onto (r,c)") has no turn-message channel in this dialect — we treat
  your `submit_audit` package's `result_claim` as the terminal signal, so both
  sides converge without waiting out a turn timeout.

## 5. Commit golden vector

Formula: `commit = sha256( canonical_json(payload) + b"|" + nonce_utf8 )`,
canonical JSON = sorted keys, separators `(",", ":")`, `ensure_ascii=False`,
UTF-8. Nonce: 32 hex chars (16 bytes), private until `submit_audit`.

* payload:
  `{"kind":"step","role":"police","sub_game":1,"step":1,"position":[1,0],"move":"MOVE:S","barrier":null,"intent":"truth","hint":"golden"}`
* canonical bytes:
  `{"barrier":null,"hint":"golden","intent":"truth","kind":"step","move":"MOVE:S","position":[1,0],"role":"police","step":1,"sub_game":1}`
* nonce: `00112233445566778899aabbccddeeff`
* SHA-256 commit:
  `9896089baad1e3ef87214d04ab397828c4f8e1b8c1db034648110cd48aaca90a`

Audit reveal envelope per step: `{"payload": ..., "nonce": ..., "commit": ...}`;
payloads carry `step` and `position` for your trajectory audit.

## 6. Scent

Contract-locked parameters are identical to yours: centre 0.9, rho = 0.10,
5×5 field. Our emission model (declared, not hidden):

* emission: `dtau(d²) = 0.9 · exp(−0.375·d²)` over squared Euclidean distance
  in the 5×5 window — reproduces book Figure 4 (0.90/0.62/0.42/0.20/0.14/0.04)
  within ±0.01; cell values clamped at 0.9;
* decay: `tau ← (1 − 0.10)·tau` once per own turn;
* rounding: none (full float precision on the wire);
* dust floor: values that decay below 1e-3 are pruned to absent;
* serving order: the `smell_grid` on our turn message is the field **after**
  that step's own emission and decay (yours serves pre-emission — a declared
  divergence; in this dialect scent is advisory and not cross-audited, per
  your own `interop_audit.py`).

Numeric golden vector — single deposit at (3,3), 7×7 board:
`tau(3,3)=0.9`, `tau(2,3)=0.618560350911875`, `tau(2,2)=0.4251298974669132`,
`tau(1,3)=0.20081714413358684`, `tau(1,2)=0.13801947016043561`,
`tau(1,1)=0.04480836153107755`; after one decay: `tau(3,3)=0.81`,
`tau(1,1)=0.0403275253779698`.

## 7. Result / signature

Each side files its own result artifact (both teams report separately, #35).
Ours: `result_<natural_role>.json` with
`result_sha256 = sha256(canonical_json(body))` — same canonicalization as the
commit formula (sorted keys, `(",",":")`, `ensure_ascii=False`). Exact strings:
roles `"police"` / `"thief"`; endings `"capture"` / `"survival"` /
`"technical_loss"`; series winner `"police"` / `"thief"` / `"tie"`;
win claims `{"type":"survival","step":n}` outbound, and inbound we accept
`survival`, `survival_claim`, `captured_event`, `captured`.

Golden vector: body
`{"report_type":"game_result","match_mode":"FRIENDLY (UNCOUNTED)","dialect":"reference","totals":{"police":75,"thief":45},"series_winner":"police"}`
→ `result_sha256 = 496e2433b76951c4baf8cbadbb3f6940ef2753bb3c3298e739ea65caf3c44127`.

## 8. Cold start / recovery

* Sub-game index: 1–6, never carried on the wire; boundaries are the
  `negotiate` exchanges; both sides advance in lockstep after the audit
  exchange (we send our audit immediately at sub-game end and wait ≤ 20 s for
  yours, then re-negotiate; agreement wait 60 s).
* Duplicate/terminal-flush turns (same step re-sent with a claim attached) are
  processed for claims only, never as movement.
* At each boundary we drain stale queued turns/audit packages; a new sub-game
  starts with the thief's step 1.
* If your audit never arrives: verdict "no package received", series still
  advances — no infinite restart loop. If a re-handshake fails: that sub-game
  is recorded as technical and the series continues.
* On our process restart mid-series: the series restarts from sub-game 1 (a
  friendly re-run); we do not resume mid-series.

## 9. Prior counted games

**0** (verified: no counted artifacts exist in either of our repositories).

## 10. First mover and timeout

First mover: **thief**, at every sub-game (structural, matches the signed
`board_and_agents.first_mover`). Turn timeout: **180 s** as you proposed
(our per-call transport timeout 30 s with 3 retries / 5 s backoff sits under
it). Constitution: your exact `game.json`, canonical SHA-256
`3835f6a137620d8d98ab3925b2d1ed397d2d20d23bb9ba857bcd104284aac443`,
adopted byte-for-byte and pinned by a regression test in both of our repos.
