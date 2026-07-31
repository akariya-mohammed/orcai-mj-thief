"""Task 5.2: config loader — JSON (signed) over TOML (private), dotted access,
reference-namespace aliases, canonical hash, binding-minimum enforcement."""
import pytest

from police_thief.shared.config import Config, canonical_sha256

SHARED = {
    "board_and_agents": {"grid_size": 7, "thief_start": [3, 3], "cop_start": [0, 0]},
    "world": {"map_area": "New York", "hint_max_words": 15},
    "movement_and_barriers": {"max_barriers": 14, "max_moves": 35, "survival_threshold": 35},
    "pheromones": {"pheromone_center_intensity": 0.9, "pheromone_decay": 0.10,
                   "pheromone_grid_size": 5},
}
PRIVATE = {
    "network": {"my_port": 8802, "opponent_url": "http://127.0.0.1:8801/mcp"},
    "world": {"map_area": "Paris"},          # illegal private override of a signed term
}


def test_dotted_access_on_real_paths():
    cfg = Config(SHARED, PRIVATE)
    assert cfg.get("pheromones.pheromone_decay") == 0.10
    assert cfg.get("movement_and_barriers.max_barriers") == 14


def test_reference_namespace_aliases():
    # The reference's dotted names (Batch A/B corroborated) must resolve too.
    cfg = Config(SHARED, PRIVATE)
    assert cfg.get("board.size") == 7
    assert cfg.get("smell.emit_intensity") == 0.9
    assert cfg.get("smell.decay_per_step") == 0.10
    assert cfg.get("rules.barriers_max") == 14
    assert cfg.get("rules.max_steps") == 35
    assert cfg.get("positions.thief_start") == [3, 3]
    assert cfg.get("play.hint_max_words") == 15


def test_signed_json_beats_private_toml_on_shared_keys():
    # The private file may NEVER weaken/override a signed term (book appendix ב).
    cfg = Config(SHARED, PRIVATE)
    assert cfg.get("play.setting") == "New York"       # not Paris


def test_private_only_keys_resolve():
    cfg = Config(SHARED, PRIVATE)
    assert cfg.get("network.my_port") == 8802


def test_missing_key_returns_default():
    cfg = Config(SHARED, {})
    assert cfg.get("llm.model", "template") == "template"


def test_canonical_hash_stable_across_key_order():
    a = {"x": 1, "y": {"b": 2, "a": 3}}
    b = {"y": {"a": 3, "b": 2}, "x": 1}
    assert canonical_sha256(a) == canonical_sha256(b)
    assert len(canonical_sha256(a)) == 64


def test_config_sha256_covers_the_shared_contract():
    assert Config(SHARED, {}).config_sha256() == canonical_sha256(SHARED)
    assert Config(SHARED, PRIVATE).config_sha256() == Config(SHARED, {}).config_sha256()


def test_binding_minimum_enforced():
    bad = {**SHARED, "board_and_agents": {**SHARED["board_and_agents"], "grid_size": 5}}
    with pytest.raises(ValueError):
        Config(bad, {})


def test_load_reads_repo_defaults_without_private_file(tmp_path, monkeypatch):
    monkeypatch.chdir("c:/ai orc/final-project")
    cfg = Config.load()                                 # game.toml absent -> shared only
    assert cfg.get("board.size") == 7
