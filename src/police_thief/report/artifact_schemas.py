"""Authoritative field lists for the 4 output artifacts + the sealed-record payload.

Verbatim field names from the reference (report/artifacts.py, artifact_helpers.py, and the
sample-run logs). The builders in report_writer.py must emit exactly these keys — a grader
(and the opponent's audit) expects them. Each file name derives from game_uid/game_id/<NN>.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.2"

# ── declaration_<game_id>.json — pre-game, cryptographically signed ──────────
DECLARATION_FIELDS = [
    "_schema", "schema_version", "declaration_type",   # "pre_game_declaration"
    "game_id", "game_uid", "links", "timezone",
    "game_started_at", "game_ended_at",
    "num_sub_games", "max_tokens_per_game",
    "groups",  # {"group_1": GROUP_BLOCK, "group_2": GROUP_BLOCK}
]
GROUP_BLOCK_FIELDS = [
    "group_id", "group_name", "members", "repos",
    "mcp_servers", "llm_model", "hardware_spec",
]

# ── config_<game_id>_g<NN>.json — the agreed terms overlaid + signed ─────────
# Body = ALL shared_terms blocks from config/game.json spread at top level.
# (Batch-B intel listed six blocks with "like" — non-exhaustive; our signed
# contract also carries world (map_area, hint_max_words are negotiated terms)
# and agreed_between, so they belong in the signed artifact too.)
SHARED_TERMS_KEYS = [
    "schema_version", "agreed_between",
    "board_and_agents", "world", "movement_and_barriers", "scoring",
    "pheromones", "network_and_league", "rate_limiter_gatekeeper",
]
CONFIG_FIELDS = [
    "_schema", *SHARED_TERMS_KEYS,
    "schema_version", "game_id", "game_uid", "sub_game_number",
    "links", "config_name",
    "config_sha256",  # canonical_sha256(shared_terms) — both peers must match
]

# ── log_<game_id>_g<NN>.json — per-step records for the replay audit ─────────
LOG_SUMMARY_FIELDS = [
    "sub_game_number", "group_id", "role", "opponent_group_id",
    "result", "winner_role", "steps", "timezone",
    "started_at", "ended_at", "duration_seconds", "tokens_total", "audit",
]
LOG_FIELDS = [
    "_schema", "schema_version", "game_id", "game_uid", "links",
    "summary",   # LOG_SUMMARY_FIELDS
    "records",   # list of sealed step records (payload + commit + nonce revealed at audit)
    "mutual_agreement",  # {opponent_group_id, sha256: consensus_signature(records), confirmed}
]

# ── result_<game_id>.json — final series result the grader scores ────────────
RESULT_FIELDS = [
    "_schema", "schema_version", "report_type",   # "final_game_result"
    "game_id", "game_uid", "links", "timezone",
    "groups", "num_sub_games", "sub_games",
    "final_result",       # {**aggregate_out, "tokens_total_series": ...}
    "mutual_agreement",   # {sha256, confirmed}
]

# ── Sealed-record payload — TWO shapes (goes into the SHA-256 with a hidden nonce) ──
STEP0_PAYLOAD_FIELDS = [
    "step",  # 0
    "type",  # "system_spec"
    "spec",  # {os, cpu_type, cpu_cores, cpu_freq_mhz, ram_gb, gpu_type, gpu_cores_or_cuda, vram_gb}
    "model", "code_version", "group_name", "sub_game_number",
]
STEP0_SPEC_FIELDS = [
    "os", "cpu_type", "cpu_cores", "cpu_freq_mhz",
    "ram_gb", "gpu_type", "gpu_cores_or_cuda", "vram_gb",
]
MOVE_PAYLOAD_FIELDS = [
    "step",
    "state",        # e.g. "grid=7x7;self=[r, c];barriers=[]"
    "position",     # [row, col]
    "move",         # e.g. "MOVE:S"
    "intent",       # "truth" | "lie"  (honesty flag committed up front)
    "verdict",      # bluff classification of the hint
    "hint",         # free-text verbal hint (may be a bluff)
    "prompt_discussion",  # {llm_prompt, llm_reasoning, bluff_classification}
    "model", "tokens_step", "tokens_total", "response_seconds", "random_move",
]

# TODO (Batch C follow-up): get peer/sealing.py `sealed_step_record` + how record["commit"]
# is computed, to pin the EXACT hash preimage (payload subset + nonce serialization).
