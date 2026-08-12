"""Reference-dialect interoperability layer (match vs Team ahk-yosi).

Speaks the reference implementation's wire protocol — the dialect the opponent's
`p2p_pursuit` peer bridges to with `[interop] dialect = "reference"`:

* tools `negotiate` / `receive_turn` / `submit_audit` / `receive_control`;
* commit = ``sha256(canonical_json(payload) + b"|" + nonce)``;
* one TurnMessage per turn carrying the commit hash and the public reveal;
* full reveal ({payload, nonce, commit} per step) at the end-of-sub-game audit;
* six sub-games, alternating roles, re-negotiation before every sub-game.

See docs/INTEROP-ahk-yosi.md for the full compatibility matrix.
"""
