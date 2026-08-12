"""Reference-dialect MCP surface: our server tools + the client link.

Push-and-inbox transport: every tool returns ``{"ok": true}`` immediately and
the reply arrives later as a separate call into the OTHER peer's server. The
handlers therefore only enqueue; all game logic runs on the series thread.

The server runs stateless HTTP so a client that posts tool calls without an
MCP session id still reaches us (the opponent's peer does the same and their
RUNBOOK documents why: a stateful server 400s such clients into a forfeit).
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any


class Inbox:
    """Thread-safe queues the MCP handlers push into and the series loop drains."""

    def __init__(self) -> None:
        self.agreements: queue.Queue = queue.Queue()
        self.turns: queue.Queue = queue.Queue()
        self.audits: queue.Queue = queue.Queue()

    # -- tool handlers (must return fast; opponent enforces a deadline) ------
    def on_negotiate(self, message: dict) -> dict:
        self.agreements.put(message)
        return {"ok": True}

    def on_receive_turn(self, message: dict) -> dict:
        self.turns.put(message)
        return {"ok": True}

    def on_submit_audit(self, payload: dict) -> dict:
        self.audits.put(payload)
        return {"ok": True}

    def on_receive_control(self, message: dict) -> dict:
        return {"ok": True}


def build_interop_server(name: str, inbox: Inbox, *, host: str = "0.0.0.0",
                         port: int = 8801):
    """FastMCP server exposing the reference tool names, wired to the inbox."""
    from fastmcp import FastMCP  # lazy: importable without the dependency

    mcp = FastMCP(name)

    @mcp.tool
    def negotiate(message: dict) -> dict:
        """Reference dialect: the opponent's signed game agreement."""
        return inbox.on_negotiate(message)

    @mcp.tool
    def receive_turn(message: dict) -> dict:
        """Reference dialect: one whole turn (commit hash + public reveal)."""
        return inbox.on_receive_turn(message)

    @mcp.tool
    def submit_audit(payload: dict) -> dict:
        """Reference dialect: end-of-sub-game reveal of records and nonces."""
        return inbox.on_submit_audit(payload)

    @mcp.tool
    def receive_control(message: dict) -> dict:
        """Advisory control signal — accepted so the opponent is never stalled."""
        return inbox.on_receive_control(message)

    @mcp.tool
    def health_check() -> dict:
        """Liveness probe."""
        return {"ok": True}

    def run() -> None:
        mcp.run(transport="http", host=host, port=port, show_banner=False,
                stateless_http=True)

    return mcp, run


def serve_in_thread(name: str, inbox: Inbox, *, host: str = "0.0.0.0",
                    port: int) -> threading.Thread:
    _, run = build_interop_server(name, inbox, host=host, port=port)
    thread = threading.Thread(target=run, name=f"interop-mcp-{port}", daemon=True)
    thread.start()
    return thread


class LinkError(RuntimeError):
    pass


class RefLink:
    """Sync client over the opponent's reference-dialect tools, with retries."""

    def __init__(self, url: str, *, timeout: float = 30.0, retries: int = 3,
                 backoff: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    def _call_once(self, tool: str, args: dict, timeout: float) -> dict:
        from fastmcp import Client  # lazy

        async def go() -> Any:
            async with Client(self.url, timeout=timeout) as client:
                result = await client.call_tool(tool, args, timeout=timeout)
                if getattr(result, "data", None) is not None:
                    return result.data
                for block in getattr(result, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        return json.loads(text)
                return {}

        return asyncio.run(go())

    def call(self, tool: str, args: dict, timeout: float | None = None) -> dict:
        deadline = timeout or self.timeout
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._call_once(tool, args, deadline)
            except Exception as exc:  # noqa: BLE001 — normalize transport failures
                last = exc
                if attempt < self.retries:
                    time.sleep(self.backoff)
        raise LinkError(f"{tool} failed against {self.url}: {last}") from last

    def list_tools(self, timeout: float | None = None) -> list[str]:
        from fastmcp import Client

        async def go() -> list[str]:
            async with Client(self.url, timeout=timeout or self.timeout) as client:
                return [tool.name for tool in await client.list_tools()]

        try:
            return asyncio.run(go())
        except Exception as exc:
            raise LinkError(f"list_tools failed against {self.url}: {exc}") from exc

    def reachable(self) -> bool:
        try:
            return bool(self.list_tools(timeout=5))
        except LinkError:
            return False

    # -- reference tool surface ----------------------------------------------
    def negotiate(self, signed: dict, timeout: float | None = None) -> dict:
        return self.call("negotiate", {"message": signed}, timeout)

    def receive_turn(self, message: dict, timeout: float | None = None) -> dict:
        return self.call("receive_turn", {"message": message}, timeout)

    def submit_audit(self, payload: dict, timeout: float | None = None) -> dict:
        return self.call("submit_audit", {"payload": payload}, timeout)
