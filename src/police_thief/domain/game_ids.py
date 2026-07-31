"""Game identity (task 5.3; artifact naming per book Table 20).

Both peers must derive the SAME identifiers with zero clock coordination, so the
uid is a pure function of (the two group ids, order-independent) + the shared
config signature. Distinct rematches within a series are distinguished by
sub_game_number in the artifact filenames (config_<game_id>_g<NN>.json etc.).
"""
from __future__ import annotations

import hashlib


def make_game_id(group_a: str, group_b: str) -> str:
    return f"{group_a}-vs-{group_b}"


def make_game_uid(group_a: str, group_b: str, config_sha256: str) -> str:
    material = "|".join(sorted((group_a, group_b))) + "|" + config_sha256
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def artifact_filenames(game_id: str, sub_game: int) -> dict[str, str]:
    """Book Table 20: declaration/result are per-game, config/log per sub-game."""
    return {
        "declaration": f"declaration_{game_id}.json",
        "config": f"config_{game_id}_g{sub_game:02d}.json",
        "log": f"log_{game_id}_g{sub_game:02d}.json",
        "result": f"result_{game_id}.json",
    }
