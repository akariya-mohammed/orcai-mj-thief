"""End-to-end demonstration of a complete match, phase by phase.

Shows the full lifecycle a league game actually follows:
  1. handshake + Step-0 sealing   2. the turn loop on the wire
  3. termination by consensus     4. the post-game mutual audit

Run: uv run python scripts/demo_match.py
"""
from __future__ import annotations

import json

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Role
from police_thief.domain.negotiation import evaluate
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.protocol import TurnMessage
from police_thief.domain.termination import CAPTURE, SURVIVAL
from police_thief.peer.finish import deliver_verdict, disclosure, finalize
from police_thief.peer.runtime import PeerRuntime
from police_thief.peer.sealing import SEALING_SCHEME, step_zero_record
from police_thief.strategy.heuristic import RingRunnerThief
from police_thief.strategy.trapping import TrapperPolice

CFG = {"rules.barriers_max": 14, "rules.survival_threshold": 35,
       "pheromones": {"pheromone_center_intensity": 0.9, "pheromone_decay": 0.10,
                      "pheromone_grid_size": 5}, "board.size": 7}


class Wire:
    """A real wire: every message is serialized and handed to the other peer."""
    def __init__(self, name):
        self.name, self.other, self.log = name, None, []

    def send_turn(self, message: dict) -> dict:
        self.log.append(json.loads(json.dumps(message)))
        return self.other.on_opponent_turn(self.log[-1])


def rule(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> int:
    board = Board(7)
    wc, wt = Wire("police"), Wire("thief")
    cop = PeerRuntime(Role.POLICE, TrapperPolice(), wc,
                      OwnGameState((0, 0), board), BeliefGrid(7), CFG)
    thief = PeerRuntime(Role.THIEF, RingRunnerThief(), wt,
                        OwnGameState((3, 3), board), BeliefGrid(7), CFG)
    wc.other, wt.other = thief, cop

    rule("1. HANDSHAKE & STEP-0 SEALING")
    z = {r: step_zero_record(f"orcai-mj-{r}", "template") for r in ("police", "thief")}
    payloads = {r: {"config_sha256": "c" * 64, "group_id": f"orcai-mj-{r}", "role": r,
                    "code_version": z[r]["payload"]["code_version"],
                    "step0_commit": z[r]["commit"], "sealing_scheme": SEALING_SCHEME}
                for r in ("police", "thief")}
    for r in ("police", "thief"):
        spec = z[r]["payload"]["spec"]
        print(f"  {r:<7} step-0 sealed  {z[r]['commit'][:24]}…")
        print(f"          machine: {spec['os']}, {spec['cpu_cores']} cores, "
              f"gpu={spec['gpu_type'][:26]}")
        print(f"          code commit: {z[r]['payload']['code_version'][:12]}  "
              f"scheme: {SEALING_SCHEME}")
    ok, reason = evaluate(payloads["police"], payloads["thief"])
    print(f"  contract check -> accepted={ok} ({reason}); thief moves first")

    rule("2. TURN LOOP ON THE WIRE")
    step = 0
    while not (cop.is_over or thief.is_over) and step < 35:
        step += 1
        thief.run_turn()
        if cop.is_over or thief.is_over:
            break
        cop.run_turn()
        if step <= 3 or step % 12 == 0:
            m = TurnMessage.from_dict(wc.log[-1])
            print(f"  step {step:>2} cop->thief  commit={m.commit[:16]}…  "
                  f"scent={len(m.scent):>2} cells  barrier={m.barrier}  "
                  f"claim={m.capture_claim}")
            print(f"          hint={m.hint[:44]!r}")

    rule("3. TERMINATION BY CONSENSUS")
    # Whoever CONFIRMED owes the answer; delivering it is what tells the claimant.
    for peer in (cop, thief):
        if deliver_verdict(peer):
            print(f"  {peer.role.value} confirmed the claim and delivered the verdict")
    outcome = cop.outcome or thief.outcome
    kind = "capture (cop wins)" if outcome["type"] == CAPTURE else "survival (thief wins)"
    print(f"  claim raised and CONFIRMED at step {outcome['step']}")
    print(f"  GAME OVER by consensus: {kind}")
    print(f"  both peers agree: cop={cop.outcome is not None} thief={thief.outcome is not None}")

    rule("4. POST-GAME MUTUAL AUDIT (nonces revealed here for the first time)")
    for me, them, label in ((cop, thief, "police audits thief"),
                            (thief, cop, "thief audits police")):
        verdict = finalize(me, disclosure(them, f"orcai-mj-{them.role.value}"),
                           config=CFG, out_dir="logs", game_uid="demo-uid")
        a = verdict["audit"]
        print(f"  {label:<22} passed={a['passed']}  "
              f"records={a['checked']['records']}  scent snapshots={a['checked']['broadcasts']}"
              f"  failures={len(a['failures'])}")
        print(f"  {'':<22} evidence -> {verdict['evidence_path']}")
    print("\n  Layers verified: digest chain · move-chain legality · P0-3 scent history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
