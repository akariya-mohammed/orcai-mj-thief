"""Client side of the pre-game handshake (task 5.3).

Retries while the opponent's server is still starting (the two terminals are
launched by hand, in any order); a DEFINITIVE rejection (config mismatch, role
conflict) raises immediately — never retry a refused contract.
"""
from __future__ import annotations

import time

from police_thief.exceptions import HandshakeRejected


def perform_handshake(link, my_payload: dict, attempts: int = 30,
                      delay: float = 1.0) -> dict:
    """Call the opponent's `handshake` tool until accepted; return their reply."""
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            reply = link.call("handshake", {"payload": my_payload})
            if isinstance(reply, dict) and reply.get("accepted"):
                return reply
            raise HandshakeRejected(str((reply or {}).get("reason", "no reason given")))
        except HandshakeRejected:
            raise                                  # definitive: do not retry
        except Exception as exc:                   # peer not up yet / transient network
            last_error = exc
            time.sleep(delay)
    raise TimeoutError(f"opponent unreachable after {attempts} attempts: {last_error}")
