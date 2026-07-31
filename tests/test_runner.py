"""Task 5.3: PeerProcess assembly — config -> brains/runtime/link, handshake wiring,
turn-order structure. The live threaded run() is the manual two-terminal gate."""
from police_thief.shared.config import Config
from police_thief.peer.runner import PeerProcess
from police_thief.strategy.heuristic import RingRunnerThief
from police_thief.strategy.trapping import TrapperPolice

SHARED = {
    "board_and_agents": {"grid_size": 7, "thief_start": [3, 3], "cop_start": [0, 0]},
    "world": {"map_area": "New York", "hint_max_words": 15},
    "movement_and_barriers": {"max_barriers": 14, "max_moves": 35, "survival_threshold": 35},
    "pheromones": {"pheromone_center_intensity": 0.9, "pheromone_decay": 0.10,
                   "pheromone_grid_size": 5},
}


def _proc(role, **private):
    base = {"game": {"group_id": f"team-{role}"},
            "network": {"my_port": 8801, "opponent_url": "http://127.0.0.1:8802/mcp"}}
    base.update(private)
    return PeerProcess(role, Config(SHARED, base))


def test_assembly_selects_role_appropriate_brain_and_start():
    police, thief = _proc("police"), _proc("thief")
    assert isinstance(police.runtime.brain, TrapperPolice)
    assert isinstance(thief.runtime.brain, RingRunnerThief)   # red-team winner
    assert police.runtime.state.position == (0, 0)
    assert thief.runtime.state.position == (3, 3)


def test_private_belief_tuning_reaches_the_grid():
    p = _proc("police", belief={"smell_trust_weight": 2.5})
    assert p.runtime.belief.trust == 2.5


def test_handshake_payload_carries_the_config_signature():
    p = _proc("police")
    payload = p.handshake_payload()
    assert payload["config_sha256"] == p.config.config_sha256()
    assert payload["role"] == "police" and payload["group_id"] == "team-police"


def test_on_handshake_accepts_matching_peer_and_agrees_game_uid():
    police, thief = _proc("police"), _proc("thief")
    reply = police.on_handshake(thief.handshake_payload())
    assert reply["accepted"] is True
    reply2 = thief.on_handshake(police.handshake_payload())
    assert reply2["accepted"] is True
    assert police.game_uid == thief.game_uid          # identical on both sides


def test_on_handshake_rejects_config_mismatch():
    police = _proc("police")
    bad = _proc("thief").handshake_payload() | {"config_sha256": "f" * 64}
    reply = police.on_handshake(bad)
    assert reply["accepted"] is False and "config" in reply["reason"].lower()


def test_turn_order_is_structural():
    # Thief initiates; police waits for the first incoming TurnMessage (Intel I3).
    assert _proc("thief").acts_first is True
    assert _proc("police").acts_first is False


def test_on_turn_delegates_and_signals():
    police = _proc("police")
    msg = {"role": "thief", "commit": "c" * 64, "hint": "", "scent": {},
           "capture_claim": None, "claim_response": None, "win_claim": None}
    ack = police._on_turn(msg)
    assert ack["acknowledged_commit"] == "c" * 64
    assert police.turn_ready.is_set()                  # the game loop can wake up
