"""FastMCP client — calls the opponent's server (Book Ch. 2; task 5.1 fix).

fastmcp's Client is ASYNC; our runtime is synchronous by design (one turn at a
time is the game's nature). send_turn bridges the boundary with asyncio.run per
call — one network call per turn, so a fresh event loop per send is fine and
keeps the runtime free of async plumbing. Must never be called from inside a
running event loop (we don't have one).

fastmcp is imported lazily so this module imports without the dependency.
"""
from __future__ import annotations

import asyncio


class OpponentLink:
    """Thin sync client over the opponent's MCP endpoint."""

    def __init__(self, opponent_url: str) -> None:
        self.opponent_url = opponent_url

    def call(self, tool: str, args: dict) -> dict:
        """Invoke one tool on the opponent's server (sync bridge over the async client)."""
        from fastmcp import Client  # lazy

        async def _call() -> dict:
            async with Client(self.opponent_url) as client:
                result = await client.call_tool(tool, args)
                # fastmcp 2.x returns a CallToolResult-like object; unwrap its data.
                return getattr(result, "data", result)

        return asyncio.run(_call())

    def send_turn(self, message: dict) -> dict:
        """Deliver a turn message to the opponent and return their acknowledgement."""
        return self.call("receive_move", {"message": message})
