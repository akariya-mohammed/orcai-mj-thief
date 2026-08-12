"""Agreed-terms vocabulary + signed agreement for the reference negotiate exchange.

The opponent's peer compares terms by exact dict equality
(`p2p_pursuit/infra/interop_codec.py interop_terms` / `handshake_from_agreement`),
so every key and value here must match their mapping of the SAME game.json
field-for-field. The agreement is signed with the reference commitment:
``signature = sha256(canonical(terms) + b"|" + nonce)``.
"""
from __future__ import annotations

from typing import Any

from police_thief.interop.refcrypto import new_nonce, reference_commit


def build_terms(config, num_games: int) -> dict[str, Any]:
    """Our constitution expressed in the reference agreed-terms vocabulary."""
    ph = config.get("pheromones", {})
    return {
        "board_size": config.get("board.size", 7),
        "smell_grid_size": ph.get("pheromone_grid_size", 5),
        "decay_per_step": ph.get("pheromone_decay", 0.10),
        "emit_intensity": ph.get("pheromone_center_intensity", 0.9),
        "min_center_intensity": ph.get("pheromone_min_center_intensity", 0.5),
        "max_steps": config.get("rules.max_steps", 35),
        "barriers_max": config.get("rules.barriers_max", 14),
        "setting": config.get("play.setting", ""),
        "hint_max_words": config.get("play.hint_max_words", 15),
        "axis_origin_corner": config.get("board.axis_origin_corner", "top-left"),
        "axis_start_index": config.get("board.axis_start_index", 0),
        "thief_start": list(config.get("positions.thief_start", (3, 3))),
        "cop_start": list(config.get("positions.cop_start", (0, 0))),
        "num_games": num_games,
    }


def build_identity(config, *, mcp_url: str, prior_counted_games: int = 0,
                   code_version: str = "") -> dict[str, Any]:
    """Group identity block their `handshake_from_agreement` / reporting reads."""
    game = (config.private or {}).get("game", {})
    return {
        "group_id": game.get("group_id", "orcai-mj"),
        "group_name": game.get("group_name", "Orcai-MJ"),
        "members": list(game.get("members", [])),
        "repos": dict(game.get("repos", {})),
        "mcp_servers": {"cop": mcp_url, "thief": mcp_url},
        "llm_model": "template",
        "code_version": code_version,
        "prior_counted_games": prior_counted_games,
        "spec": {},
    }


def signed_agreement(terms: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    nonce = new_nonce()
    return {"terms": dict(terms), "nonce": nonce,
            "signature": reference_commit(terms, nonce),
            "identity": dict(identity)}


def evaluate_agreement(agreement: dict[str, Any],
                       my_terms: dict[str, Any]) -> tuple[bool, str]:
    """(accepted, reason). Terms must match exactly and the signature must verify."""
    if not isinstance(agreement, dict):
        return False, "agreement is not an object"
    theirs = agreement.get("terms")
    if theirs != my_terms:
        diff = sorted(
            k for k in set(my_terms) | set(theirs or {})
            if not isinstance(theirs, dict) or theirs.get(k) != my_terms.get(k))
        return False, f"terms mismatch on {diff}"
    signed = reference_commit(theirs, str(agreement.get("nonce", ""))) \
        == agreement.get("signature")
    if not signed:
        return False, "agreement signature does not verify"
    return True, "ok"
