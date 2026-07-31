"""PeerRuntime — one independent peer's turn loop (Book Ch. 8; reference peer/runtime.py).

Loop:  wait green -> think -> move -> seal -> send -> verify -> wait

GamePhaseMachine makes an illegal jump a loud dev-time bug, never a silent deadlock;
apply_move falls back to HOLD so the loop never stalls; the move is sealed before it is
revealed; and inbound envelopes earn a strike rather than crashing us.
"""
from __future__ import annotations

import logging

from police_thief.domain.brains import Decision, MoveType, Role
from police_thief.domain.protocol import TurnMessage, build_turn_message
from police_thief.domain.smell import ScentGrid
from police_thief.domain.state_machine import GamePhaseMachine
from police_thief.exceptions import ProtocolViolation
from police_thief.peer.claims import (answer_claims, good_faith_capture_claim,
                                      survival_claim)
from police_thief.peer.hint_policy import weigh as weigh_hint
from police_thief.peer.receive import accept_barrier
from police_thief.peer.sealing import sealed_record
from police_thief.peer.violations import ViolationLog


class PeerRuntime:
    """Owns state, belief, scent, records, transport, and the phase machine for one peer."""

    def __init__(self, role: Role, brain, transport, state, belief, config: dict,
                 talker=None) -> None:
        self.role = role
        self.brain = brain
        self.transport = transport
        self.state = state
        self.belief = belief
        self.config = config
        self.talker = talker           # optional verbal layer (TemplateProvider etc.)
        self.phases = GamePhaseMachine()
        self.records: list[dict] = []
        self.last_opponent_hint = ""
        self.trust_ema = 0.5           # opponent verbal credibility, EMA alpha 0.3
        self.last_hint_verdict = None  # feeds the sealed record's verdict field (6.1)
        self.violations = ViolationLog()   # opponent protocol strikes (evidence trail)
        self.outcome = None                # set once terminal consensus is reached
        self._pending_response = None      # answer owed to the opponent's claim
        self.opponent_scents: list = []    # their broadcasts, kept for the P0-3 audit
        self.my_scent_history: list = []   # ours, disclosed at the final audit
        self.start_position = tuple(state.position)
        # Scent parameters come from the SIGNED pheromones block; book values as fallback.
        self.my_scent = ScentGrid(
            state.board.grid_size,
            center_intensity=config.get("pheromones.pheromone_center_intensity", 0.9),
            decay_rate=config.get("pheromones.pheromone_decay", 0.10),
            field_size=config.get("pheromones.pheromone_grid_size", 5),
        )

    def on_opponent_turn(self, msg_dict: dict) -> dict:
        """Receive handler (wired as mcp_server's on_turn): the opponent MOVED
        (diffuse the belief) and only then left evidence (fuse their scent).
        A malformed envelope is rejected with a reason and a strike, never a
        crash. The ack locks the opponent's commitment (commit-reveal stage 2)."""
        try:
            msg = TurnMessage.from_dict(msg_dict)
        except ProtocolViolation as exc:
            return self.violations.reject(str(exc), msg_dict, self.phases)
        if msg.barrier is not None:
            refusal = accept_barrier(self.state, tuple(msg.barrier),
                                     self.config.get("rules.barriers_max", 14))
            if refusal:
                return self.violations.reject(refusal, msg_dict, self.phases)
        self.belief.diffuse(barriers=self.state.barriers)
        if msg.scent:
            self.belief.update_from_smell(msg.scent)
        self.opponent_scents.append(dict(msg.scent))
        self._pending_response, outcome = answer_claims(
            msg, self.state.position, len(self.records),
            self.config.get("rules.survival_threshold", 35))
        self.outcome = self.outcome or outcome
        self._weigh_hint(msg)
        self.last_opponent_hint = msg.hint
        return {"status": "ok", "acknowledged_commit": msg.commit}

    @property
    def is_over(self) -> bool:      # terminal consensus reached (task 6.3)
        return self.outcome is not None
    def _weigh_hint(self, msg) -> None:
        """Judge the claim against the speaker's own scent and update trust (Ch. 4).
        Policy lives in peer/hint_policy.py — see it for the truth/lie asymmetry."""
        self.trust_ema, self.last_hint_verdict = weigh_hint(
            self.belief, msg.hint, msg.scent, self.state.board.grid_size, self.trust_ema)

    def run_turn(self, opponent_hint: str | None = None) -> "object":
        if opponent_hint is None:                  # default: the hint we last received
            opponent_hint = self.last_opponent_hint
        barriers_max = self.config.get("rules.barriers_max", 14)

        # think
        self.phases.transition("COMPUTING_MOVE")
        decision = self.brain.decide(self.state, self.belief, opponent_hint,
                                     self.config.get("play.setting"), barriers_max)

        # Barrier placement is the cop's privilege alone (Ch. 3) — degrade, never obey.
        if self.role is Role.THIEF and decision.move_type is MoveType.BARRIER:
            logging.getLogger(__name__).warning(
                "thief brain attempted BARRIER — illegal, degraded to HOLD")
            decision = Decision(MoveType.HOLD, None, hint=decision.hint)

        # verbal layer (never touches the move — Rule 25)
        if self.talker is not None:
            threat = self.state.board.distance(self.state.position,
                                               self.belief.most_likely())
            intent = self.talker.pick_intent(threat)
            decision = Decision(decision.move_type, decision.direction,
                                hint=self.talker.produce(self.state.position, intent),
                                bluff=(intent == "lie"))

        # never stall; remember any wall we build so we can DECLARE it (Rule 15)
        walls_before = set(self.state.barriers)
        if not self.state.apply_move(decision.move_type, decision.direction, barriers_max):
            self.state.apply_move(MoveType.HOLD, None)
        placed = self.state.barriers - walls_before

        # seal
        self.phases.transition("COMMITTING")
        record = sealed_record(self.state, decision, step=len(self.records) + 1)
        self.records.append(record)
        h_commit = record["commit"]

        # presence emits from the POST-move cell, then the field ages (reference order)
        self.my_scent.deposit(self.state.position)
        self.my_scent.decay_all()
        self.my_scent_history.append(self.my_scent.snapshot())

        # send
        threshold = self.config.get("rules.survival_threshold", 35)
        message = build_turn_message(
            self.role.value, decision.hint, self.my_scent.snapshot(), h_commit,
            good_faith_capture_claim(self.role, self.state.position, self.belief,
                                     decision.move_type),
            claim_response=self._pending_response,
            win_claim=survival_claim(self.role, len(self.records), threshold),
            barrier=(list(placed.pop()) if placed else None))
        self._pending_response = None
        self.phases.transition("AWAITING_REVEAL")
        self.transport.send_turn(message.to_dict())

        # verify (opponent's reveal validated here in Stage 6) then hand the turn back
        self.phases.transition("VERIFYING")
        self.phases.transition("WAITING_FOR_OPPONENT")
        return message
