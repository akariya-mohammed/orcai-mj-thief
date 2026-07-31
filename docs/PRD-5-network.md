# PRD 5 — Network: Config, Transport, Handshake, Reliability (retro)

**Goal:** turn the components into a living peer process talking real MCP over HTTP.

## Delivered
- `shared/config.py` — signed JSON over private TOML (contract can never be weakened),
  dotted access + reference-namespace aliases, canonical config signature, binding
  minimums enforced at load.
- `infra/mcp_client.py` — sync→async bridge (`asyncio.run` per call, `.data` unwrap);
  generalized `call(tool, args)`.
- `peer/handshake.py` + `domain/negotiation.py` — contract-hash verification, role
  conflict/missing-field rejection, thief-moves-first, clock-free game-uid.
- `peer/runner.py` — `PeerProcess` assembly + CLI `peer` (+ `--gui`); per-role configs
  committed under `config/police|thief/`.
- `peer/watchdog.py` — DeadlineTracker + Watchdog; `WAITING→TECHNICAL_LOSS` edge;
  persisted audit snapshot on timeout.

## Gate (met — live)
Two real processes on fastmcp **3.4.5** (localhost 8801/8802): handshake mutually
verified (identical contract hash + identical independently-derived game uid), thief
moved first, 5 sealed turn exchanges, trust EMA 0.65→0.88. Zero transport fixes needed.

## Open
5.4 public tunnel (ngrok) — user-operated, required only for cross-machine league play.
