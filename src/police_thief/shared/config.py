"""Config loader (task 5.2). Zero third-party deps (tomllib is stdlib, 3.11+).

Two layers, one precedence rule:
- SHARED  config/game.json — the signed contract, byte-identical between peers.
- PRIVATE config/game.toml — this peer only (port, opponent_url, [llm], [belief]...).
On any shared key the SIGNED value wins: the private file may never weaken the
contract (book appendix ב). Dotted access resolves the real game.json paths AND
the reference implementation's dotted namespace (corroborated by Batch A/B intel)
via an alias map, so brains/runtime can use either vocabulary.

canonical_sha256(shared) is the config signature exchanged in the handshake
(task 5.3): same canonical JSON as domain/crypto.py — sorted keys, tight
separators — so both peers hash byte-identical input.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

# Binding minimums (book appendix ו): raise only by mutual agreement, NEVER lower.
BOOK_MINIMUMS = {
    "board_and_agents.grid_size": 7,
    "movement_and_barriers.max_barriers": 14,
    "movement_and_barriers.max_moves": 35,
    "movement_and_barriers.survival_threshold": 35,
}

# Reference dotted namespace -> signed game.json path.
ALIASES = {
    "board.size": "board_and_agents.grid_size",
    "board.axis_origin_corner": "board_and_agents.axis_origin_corner",
    "board.axis_start_index": "board_and_agents.axis_start_index",
    "positions.thief_start": "board_and_agents.thief_start",
    "positions.cop_start": "board_and_agents.cop_start",
    "smell.grid_size": "pheromones.pheromone_grid_size",
    "smell.decay_per_step": "pheromones.pheromone_decay",
    "smell.emit_intensity": "pheromones.pheromone_center_intensity",
    "rules.max_steps": "movement_and_barriers.max_moves",
    "rules.barriers_max": "movement_and_barriers.max_barriers",
    "rules.survival_threshold": "movement_and_barriers.survival_threshold",
    "play.setting": "world.map_area",
    "play.hint_max_words": "world.hint_max_words",
    "game.num_games": "network_and_league.num_games",
}


def canonical_sha256(obj) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Config:
    def __init__(self, shared: dict, private: dict | None = None) -> None:
        self.shared = shared
        self.private = private or {}
        self._validate()

    @classmethod
    def load(cls, shared_path: str = "config/game.json",
             private_path: str = "config/game.toml") -> "Config":
        shared = json.loads(Path(shared_path).read_text(encoding="utf-8"))
        private = {}
        p = Path(private_path)
        if p.exists():
            private = tomllib.loads(p.read_text(encoding="utf-8"))
        return cls(shared, private)

    @staticmethod
    def _resolve(tree: dict, dotted: str):
        node = tree
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None, False
            node = node[part]
        return node, True

    def get(self, key: str, default=None):
        key = ALIASES.get(key, key)
        value, found = self._resolve(self.shared, key)   # signed contract wins
        if found:
            return value
        value, found = self._resolve(self.private, key)
        if found:
            return value
        return default

    def config_sha256(self) -> str:
        """Signature of the SHARED contract only — private config never crosses the wire."""
        return canonical_sha256(self.shared)

    def _validate(self) -> None:
        for dotted, floor in BOOK_MINIMUMS.items():
            value, found = self._resolve(self.shared, dotted)
            if found and value < floor:
                raise ValueError(f"{dotted}={value} is below the binding minimum {floor}")
