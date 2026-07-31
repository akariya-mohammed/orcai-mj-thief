# PRD 2 — FastMCP Infrastructure

**Goal:** split the two agents into independent processes that talk over MCP. Prove a message
leaves one peer and arrives, correctly decoded, at the other — before loading it with real content.

## Scope
- Each peer runs its own `FastMCP` server exposing one tool, `receive_move` (`infra/mcp_server.py`).
- Each peer is also a client that calls the opponent's `receive_move` (`infra/mcp_client.py`).
- `domain/protocol.py` — the `TurnMessage` (`build_turn_message` / `to_dict` / `from_dict`).
- `peer/runtime.py` — the turn loop, with `GamePhaseMachine` enforcing legal phase order.
- Localhost only at this stage; the public tunnel is Stage 5.

## Design notes (per reference)
- Every peer is **both** server and client — symmetric, no "strong/weak" side.
- The commit-reveal split means the turn message carries the sealed `commit` + verbal `hint`,
  not the move/nonce (revealed later). No bare coordinates as the move (Rule 27).
- `apply_move` returns `False` on an illegal move → runtime falls back to `HOLD` ("never stall").
- There is **no central Orchestrator** (Rule 1/2); the per-peer gateway is `SimulationSdk`.

## Milestone gate
- Automated: `TurnMessage` round-trips (`to_dict`→`from_dict`) and a full phase cycle runs
  (`WAITING → COMPUTING → COMMITTING → AWAITING_REVEAL → VERIFYING → WAITING`) — `tests/test_protocol.py`.
- Manual (live): start two processes on localhost; a move from A is decoded correctly by B.
