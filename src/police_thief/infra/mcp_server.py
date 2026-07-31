"""FastMCP server — each peer runs its own (local truth, Book Ch. 2).

Every agent is simultaneously a server (exposes a tool the opponent calls) and a client.
The opponent, acting as a client, calls `receive_move` to submit a signed turn message;
we accept it after verifying the commitment.

fastmcp is imported lazily so this module (and the tests) import without the dependency.
"""
from __future__ import annotations

from typing import Callable


def build_server(name: str, on_turn: Callable[[dict], dict],
                 on_handshake: Callable[[dict], dict] | None = None,
                 host: str = "0.0.0.0", port: int = 8000):
    """Create a FastMCP server exposing `receive_move` (and optionally `handshake`).

    on_turn(message: dict) -> dict        # validate, apply, acknowledge a turn
    on_handshake(payload: dict) -> dict   # pre-game contract verification (task 5.3)
    """
    from fastmcp import FastMCP  # lazy: keeps the module importable without fastmcp

    mcp = FastMCP(name)

    @mcp.tool
    def receive_move(message: dict) -> dict:
        """Opponent submits a turn message; we hand it to the peer runtime and acknowledge."""
        return on_turn(message)

    if on_handshake is not None:
        @mcp.tool
        def handshake(payload: dict) -> dict:
            """Exchange config signatures + identities before turn 1 (Rule 11)."""
            return on_handshake(payload)

    def run() -> None:
        # Bind so a tunnel (ngrok/Localtonet) can expose it publicly for the league (Stage 5).
        mcp.run(transport="http", host=host, port=port)

    return mcp, run
