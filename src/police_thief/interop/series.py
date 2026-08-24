"""Six-sub-game networked series in the reference dialect.

One `ReferenceSeriesPeer` is a full autonomous peer: MCP server (negotiate /
receive_turn / submit_audit / receive_control), outbound RefLink, role
alternation (natural role on odd sub-games), per-sub-game re-negotiation,
thief-first turn order, commit-on-the-turn + reveal-at-audit sealing, mutual
end-of-sub-game audit, deterministic boundary recovery and friendly/counted
separation.

Timing contract (matches the opponent's measured windows, RUNBOOK 3b):
after a sub-game ends we send our audit package immediately, wait at most
AUDIT_WAIT (20 s) for theirs, then re-negotiate — their peer allows ~60 s for
our agreement to arrive.
"""
from __future__ import annotations

import json
import queue
import random
import time
from datetime import UTC, datetime
from pathlib import Path

from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Decision, MoveType
from police_thief.domain.game_ids import make_game_id, make_game_uid
from police_thief.domain.own_state import OwnGameState
from police_thief.domain.smell import ScentGrid
from police_thief.exceptions import ProtocolViolation
from police_thief.interop import consensus, refaudit, wire
from police_thief.interop import najamjad as najamjad_mod
from police_thief.interop import terms as terms_mod
from police_thief.interop.mcp import Inbox, LinkError, RefLink, serve_in_thread
from police_thief.interop.refcrypto import digest, mutual_digest, seal
from police_thief.peer.hint_policy import weigh as weigh_hint
from police_thief.peer.receive import accept_barrier
from police_thief.peer.sealing import move_str
from police_thief.strategy.heuristic import RingRunnerThief
from police_thief.strategy.trapping import TrapperPolice
from police_thief.strategy.trash_talk import TemplateProvider

POLICE, THIEF = "police", "thief"
CAPTURE, SURVIVAL, TECHNICAL_LOSS = "capture", "survival", "technical_loss"

FRIENDLY, COUNTED = "friendly", "counted"
FRIENDLY_LABEL = "FRIENDLY (UNCOUNTED)"
SCHEMA_VERSION = "1.2"

# amireman public-spec reporting recipients (Section 12 dispatch). Friendly
# reports go to the team; counted reports go to the league address. The two
# never cross over (a friendly must never reach the lecturer, and vice-versa).
AMIREMAN_FRIENDLY_RECIPIENT = "judekhleif@gmail.com"

# NajAmjad §7.4: counted goes to the lecturer from each team separately;
# friendlies go to the two teams ONLY — never the lecturer. Dispatch itself
# lives in the POST-MATCH aggregator (interop/najamjad_report.py); the
# gameplay peer never emails for this profile.
NAJAMJAD_FRIENDLY_RECIPIENT = najamjad_mod.FRIENDLY_RECIPIENT

AUDIT_WAIT = 20.0          # their REHANDSHAKE_AUDIT_WAIT
AGREEMENT_WAIT = 60.0      # their re-negotiate window
DEFAULT_TURN_TIMEOUT = 180.0


def role_for(natural: str, sub_game: int) -> str:
    """Natural role on odd sub-games, the opposite on even ones (reference rule)."""
    if sub_game % 2 == 1:
        return natural
    return THIEF if natural == POLICE else POLICE


def other(role: str) -> str:
    return THIEF if role == POLICE else POLICE


def score_for(ending: str, scoring: dict) -> tuple[int, int]:
    """(police_score, thief_score) for one sub-game ending."""
    if ending == CAPTURE:
        return scoring.get("capture_cop", 20), scoring.get("capture_thief", 5)
    if ending == SURVIVAL:
        return scoring.get("survival_cop", 5), scoring.get("survival_thief", 10)
    return (scoring.get("technical_loss", 0),) * 2


class SubGame:
    """Local truth for one sub-game: state, belief, scent, sealed records, claims."""

    def __init__(self, my_role: str, config, sub_game: int, seed: int,
                 spec_profile: str = "ahk-yosi") -> None:
        self.my_role = my_role
        self.n = sub_game
        self.config = config
        self.spec_profile = spec_profile
        size = config.get("board.size", 7)
        key = "cop_start" if my_role == POLICE else "thief_start"
        start = tuple(config.get(f"positions.{key}",
                                 (0, 0) if my_role == POLICE else (3, 3)))
        self.state = OwnGameState(start, Board(size))
        self.belief = BeliefGrid(size, config.get("belief.smell_trust_weight", 4.0))
        scent_cls = (najamjad_mod.KernelScentGrid
                     if spec_profile == "najamjad" else ScentGrid)
        # NajAmjad §4.0: the A2 kernel must go on the wire cell-for-cell —
        # the exact registered table with max-merge, never our Gaussian fit.
        # initial_field is empty for EVERY agreed window, first attempt or
        # re-offer, because each attempt constructs a fresh SubGame.
        self.scent = scent_cls(
            size,
            center_intensity=config.get("pheromones.pheromone_center_intensity", 0.9),
            decay_rate=config.get("pheromones.pheromone_decay", 0.10),
            field_size=config.get("pheromones.pheromone_grid_size", 5))
        if my_role == POLICE:
            # NajAmjad Barrier Law: never a barrier on the thief's occupied cell.
            self.brain = TrapperPolice(
                forbid_barrier_on_thief=(spec_profile == "najamjad"))
        else:
            self.brain = RingRunnerThief()
        self.talker = TemplateProvider(size, random.Random(seed))
        self.records: list[dict] = []       # sealed {payload, nonce, commit}
        self.opp_commits: list[str] = []    # commitments witnessed live
        self.my_steps = 0
        self.opp_steps = 0
        self.last_opp_step = 0
        self.owed_claim_response: dict | None = None
        self.outcome: dict | None = None
        self.captured = False               # rule #46/#47: bars a survival claim
        self.last_opp_hint = ""
        self.trust_ema = 0.5
        self.opp_scents: list[dict] = []
        self.my_scent_history: list[dict] = []
        self.last_sent: dict | None = None
        self.violations: list[str] = []

    # -- outbound ------------------------------------------------------------
    def build_my_turn(self) -> dict:
        """Think, move, seal (reference digest), emit scent, assemble the message."""
        barriers_max = self.config.get("rules.barriers_max", 14)
        threshold = self.config.get("rules.survival_threshold", 35)
        decision = self.brain.decide(self.state, self.belief, self.last_opp_hint,
                                     self.config.get("play.setting"), barriers_max)
        if self.my_role == THIEF and decision.move_type is MoveType.BARRIER:
            decision = Decision(MoveType.HOLD, None, hint=decision.hint)
        if self.captured:
            # Rule #46/#47: a captured thief may not walk off the capturing
            # barrier. Hold, keep emitting scent, and truthfully confirm the
            # capture claim the opponent will eventually place.
            decision = Decision(MoveType.HOLD, None, hint=decision.hint)
        threat = self.state.board.distance(self.state.position,
                                           self.belief.most_likely())
        intent = self.talker.pick_intent(threat)
        hint = self.talker.produce(self.state.position, intent)
        decision = Decision(decision.move_type, decision.direction, hint=hint,
                            bluff=(intent == "lie"))

        walls_before = set(self.state.barriers)
        if not self.state.apply_move(decision.move_type, decision.direction,
                                     barriers_max):
            self.state.apply_move(MoveType.HOLD, None)
        placed = self.state.barriers - walls_before
        barrier = list(placed.pop()) if placed else None

        step = self.my_steps + 1
        payload = {"kind": "step", "role": self.my_role, "sub_game": self.n,
                   "step": step, "position": list(self.state.position),
                   "move": move_str(decision), "barrier": barrier,
                   "intent": intent, "hint": hint}
        record = seal(payload)
        self.records.append(record)
        self.my_steps = step

        if self.spec_profile == "najamjad":
            # Serve order per their §4.0.1 (the kit's field_walk): age the
            # PRIOR trail first, merge the fresh deposit at FULL strength,
            # then transmit — the packet's peak is always 0.90 on the cell we
            # occupy and every older cell already carries this turn's decay.
            self.scent.decay_all()
            self.scent.deposit(self.state.position)
        else:
            # ahk-yosi / amireman convention (unchanged): deposit then decay
            # before the snapshot. Left exactly as those opponents verified it.
            self.scent.deposit(self.state.position)
            self.scent.decay_all()
        snapshot = self.scent.snapshot()
        self.my_scent_history.append(dict(snapshot))

        capture_claim = None
        if self.my_role == POLICE:
            if self.spec_profile == "amireman":
                # Spec Section 5: the Cop declares a capture-claim for its own
                # post-move cell on EVERY Cop turn — including STAY and barrier
                # turns — with no gating and never chosen by strategy.
                capture_claim = list(self.state.position)
            elif decision.move_type is MoveType.MOVE and \
                    tuple(self.state.position) == tuple(self.belief.most_likely()):
                # ahk-yosi dialect (p2p_pursuit): claim only when we step onto
                # the believed cell. Left unchanged so that path keeps verifying.
                capture_claim = list(self.state.position)

        win_claim = None
        if self.my_role == THIEF and step >= threshold and not self.captured:
            # Spec Appendix D: the survival claim is exactly {"type": "survival"}.
            # The ahk-yosi dialect additionally carries the step field.
            win_claim = ({"type": SURVIVAL} if self.spec_profile == "amireman"
                         else {"type": SURVIVAL, "step": step})
            self.outcome = {"ending": SURVIVAL, "winner": THIEF, "step": step,
                            "cause": f"survived {step} steps"}

        message = wire.build_turn(
            step=step, sender=self.my_role, hint=hint, scent=snapshot,
            commit=record["commit"], barrier=barrier, capture_claim=capture_claim,
            claim_response=self.owed_claim_response, win_claim=win_claim)
        self.owed_claim_response = None
        self.last_sent = message
        return message

    def courtesy_flush(self) -> dict | None:
        """The answer we still owe after a terminal turn — re-sent on a copy of
        our last message (the reference deliver_verdict convention)."""
        if not self.owed_claim_response:
            return None
        base = dict(self.last_sent) if self.last_sent else wire.build_turn(
            step=self.my_steps, sender=self.my_role, hint="", scent={},
            commit=self.records[-1]["commit"] if self.records else "0" * 64)
        base["claim_response"] = self.owed_claim_response
        base["timestamp"] = datetime.now(UTC).isoformat()
        base["win_claim"] = None
        base["capture_claim"] = None
        self.owed_claim_response = None
        return base

    # -- inbound ---------------------------------------------------------------
    def process_opp_turn(self, parsed: dict) -> None:
        """Apply one opponent turn: physics first, then claims. A repeated step
        (their terminal flush) is processed for claims only, never as movement."""
        threshold = self.config.get("rules.survival_threshold", 35)
        duplicate = parsed["step"] <= self.last_opp_step
        if not duplicate:
            self.last_opp_step = parsed["step"]
            self.opp_steps = max(self.opp_steps, parsed["step"])
            self.opp_commits.append(parsed["commit"])
            if parsed["barrier"] is not None:
                if (self.spec_profile == "najamjad" and self.my_role == THIEF
                        and tuple(parsed["barrier"]) == tuple(self.state.position)):
                    # NajAmjad Barrier Law: a barrier NEVER goes on the cell
                    # the thief occupies. Not a capture for this opponent — a
                    # violation we record, and we do not apply the wall.
                    self.violations.append(
                        f"opponent declared a barrier on our occupied cell "
                        f"{parsed['barrier']} — forbidden by the agreed "
                        f"Barrier Law; not applied")
                else:
                    refusal = accept_barrier(self.state, tuple(parsed["barrier"]),
                                             self.config.get("rules.barriers_max", 14))
                    if refusal:
                        self.violations.append(refusal)
            self.belief.diffuse(barriers=self.state.barriers)
            if parsed["scent"]:
                self.belief.update_from_smell(parsed["scent"])
            self.opp_scents.append(dict(parsed["scent"]))
            self.trust_ema, _ = weigh_hint(self.belief, parsed["hint"],
                                           parsed["scent"],
                                           self.state.board.grid_size,
                                           self.trust_ema)
            self.last_opp_hint = parsed["hint"]
            if self.my_role == THIEF and not self.captured:
                on_barrier = tuple(self.state.position) in self.state.barriers
                enclosed = not self.state.board.legal_moves(self.state.position)
                if self.spec_profile == "najamjad":
                    # NajAmjad: barrier-on-cell is never legal (handled above),
                    # so ONLY rule 47 (no legal orthogonal move) captures us —
                    # and we truthfully concede on our own next answer.
                    on_barrier = False
                if on_barrier or enclosed:
                    # Rules #46/#47: we are captured. The reference wire has no
                    # sealed confession, but an unprompted truthful
                    # claim_response ends the opponent's game as a capture
                    # (their bridge accepts it as an unsealed answer) — the
                    # honest, converging channel. Never claim survival now.
                    self.captured = True
                    cause = ("barrier onto our cell" if on_barrier
                             else "enclosed — no legal move")
                    self.owed_claim_response = {
                        "claim": list(self.state.position), "caught": True}
                    self.outcome = {"ending": CAPTURE, "winner": POLICE,
                                    "step": parsed["step"],
                                    "cause": f"{cause} (rule #46/#47 confession)"}

        if parsed["capture_claim"] is not None:
            cell = parsed["capture_claim"]
            caught = tuple(cell) == tuple(self.state.position)
            self.owed_claim_response = {"claim": list(cell), "caught": caught}
            if caught:
                self.outcome = {"ending": CAPTURE, "winner": POLICE,
                                "step": parsed["step"],
                                "cause": f"capture claim confirmed at {list(cell)}"}

        response = parsed["claim_response"]
        if isinstance(response, dict):
            caught = response.get("caught", response.get("confirmed"))
            if caught and self.my_role == POLICE:
                self.outcome = {"ending": CAPTURE, "winner": POLICE,
                                "step": parsed["step"],
                                "cause": f"claim answered caught at "
                                         f"{response.get('claim')}"}

        claim = parsed["win_claim"]
        if isinstance(claim, dict) and self.outcome is None:
            kind = str(claim.get("type", ""))
            if kind in wire.SURVIVAL_KINDS:
                if self.opp_steps >= threshold:
                    self.outcome = {"ending": SURVIVAL, "winner": THIEF,
                                    "step": self.opp_steps,
                                    "cause": f"{kind} at {self.opp_steps} steps"}
                else:
                    self.outcome = {"ending": TECHNICAL_LOSS, "winner": self.my_role,
                                    "step": self.opp_steps,
                                    "cause": f"false survival claim at "
                                             f"{self.opp_steps} steps "
                                             f"(threshold {threshold})"}
            elif kind in wire.CAPTURED_KINDS:
                self.outcome = {"ending": CAPTURE, "winner": POLICE,
                                "step": parsed["step"],
                                "cause": f"opponent confessed {kind}"}

    def declare_technical(self, cause: str, winner: str | None = None) -> None:
        self.outcome = {"ending": TECHNICAL_LOSS,
                        "winner": winner or self.my_role,
                        "step": max(self.my_steps, self.opp_steps), "cause": cause}

    def accept_result_claim(self, claim: str) -> None:
        """The opponent's audit package arrived mid-game: in the reference
        dialect a barrier-capture ending has NO turn-message channel (measured
        live vs p2p_pursuit 2026-08-12) — the audit package IS the terminal
        signal. Adopt the claimed result when it is consistent with local truth,
        else record the disagreement as a technical ending.
        """
        threshold = self.config.get("rules.survival_threshold", 35)
        step = max(self.my_steps, self.opp_steps)
        if claim == CAPTURE and (self.my_role == POLICE or self.captured):
            self.outcome = {"ending": CAPTURE, "winner": POLICE, "step": step,
                            "cause": "opponent's audit package claims capture "
                                     "(concession-by-audit)"}
        elif claim == SURVIVAL and (self.my_role == THIEF
                                    or self.opp_steps >= threshold):
            self.outcome = {"ending": SURVIVAL, "winner": THIEF, "step": step,
                            "cause": "opponent's audit package claims survival"}
        else:
            self.declare_technical(
                f"opponent ended the sub-game claiming {claim!r}, "
                f"inconsistent with our local state")


class ReferenceSeriesPeer:
    """One autonomous peer for a full reference-dialect series."""

    def __init__(self, *, natural_role: str, config, opponent_url: str,
                 my_port: int, num_games: int = 6, mode: str = FRIENDLY,
                 alternate_roles: bool = True, handshake_per_sub_game: bool = True,
                 turn_timeout: float = DEFAULT_TURN_TIMEOUT,
                 agreement_timeout: float = AGREEMENT_WAIT,
                 audit_wait: float = AUDIT_WAIT, out_dir: str = "artifacts/interop",
                 seed: int = 0, mcp_url: str | None = None,
                 prior_counted_games: int = 0, log_fn=print,
                 spec_profile: str = "ahk-yosi", git_commit_hash: str = "",
                 consensus_wait: float | None = None,
                 game_id_override: str | None = None,
                 first_window_role: str = POLICE) -> None:
        if mode not in (FRIENDLY, COUNTED):
            raise ValueError(f"unknown mode {mode!r}")
        if natural_role not in (POLICE, THIEF):
            raise ValueError(f"unknown role {natural_role!r}")
        if spec_profile not in ("ahk-yosi", "amireman", "najamjad"):
            raise ValueError(f"unknown spec_profile {spec_profile!r}")
        if first_window_role not in (POLICE, THIEF):
            raise ValueError(f"unknown first_window_role {first_window_role!r}")
        self.natural_role = natural_role
        self.config = config
        self.num_games = num_games
        self.mode = mode
        self.spec_profile = spec_profile
        self.alternate_roles = alternate_roles
        self.handshake_per_sub_game = handshake_per_sub_game
        self.turn_timeout = turn_timeout
        self.agreement_timeout = agreement_timeout
        self.audit_wait = audit_wait
        self.consensus_wait = consensus_wait if consensus_wait is not None else audit_wait
        self.out_dir = Path(out_dir)
        self.seed = seed
        self.my_port = my_port
        self.log = log_fn
        self.inbox = Inbox()
        self.link = RefLink(opponent_url)
        self.game_id_override = game_id_override
        self.terms = terms_mod.build_terms(config, num_games)
        hw = None
        if spec_profile in ("amireman", "najamjad"):
            from police_thief.shared.sysinfo import detailed_hardware_spec
            hw = detailed_hardware_spec()
        # -- NajAmjad split-process mode (their §3) --------------------------
        # This process plays ONLY its repo's fixed role: cop repo -> police
        # windows against their thief door, thief repo -> thief windows
        # against their cop door. first_window_role is OUR TEAM's role in
        # window 1 (their §1: NajAmjad open as thief, so ours defaults to
        # police). Timing follows their §3.1 table; the window patience is
        # WALL CLOCK, not an attempt count.
        self.first_window_role = first_window_role
        if spec_profile == "najamjad":
            self.my_windows = najamjad_mod.windows_for(
                natural_role, first_window_role, num_games)
            self.audit_wait = najamjad_mod.AUDIT_WAIT
            self.window_patience = najamjad_mod.WINDOW_PATIENCE
        else:
            self.my_windows = list(range(1, num_games + 1))
            self.window_patience = 0.0
        self._current_window: int | None = None    # window now negotiating/playing
        self._mid_game = False                     # responder: busy refusal gate
        self._last_audit_key: str | None = None    # repeated-audit tolerance
        self.identity = terms_mod.build_identity(
            config, mcp_url=mcp_url or f"http://0.0.0.0:{my_port}/mcp",
            prior_counted_games=prior_counted_games,
            git_commit_hash=git_commit_hash, hardware_spec=hw)
        if spec_profile == "najamjad":
            # Two REAL doors, one per role (their §3): the identity must name
            # BOTH our endpoints so their per-role retargeting can dial the
            # right process. Each process's own URL comes from --mcp-url; the
            # sibling's from the private [network] config when declared.
            net = (config.private or {}).get("network", {})
            servers = dict(self.identity.get("mcp_servers", {}))
            own_key = "cop" if natural_role == POLICE else "thief"
            servers[own_key] = mcp_url or servers.get(own_key, "")
            for key, cfg_key in (("cop", "cop_mcp_url"),
                                 ("thief", "thief_mcp_url")):
                if net.get(cfg_key):
                    servers[key] = net[cfg_key]
            self.identity["mcp_servers"] = servers
        self.their_identity: dict = {}
        self.rows: list[dict] = []
        self.mutual_agreement: dict = {}   # spec-profile series consensus outcome
        self._server_thread = None
        # Computed after initial negotiation (game_id requires both group IDs)
        self.game_id: str = ""
        self.game_uid: str = ""
        self.game_started_at: str = ""

    # -- lifecycle -------------------------------------------------------------
    def _najamjad_negotiate_responder(self, message: dict) -> dict:
        """Server-thread reply to an inbound negotiate (NajAmjad §3.1).

        Mid-game -> the retriable busy refusal (their exact convention). A
        ``sub_game_number`` naming a window other than the one we are opening
        -> a retriable refusal that names both numbers (never adopt it). An
        acceptable handshake -> acceptance with OUR signed agreement attached
        in-band under ``agreement``, so a one-directional outbound failure on
        their side still completes the exchange.
        """
        if self._mid_game:
            return najamjad_mod.busy_refusal()
        expected = self._current_window
        named = message.get("sub_game_number") if isinstance(message, dict) else None
        if (isinstance(named, int) and expected is not None
                and named != expected):
            return {"accepted": False, "retriable": True,
                    "errors": [f"sub_game_number {named} does not name the "
                               f"window we are opening ({expected})"]}
        reply = {"ok": True, "accepted": True}
        if expected is not None:
            reply["agreement"] = najamjad_mod.signed_agreement(
                self.terms, self.identity, expected)
        return reply

    def start_server(self) -> None:
        if self.spec_profile == "najamjad":
            self.inbox.negotiate_responder = self._najamjad_negotiate_responder
        self._server_thread = serve_in_thread(
            f"police-thief-interop-{self.natural_role}", self.inbox,
            port=self.my_port)
        self.log(f"[{self.natural_role}] interop MCP server on port {self.my_port} "
                 f"({self.mode.upper()} mode)")

    def wait_for_opponent(self, attempts: int = 150, delay: float = 2.0) -> bool:
        """An agreement already in our inbox is stronger evidence than a probe."""
        for _ in range(attempts):
            if not self.inbox.agreements.empty():
                return True
            if self.link.reachable():
                return True
            time.sleep(delay)
        return False

    # -- boundaries ------------------------------------------------------------
    def negotiate_boundary(self, n: int) -> tuple[bool, str]:
        """Push our signed agreement, wait for theirs, verify terms + signature."""
        agreement = terms_mod.signed_agreement(self.terms, self.identity)
        try:
            self.link.negotiate(agreement)
        except LinkError as exc:
            return False, f"could not deliver agreement: {exc}"
        try:
            theirs = self.inbox.agreements.get(timeout=self.agreement_timeout)
        except queue.Empty:
            return False, "opponent never sent its agreement"
        while not self.inbox.agreements.empty():
            # Their deadline tracker re-pushes the same agreement on retry;
            # always negotiate against the freshest one.
            theirs = self.inbox.agreements.get_nowait()
        accepted, reason = terms_mod.evaluate_agreement(theirs, self.terms)
        if not accepted:
            return False, reason
        self.their_identity = theirs.get("identity", {}) or {}
        return True, "ok"

    def _drain_stale_turns(self) -> None:
        """A new sub-game opens with the thief's step 1; anything else queued at
        the boundary is a stale terminal flush from the previous sub-game.
        A queued audit package is likewise last sub-game's (arrived after our
        wait window) — dropping it here keeps it from reading as a terminal
        signal for the new sub-game."""
        while not self.inbox.audits.empty():
            self.inbox.audits.get_nowait()
        kept: list[dict] = []
        while True:
            try:
                msg = self.inbox.turns.get_nowait()
            except queue.Empty:
                break
            if isinstance(msg, dict) and msg.get("step") == 1:
                kept.append(msg)
                break
        for msg in kept:
            self.inbox.turns.put(msg)

    # -- one sub-game ------------------------------------------------------------
    def play_sub_game(self, n: int) -> dict:
        my_role = role_for(self.natural_role, n) if self.alternate_roles \
            else self.natural_role
        started_at = datetime.now(UTC).isoformat()
        engine = SubGame(my_role, self.config, n, seed=self.seed + n,
                         spec_profile=self.spec_profile)
        self.log(f"[{self.natural_role}] sub-game {n}: playing as {my_role}")

        if n > 1 and self.handshake_per_sub_game:
            ok, reason = self.negotiate_boundary(n)
            if not ok:
                self.log(f"[{self.natural_role}] sub-game {n}: no re-handshake: "
                         f"{reason}")
                engine.declare_technical(f"no re-handshake: {reason}")
                return self._finish_sub_game(engine, n, started_at)
        self._drain_stale_turns()
        self._run_play_loop(engine)
        return self._finish_sub_game(engine, n, started_at)

    def _run_play_loop(self, engine: SubGame) -> None:
        """Thief-first turn loop until a terminal outcome (shared by all profiles)."""
        if engine.my_role == THIEF:                # thief opens every sub-game
            self._send_turn(engine, engine.build_my_turn())
        safety_cap = 4 * self.config.get("rules.max_steps", 35)
        iterations = 0
        while engine.outcome is None and iterations < safety_cap:
            iterations += 1
            parsed = self._await_opponent_turn(engine)
            if parsed is None or engine.outcome is not None:
                break
            engine.process_opp_turn(parsed)
            if engine.outcome is not None:
                break
            self._send_turn(engine, engine.build_my_turn())
        if engine.outcome is None:
            engine.declare_technical("no terminal consensus within the move budget")

        flush = engine.courtesy_flush()
        if flush is not None:
            try:
                self.link.receive_turn(flush)
            except LinkError:
                pass                                # best-effort courtesy message

    def _send_turn(self, engine: SubGame, message: dict) -> None:
        try:
            self.link.receive_turn(message, timeout=self.turn_timeout)
        except LinkError as exc:
            engine.declare_technical(f"no response to our turn: {exc}")

    def _await_opponent_turn(self, engine: SubGame) -> dict | None:
        deadline = time.monotonic() + self.turn_timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if not self.inbox.audits.empty():
                # Their audit package IS the end-of-sub-game signal for endings
                # the reference wire cannot carry (barrier capture). Adopt it
                # and requeue the package for the audit exchange step.
                package = self.inbox.audits.get_nowait()
                if self._is_stale_audit_copy(package, engine.n):
                    # NajAmjad §5: reveals are re-sent up to three times per
                    # window, byte-identical. A straggler copy of the LAST
                    # window's package must never terminate THIS window.
                    continue
                engine.accept_result_claim(str(package.get("result_claim", "")))
                self.inbox.audits.put(package)
                return None
            try:
                raw = self.inbox.turns.get(timeout=min(2.0, max(0.1, remaining)))
            except queue.Empty:
                continue
            try:
                parsed = wire.parse_turn(raw, grid_size=engine.state.board.grid_size)
            except ProtocolViolation as exc:
                engine.violations.append(str(exc))
                continue
            if parsed["sender"] == engine.my_role:
                engine.declare_technical(
                    f"both peers claim role {engine.my_role!r}")
                return None
            return parsed
        engine.declare_technical(f"turn timeout ({self.turn_timeout:.0f}s)")
        return None

    # -- audit + artifacts -------------------------------------------------------
    def _is_stale_audit_copy(self, package: dict, current_n: int) -> bool:
        """Repeated-audit tolerance (NajAmjad profile only).

        A package is stale when it explicitly names an earlier window, or when
        it is byte-identical to the last package we already audited. Other
        profiles keep the historic behavior (boundary drain handles copies).
        """
        if self.spec_profile != "najamjad" or not isinstance(package, dict):
            return False
        for key in ("sub_game_number", "sub_game"):
            named = package.get(key)
            if isinstance(named, int) and named != current_n:
                return True
        try:
            fingerprint = json.dumps(package, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False
        return fingerprint == self._last_audit_key

    def _finish_sub_game(self, engine: SubGame, n: int, started_at: str) -> dict:
        ending = engine.outcome["ending"]
        package = {"sender": engine.my_role, "records": engine.records,
                   "result_claim": ending}
        if self.spec_profile == "najamjad":
            # Index keys they explicitly welcome (§5): they file reveals by
            # window, not by arrival time, and their AuditPayload is tolerant.
            package["sub_game"] = n
            package["sub_game_number"] = n
        sent_ok = True
        try:
            self.link.submit_audit(package)
        except LinkError as exc:
            sent_ok = False
            self.log(f"[{self.natural_role}] sub-game {n}: audit delivery failed: "
                     f"{exc}")
        theirs: dict | None = None
        audit_deadline = time.monotonic() + self.audit_wait
        while theirs is None and time.monotonic() < audit_deadline:
            remaining = max(0.1, audit_deadline - time.monotonic())
            try:
                candidate = self.inbox.audits.get(timeout=remaining)
            except queue.Empty:
                break
            if self._is_stale_audit_copy(candidate, n):
                continue                    # tolerated straggler copy — keep waiting
            theirs = candidate
        if theirs is not None and self.spec_profile == "najamjad":
            try:
                self._last_audit_key = json.dumps(theirs, sort_keys=True,
                                                  default=str)
            except (TypeError, ValueError):
                self._last_audit_key = None
        if theirs is None:
            verdict, violations = "no package received", []
        else:
            verdict, violations = refaudit.audit_reference_log(
                theirs.get("records", []), engine.opp_commits,
                grid_size=engine.state.board.grid_size,
                barriers_max=self.config.get("rules.barriers_max", 14))
            claimed = theirs.get("result_claim")
            if claimed not in (None, "unknown", ending):
                violations = list(violations) + [
                    f"result claims disagree: ours {ending!r}, theirs {claimed!r}"]
                if verdict == refaudit.VERIFIED_OK:
                    verdict = "Verified OK (result claim differs)"
        police_score, thief_score = score_for(ending,
                                              self.config.get("scoring", {}))
        row = {
            "index": n, "my_role": engine.my_role, "ending": ending,
            "winner": engine.outcome["winner"], "cause": engine.outcome["cause"],
            "step": engine.outcome.get("step", 0),
            "police_score": police_score, "thief_score": thief_score,
            "audit_of_opponent": verdict, "audit_violations": violations,
            "audit_delivered": sent_ok,
            "opponent_audit_of_us": "not reported (reference dialect)",
            "protocol_violations": engine.violations,
            # Per-sub-game identity capture (Section 3/12): the commit each side
            # played THIS sub-game. Re-read every handshake; MAY differ per game.
            "started_at": started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "our_commit": (self.identity.get("github_commit") or ""),
            "their_commit": (self.their_identity.get("github_commit")
                             or self.their_identity.get("git_commit_hash") or ""),
            "their_group_id": self.their_identity.get("group_id", ""),
            "result_agreed": (theirs is not None
                              and verdict.startswith(refaudit.VERIFIED_OK)
                              and (theirs.get("result_claim")
                                   in (None, "unknown", ending))),
            "log_verified": (theirs is not None
                             and verdict.startswith(refaudit.VERIFIED_OK)),
        }
        self._write_log(engine, n, row, theirs, started_at)
        self.log(f"[{self.natural_role}] sub-game {n}: {ending} "
                 f"winner={row['winner']} ({row['cause']}) audit={verdict}")
        return row

    def _write_log(self, engine: SubGame, n: int, row: dict,
                   theirs: dict | None, started_at: str) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        ended_at = datetime.now(UTC).isoformat()
        try:
            t1 = datetime.fromisoformat(started_at)
            t2 = datetime.fromisoformat(ended_at)
            duration = round((t2 - t1).total_seconds(), 2)
        except Exception:
            duration = 0.0

        our_repos = self.identity.get("repos", {})
        their_repos = self.their_identity.get("repos", {})
        links: dict = {}
        for k, v in (our_repos or {}).items():
            links[f"group_1_repo_{k}"] = v
        for k, v in (their_repos or {}).items():
            links[f"group_2_repo_{k}"] = v

        summary = {
            "sub_game_number": n,
            "group_id": self.identity.get("group_id", ""),
            "role": engine.my_role,
            "opponent_group_id": self.their_identity.get("group_id", ""),
            "result": row["ending"],
            "winner_role": row["winner"],
            "steps": row["step"],
            "timezone": "UTC",
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration,
            "tokens_total": 0,
            "audit": row["audit_of_opponent"],
        }
        mutual_agreement = {
            "opponent_group_id": self.their_identity.get("group_id", ""),
            "result_claim": (theirs or {}).get("result_claim", ""),
            "confirmed": row["audit_of_opponent"].startswith("Verified OK"),
        }
        log = {
            "_schema": "police_thief_p2p_log_v1.2",
            "schema_version": SCHEMA_VERSION,
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "links": links,
            "summary": summary,
            "records": engine.records,
            "mutual_agreement": mutual_agreement,
            # extended fields for internal audit/replay
            "match_mode": FRIENDLY_LABEL if self.mode == FRIENDLY else "COUNTED",
            "dialect": "reference",
            "sub_game": n, "my_role": engine.my_role,
            "config_sha256": digest(self.config.shared),
            "row": row,
            "my_scent_history": [wire.scent_to_wire(s)
                                 for s in engine.my_scent_history],
            "opponent_records": (theirs or {}).get("records", []),
            "opponent_result_claim": (theirs or {}).get("result_claim"),
        }
        fname = (f"log_{self.game_id}_g{n:02d}.json" if self.game_id
                 else f"log_{self.natural_role}_g{n:02d}.json")
        path = self.out_dir / fname
        path.write_text(json.dumps(log, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    # -- official artifacts --------------------------------------------------
    def _links_dict(self) -> dict:
        our_repos = self.identity.get("repos", {})
        their_repos = self.their_identity.get("repos", {})
        links: dict = {}
        for k, v in (our_repos or {}).items():
            links[f"group_1_repo_{k}"] = v
        for k, v in (their_repos or {}).items():
            links[f"group_2_repo_{k}"] = v
        return links

    def _build_mutual_doc(self) -> dict:
        """Build the shared cross-team outcome document for mutual_agreement.sha256.

        Canonical game_id uses alphabetically sorted group IDs so both teams
        derive the same identifier regardless of which side calls this.
        Aggregate and per-sub-game scores are computed from self.rows.
        Links, local audit data, and all private fields are excluded.
        """
        our_group = self.identity.get("group_id", "orcai-mj")
        their_group = self.their_identity.get("group_id", "") or "opponent"

        groups_sorted = sorted([our_group, their_group])
        canonical_game_id = f"{groups_sorted[0]}-vs-{groups_sorted[1]}"

        group_scores: dict = {our_group: 0, their_group: 0}
        group_wins: dict = {our_group: 0, their_group: 0}
        ties_count = 0
        mutual_sub_games = []

        for row in self.rows:
            my_role = row["my_role"]
            their_role = THIEF if my_role == POLICE else POLICE
            ending = row["ending"]
            winner_role = row["winner"]

            our_score = row["police_score"] if my_role == POLICE else row["thief_score"]
            their_score = row["thief_score"] if my_role == POLICE else row["police_score"]

            if ending == "tie":
                winner_group_id = "tie"
                ties_count += 1
            elif winner_role == my_role:
                winner_group_id = our_group
                group_wins[our_group] += 1
            else:
                winner_group_id = their_group
                group_wins[their_group] += 1

            group_scores[our_group] += our_score
            group_scores[their_group] += their_score

            mutual_sub_games.append({
                "sub_game_number": row["index"],
                "roles": {our_group: my_role, their_group: their_role},
                "result": ending,
                "winner_group": winner_group_id,
                "score": {our_group: our_score, their_group: their_score},
            })

        if group_scores[our_group] > group_scores[their_group]:
            series_winner_group = our_group
            is_series_tie = False
        elif group_scores[their_group] > group_scores[our_group]:
            series_winner_group = their_group
            is_series_tie = False
        else:
            series_winner_group = "tie"
            is_series_tie = True

        return {
            "game_id": canonical_game_id,
            "aggregate": {
                "total_score": dict(group_scores),
                "sub_games_won": dict(group_wins),
                "ties": ties_count,
                "winner_group": series_winner_group,
                "series_tie": is_series_tie,
            },
            "sub_games": mutual_sub_games,
        }

    def _write_declaration(self) -> None:
        """Write declaration_{game_id}.json before the first sub-game."""
        from police_thief.shared.sysinfo import hardware_spec as get_hw
        our_id = self.identity
        their_id = self.their_identity
        declaration = {
            "_schema": "police_thief_p2p_declaration_v1.2",
            "schema_version": SCHEMA_VERSION,
            "declaration_type": "pre_game_declaration",
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "links": self._links_dict(),
            "timezone": "UTC",
            "game_started_at": self.game_started_at,
            "game_ended_at": "",  # filled in build_result()
            "num_sub_games": self.num_games,
            "max_tokens_per_game": self.config.get(
                "network_and_league.token_budget_per_series", 200000),
            "groups": {
                "group_1": {
                    "group_id": our_id.get("group_id", ""),
                    "group_name": our_id.get("group_name", ""),
                    "members": our_id.get("members", []),
                    "repos": our_id.get("repos", {}),
                    "mcp_servers": our_id.get("mcp_servers", {}),
                    "llm_model": our_id.get("llm_model", "template"),
                    "hardware_spec": get_hw(),
                },
                "group_2": {
                    "group_id": their_id.get("group_id", ""),
                    "group_name": their_id.get("group_name", ""),
                    "members": their_id.get("members", []),
                    "repos": their_id.get("repos", {}),
                    "mcp_servers": their_id.get("mcp_servers", {}),
                    "llm_model": their_id.get("llm_model", "unknown"),
                    "hardware_spec": {},
                },
            },
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"declaration_{self.game_id}.json"
        path.write_text(json.dumps(declaration, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        self.log(f"[{self.natural_role}] declaration written -> {path.name}")

    def _write_config_artifact(self, n: int) -> None:
        """Write config_{game_id}_g{NN}.json — the agreed terms for sub-game n."""
        shared = self.config.shared
        config_sha256 = digest(shared)
        artifact: dict = {"_schema": "police_thief_p2p_config_v1.2"}
        for key in ("agreed_between", "board_and_agents",
                    "world", "movement_and_barriers", "scoring", "pheromones",
                    "network_and_league", "rate_limiter_gatekeeper"):
            if key in shared:
                artifact[key] = shared[key]
        artifact.update({
            "schema_version": SCHEMA_VERSION,
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "sub_game_number": n,
            "links": self._links_dict(),
            "config_name": f"{self.game_id}-g{n:02d}",
            "config_sha256": config_sha256,
        })
        fname = (f"config_{self.game_id}_g{n:02d}.json" if self.game_id
                 else f"config_{self.natural_role}_g{n:02d}.json")
        path = self.out_dir / fname
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    def _update_declaration_end(self, game_ended_at: str) -> None:
        if not self.game_id:
            return
        path = self.out_dir / f"declaration_{self.game_id}.json"
        if not path.exists():
            return
        try:
            declaration = json.loads(path.read_text(encoding="utf-8"))
            declaration["game_ended_at"] = game_ended_at
            path.write_text(json.dumps(declaration, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        except Exception:
            pass

    # -- series --------------------------------------------------------------
    def reset_for_next_series(self) -> None:
        """Drain per-series state so run_series() can be called again.
        The MCP server thread is NOT restarted — it keeps serving across resets.
        """
        import queue as _queue
        for q in (self.inbox.agreements, self.inbox.turns, self.inbox.audits):
            while True:
                try:
                    q.get_nowait()
                except _queue.Empty:
                    break
        self.rows = []
        self.mutual_agreement = {}
        self.game_id = ""
        self.game_uid = ""
        self.game_started_at = ""
        self.their_identity = {}
        self._current_window = None
        self._mid_game = False
        self._last_audit_key = None

    def run_series(self) -> dict:
        if self.spec_profile == "najamjad":
            return self.run_series_najamjad()
        self.game_started_at = datetime.now(UTC).isoformat()
        if not self.wait_for_opponent():
            raise LinkError("opponent never came up")
        ok, reason = self.negotiate_boundary(1)
        if not ok:
            raise LinkError(f"initial negotiation failed: {reason}")
        # Compute game_id/game_uid once both identities are known
        self._compute_ids()
        self.log(f"[{self.natural_role}] game_id={self.game_id} uid={self.game_uid}")
        self._write_declaration()
        self.log(f"[{self.natural_role}] agreement verified with "
                 f"{self.their_identity.get('group_id', 'opponent')}")
        for n in range(1, self.num_games + 1):
            self.rows.append(self.play_sub_game(n))
        if self.spec_profile == "amireman":
            self._run_consensus_exchange()
            return self.build_spec_result()
        return self.build_result()

    def _compute_ids(self) -> None:
        """Derive game_id/game_uid per the active profile (both must match peer)."""
        our_group = self.identity.get("group_id", "orcai-mj")
        their_group = self.their_identity.get("group_id", "opponent")
        if self.spec_profile == "najamjad":
            # Their §6 is byte-identical to the Appendix-B recipe: sorted pair,
            # game_uid from the FIRST 16 RAW bytes of sha256(canonical(terms)
            # + "|" + "|".join(pair)). Derivable before any handshake because
            # both group ids are fixed for this opponent.
            their_group = (self.their_identity.get("group_id", "")
                           or najamjad_mod.THEIR_GROUP_ID)
            self.game_id = consensus.spec_game_id(our_group, their_group)
            self.game_uid = consensus.spec_game_uid(self.terms, our_group,
                                                    their_group)
        elif self.spec_profile == "amireman":
            # Spec Appendix B: sorted "-vs-" id and a UUID over canonical(terms).
            # game_id MAY be a mutually-agreed label (e.g. TEST22); game_uid is
            # ALWAYS derived and never overridden.
            self.game_id = self.game_id_override or \
                consensus.spec_game_id(our_group, their_group)
            self.game_uid = consensus.spec_game_uid(self.terms, our_group,
                                                    their_group)
        else:
            self.game_id = make_game_id(our_group, their_group)
            self.game_uid = make_game_uid(our_group, their_group,
                                          digest(self.config.shared))

    def build_result(self) -> dict:
        # Compute game_id lazily when build_result is called without run_series
        if not self.game_id:
            our_group = self.identity.get("group_id", "orcai-mj")
            their_group = self.their_identity.get("group_id", "opponent")
            self.game_id = make_game_id(our_group, their_group)
            self.game_uid = make_game_uid(our_group, their_group,
                                          digest(self.config.shared))

        police_total = sum(r["police_score"] for r in self.rows)
        thief_total = sum(r["thief_score"] for r in self.rows)
        winner = POLICE if police_total > thief_total else \
            THIEF if thief_total > police_total else "tie"
        # All audits verified + all outgoing audits delivered + no protocol violations
        clean = all(
            r["ending"] in (CAPTURE, SURVIVAL)
            and r["audit_of_opponent"].startswith("Verified OK")
            and r.get("audit_delivered", True)
            and not r.get("protocol_violations")
            for r in self.rows
        )
        game_ended_at = datetime.now(UTC).isoformat()
        our_id = self.identity
        their_id = self.their_identity
        links = self._links_dict()

        body = {
            # spec-required fields
            "_schema": "police_thief_p2p_result_v1.2",
            "schema_version": SCHEMA_VERSION,
            "report_type": "final_game_result",
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "links": links,
            "timezone": "UTC",
            "groups": {
                "group_1": {k: our_id.get(k) for k in
                            ("group_id", "group_name", "members", "repos")},
                "group_2": {k: their_id.get(k) for k in
                            ("group_id", "group_name", "members", "repos")},
            },
            "num_sub_games": len(self.rows),
            "sub_games": self.rows,
            "final_result": {
                "winner": winner,
                "totals": {"police": police_total, "thief": thief_total},
                "all_audits_verified": clean,
                "tokens_total_series": 0,
            },
            "mutual_agreement": {"sha256": "", "confirmed": clean},
            # internal fields kept for backward compatibility and dispatch_report
            "match_mode": FRIENDLY_LABEL if self.mode == FRIENDLY else "COUNTED",
            "dialect": "reference",
            "config_sha256": digest(self.config.shared),
            "generated_at": game_ended_at,
            "my_group": {k: our_id.get(k) for k in
                         ("group_id", "group_name", "members", "repos")},
            "opponent_group": {k: their_id.get(k) for k in
                               ("group_id", "group_name", "members", "repos")},
            "natural_role": self.natural_role,
            "totals": {"police": police_total, "thief": thief_total},
            "series_winner": winner,
            "all_audits_verified": clean,
        }
        # Populate mutual_agreement.sha256 BEFORE signing so result_sha256 covers it
        body["mutual_agreement"]["sha256"] = mutual_digest(self._build_mutual_doc())
        body["result_sha256"] = digest(body)

        self.out_dir.mkdir(parents=True, exist_ok=True)

        # Write one config artifact per sub-game
        for n in range(1, self.num_games + 1):
            self._write_config_artifact(n)

        # Update declaration with the end timestamp
        self._update_declaration_end(game_ended_at)

        result_name = (f"result_{self.game_id}.json" if self.game_id
                       else f"result_{self.natural_role}.json")
        path = self.out_dir / result_name
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        report = self.dispatch_report(body)
        body["report_status"] = report
        self.log(f"[{self.natural_role}] series done: totals={body['totals']} "
                 f"winner={winner} report={report['status']}")
        return body

    # -- amireman public spec: consensus object, exchange, Section 12 report ---
    def _canonical_rows(self) -> list[dict]:
        """The six spec rows (Section 11), group-keyed, from self.rows."""
        our_group = self.identity.get("group_id", "orcai-mj")
        their_group = self.their_identity.get("group_id", "") or "opponent"
        rows: list[dict] = []
        for row in self.rows:
            my_role = row["my_role"]
            their_role = other(my_role)
            our_score = row["police_score"] if my_role == POLICE else row["thief_score"]
            their_score = row["thief_score"] if my_role == POLICE else row["police_score"]
            if our_score > their_score:
                winner_group = our_group
            elif their_score > our_score:
                winner_group = their_group
            else:                                  # per-sub-game score tie / 0-0
                winner_group = None
            rows.append(consensus.consensus_row(
                sub_game_number=row["index"], result=row["ending"],
                roles={our_group: my_role, their_group: their_role},
                score={our_group: our_score, their_group: their_score},
                winner_group=winner_group))
        return rows

    def _consensus_object(self) -> dict:
        if not self.game_id:
            self._compute_ids()
        return consensus.build_consensus_object(
            self.game_id, self.game_uid, self._canonical_rows())

    def _run_consensus_exchange(self) -> dict:
        """Section 10 step 3: send our series digest, wait (bounded) for theirs,
        and confirm agreement only when the received remote digest equals ours,
        every remote log verified, and every sub-game result was agreed."""
        our_sha = consensus.consensus_sha(self._consensus_object())
        last_role = role_for(self.natural_role, self.num_games) \
            if self.alternate_roles else self.natural_role
        envelope = consensus.build_consensus_envelope(last_role, our_sha)
        delivered = True
        try:
            self.link.submit_audit(envelope)
        except LinkError as exc:
            delivered = False
            self.log(f"[{self.natural_role}] consensus envelope delivery failed: {exc}")

        peer_sha = ""
        deadline = time.monotonic() + self.consensus_wait
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                env = self.inbox.audits.get(timeout=min(2.0, max(0.1, remaining)))
            except queue.Empty:
                continue
            accepted, _reason = consensus.validate_remote_consensus(env)
            if accepted:
                peer_sha = env["consensus_sha"]
                break
            # Straggler per-sub-game audit (no valid consensus_sha) — skip it.
        rows_present = bool(self.rows)
        results_agreed = rows_present and all(r.get("result_agreed") for r in self.rows)
        logs_verified = rows_present and all(r.get("log_verified") for r in self.rows)
        sha_match = bool(peer_sha) and peer_sha == our_sha
        self.mutual_agreement = {
            "sha256": our_sha,
            "peer_sha256": peer_sha,
            "sha_match": sha_match,
            "results_agreed": results_agreed,
            "confirmed": bool(sha_match and results_agreed and logs_verified),
            "consensus_delivered": delivered,
        }
        self.log(f"[{self.natural_role}] consensus: ours={our_sha[:12]} "
                 f"theirs={(peer_sha or '<none>')[:12]} match={sha_match} "
                 f"confirmed={self.mutual_agreement['confirmed']}")
        return self.mutual_agreement

    def build_spec_result(self) -> dict:
        """Section 12 result report (amireman public spec)."""
        if not self.game_id:
            self._compute_ids()
        our_group = self.identity.get("group_id", "orcai-mj")
        their_group = self.their_identity.get("group_id", "") or "opponent"
        our_id, their_id = self.identity, self.their_identity
        canon_rows = self._canonical_rows()

        # Series totals with the Section 6 +2 tie bonus, applied once, only on a tie.
        total = {our_group: 0, their_group: 0}
        for cr in canon_rows:
            for g, s in cr["score"].items():
                total[g] += s
        base_tie = total[our_group] == total[their_group]
        if base_tie:
            total[our_group] += self.config.get("scoring", {}).get("tie_score", 2)
            total[their_group] += self.config.get("scoring", {}).get("tie_score", 2)
        sub_games_won = {
            our_group: sum(1 for r in canon_rows if r["winner_group"] == our_group),
            their_group: sum(1 for r in canon_rows if r["winner_group"] == their_group),
        }
        ties = sum(1 for r in canon_rows if r["winner_group"] is None)
        winner_group = None if base_tie else (
            our_group if total[our_group] > total[their_group] else their_group)

        if not self.mutual_agreement:
            self._run_consensus_exchange_stub()

        from police_thief.shared.sysinfo import detailed_hardware_spec as get_hw
        github_links = {
            our_group: dict(our_id.get("repos", {})),
            their_group: dict(their_id.get("repos", {})),
        }

        def _row_report(row: dict, cr: dict) -> dict:
            n = row["index"]
            return {
                "sub_game_number": n,
                "roles": cr["roles"],
                "result": cr["result"],
                "winner_group": cr["winner_group"],
                "tie": cr["winner_group"] is None,
                "score": cr["score"],
                "github_commit": {our_group: row.get("our_commit", ""),
                                  their_group: row.get("their_commit", "")},
                "tokens": {our_group: 0, their_group: 0},
                "steps": row.get("step", 0),
                "started_at": row.get("started_at", ""),
                "ended_at": row.get("ended_at", ""),
                "audit": {
                    "log_verified": bool(row.get("log_verified")),
                    "tampered": row["audit_of_opponent"] == refaudit.TAMPERED,
                    "result_agreed": bool(row.get("result_agreed")),
                },
                "log_files": [f"log_{self.game_id}_g{n:02d}.json"],
            }

        sub_games_report = [_row_report(row, cr)
                            for row, cr in zip(self.rows, canon_rows)]

        def _details(gid: str, ident: dict, hw: dict) -> dict:
            return {
                "group_id": gid,
                "members": ident.get("members", []),
                "repos": ident.get("repos", {}),
                "mcp_servers": ident.get("mcp_servers", {}),
                "llm_model": ident.get("llm_model", ""),
                "hardware_spec": hw,
            }

        confirmed = bool(self.mutual_agreement.get("confirmed"))
        game_ended_at = datetime.now(UTC).isoformat()
        body = {
            "report_type": "final_game_result",
            "schema_version": SCHEMA_VERSION,
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "groups": sorted([our_group, their_group]),
            "timezone": "UTC",
            "game_started_at": self.game_started_at,
            "game_ended_at": game_ended_at,
            "sub_games": sub_games_report,
            "links": {"github": github_links},
            "group_details": {
                our_group: _details(our_group, our_id, get_hw()),
                their_group: _details(their_group, their_id, {}),
            },
            "mutual_agreement": dict(self.mutual_agreement),
            "final_result": {
                "total_score": total,
                "sub_games_won": sub_games_won,
                "ties": ties,
                "winner_group": winner_group,
                "series_tie": base_tie,
                "tokens_total_series": 0,
            },
            # -- internal keys the CLI / dispatch_report / launcher read --------
            "dialect": "amireman",
            "spec_profile": "amireman",
            "match_mode": FRIENDLY_LABEL if self.mode == FRIENDLY else "COUNTED",
            "num_sub_games": len(self.rows),
            "config_sha256": digest(self.config.shared),
            "totals": {"police": sum(r["police_score"] for r in self.rows),
                       "thief": sum(r["thief_score"] for r in self.rows)},
            "series_winner": winner_group or "tie",
            "all_audits_verified": confirmed,
        }
        body["result_sha256"] = digest(body)

        self.out_dir.mkdir(parents=True, exist_ok=True)
        result_name = (f"result_{self.game_id}.json" if self.game_id
                       else f"result_{self.natural_role}.json")
        (self.out_dir / result_name).write_text(
            json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        self._update_declaration_end(game_ended_at)
        report = self._dispatch_report_amireman(body)
        body["report_status"] = report
        self.log(f"[{self.natural_role}] amireman series done: "
                 f"winner={winner_group} confirmed={confirmed} "
                 f"report={report['status']}")
        return body

    def _new_gmail_sender(self):
        """Construct the Gmail sender — a seam tests replace with a fake so no
        real email is ever sent during testing."""
        from police_thief.infra.email_sender import GmailSender
        return GmailSender(self.config)

    def _dispatch_report_amireman(self, result: dict) -> dict:
        """amireman public-spec reporting (Section 12).

        A COMPLETED series sends EXACTLY ONE email with EXACTLY ONE attachment,
        ``result_<game_id>.json``. No declaration/config/log/audit/consensus
        file is attached (those are still written locally). Recipient is chosen
        strictly by mode and the two addresses never cross:

        * friendly / non-counted -> the team address (never the lecturer);
        * counted                -> the league address (never the team address).

        A per-game sentinel guarantees one completed series cannot send twice.
        """
        from police_thief.infra.email_sender import LEAGUE_ADDRESS
        game_id = self.game_id or f"interop-{self.identity.get('group_id', 'unknown')}"
        recipient = (AMIREMAN_FRIENDLY_RECIPIENT if self.mode == FRIENDLY
                     else LEAGUE_ADDRESS)
        result_path = self.out_dir / f"result_{game_id}.json"
        if not result_path.exists():
            return {"status": "suppressed (no result artifact)",
                    "recipient": recipient}
        sentinel = self.out_dir / f"amireman_report_sent_{game_id}.lock"
        if sentinel.exists():
            return {"status": "duplicate_suppressed", "sentinel": str(sentinel),
                    "recipient": recipient}
        sender = self._new_gmail_sender()
        sender.recipient = recipient          # explicit; never the config default
        sender.mode = "send"                  # a completed series always sends
        summary = {"game_id": game_id, "winner": result.get("series_winner")}
        # EXACTLY one attachment: the final result report and nothing else.
        report = sender.send_series_report({"result": result_path}, summary)
        report["recipient"] = recipient
        if report.get("status") == "sent":
            sentinel.write_text(json.dumps(report, ensure_ascii=False),
                                encoding="utf-8")
        return report

    def _run_consensus_exchange_stub(self) -> None:
        """Populate mutual_agreement with a local-only digest when no exchange
        was run (e.g. build_spec_result called directly in a unit test). A
        local digest alone MUST NOT confirm agreement (Section 10 step 4)."""
        our_sha = consensus.consensus_sha(self._consensus_object())
        self.mutual_agreement = {
            "sha256": our_sha, "peer_sha256": "", "sha_match": False,
            "results_agreed": False, "confirmed": False,
            "consensus_delivered": False,
        }

    # -- NajAmjad profile: split two-process series (their §3 / §3.1) ----------
    def negotiate_window_najamjad(self, n: int) -> tuple[bool, str]:
        """Open window ``n``: fresh signed terms, ``sub_game_number`` riding on
        every negotiate, busy refusals retried without burning budget, bounded
        by WALL-CLOCK window patience with capped exponential backoff.
        """
        self._current_window = n
        deadline = time.monotonic() + self.window_patience
        backoff = najamjad_mod.BACKOFF_START
        last_reason = "window patience exhausted"
        while time.monotonic() < deadline:
            agreement = najamjad_mod.signed_agreement(self.terms, self.identity, n)
            theirs: dict | None = None
            delivered = False
            try:
                response = self.link.negotiate(
                    agreement, timeout=najamjad_mod.HANDSHAKE_REPLY)
                delivered = True
                if najamjad_mod.is_busy_refusal(response):
                    # "Ask again in a moment" — retriable, costs no budget
                    # beyond the wall clock (their §3.1).
                    time.sleep(backoff)
                    backoff = min(backoff * 2, najamjad_mod.BACKOFF_CEILING)
                    continue
                if isinstance(response, dict) and \
                        isinstance(response.get("agreement"), dict):
                    theirs = response["agreement"]   # in-band reply agreement
            except LinkError as exc:
                last_reason = f"could not deliver agreement: {exc}"
            if theirs is None:
                wait_until = time.monotonic() + min(
                    najamjad_mod.HANDSHAKE_REPLY,
                    max(0.1, deadline - time.monotonic()))
                while theirs is None and time.monotonic() < wait_until:
                    try:
                        theirs = self.inbox.agreements.get(
                            timeout=min(2.0, max(0.1,
                                                 wait_until - time.monotonic())))
                    except queue.Empty:
                        continue
            while not self.inbox.agreements.empty():
                theirs = self.inbox.agreements.get_nowait()   # freshest copy wins
            if theirs is None:
                last_reason = "opponent never sent its agreement"
                time.sleep(backoff)
                backoff = min(backoff * 2, najamjad_mod.BACKOFF_CEILING)
                continue
            accepted, reason = najamjad_mod.evaluate_agreement(
                theirs, self.terms, expected_sub_game=n)
            if not accepted:
                if "terms mismatch" in reason or "scent model" in reason:
                    # A differing negotiate is a refusal, not a counter-offer.
                    return False, reason
                last_reason = reason                  # e.g. window-number drift
                self.log(f"[{self.natural_role}] window {n}: refused handshake: "
                         f"{reason}")
                time.sleep(backoff)
                backoff = min(backoff * 2, najamjad_mod.BACKOFF_CEILING)
                continue
            if theirs.get("scent_model_sha256") is None:
                self.log(f"[{self.natural_role}] window {n}: peer declared no "
                         f"scent model; we run A2 — flagged, not fatal")
            if not delivered:
                # We adopted the agreement they pushed while our own outbound
                # was failing — deliver ours late rather than skip it (§3.1).
                try:
                    self.link.negotiate(agreement,
                                        timeout=najamjad_mod.HANDSHAKE_REPLY)
                except LinkError:
                    pass          # their greeting proves a live dialler; in-band
                                  # reply already carried our agreement
            self.their_identity = theirs.get("identity", {}) or {}
            return True, "ok"
        return False, last_reason

    def play_window_najamjad(self, n: int) -> dict:
        """One window at our FIXED role, re-offered under the SAME number
        (bounded) when it fails on transport rather than on the board."""
        reoffer_causes = ("no response to our turn", "turn timeout",
                          "no terminal consensus", "could not deliver",
                          "opponent never sent", "window patience")
        row: dict | None = None
        for attempt in range(1, najamjad_mod.REOFFER_LIMIT + 1):
            started_at = datetime.now(UTC).isoformat()
            engine = SubGame(self.natural_role, self.config, n,
                             seed=self.seed + n, spec_profile=self.spec_profile)
            self.log(f"[{self.natural_role}] window {n} (attempt {attempt}): "
                     f"playing as {self.natural_role}")
            ok, reason = self.negotiate_window_najamjad(n)
            if not ok:
                engine.declare_technical(f"no handshake for window {n}: {reason}")
                row = self._finish_sub_game(engine, n, started_at)
            else:
                self._drain_stale_turns()
                self._mid_game = True
                try:
                    self._run_play_loop(engine)
                finally:
                    self._mid_game = False
                row = self._finish_sub_game(engine, n, started_at)
            cause = str(row.get("cause", ""))
            failed_transport = row["ending"] == TECHNICAL_LOSS and any(
                marker in cause for marker in reoffer_causes)
            if not failed_transport:
                break
            if attempt < najamjad_mod.REOFFER_LIMIT:
                self.log(f"[{self.natural_role}] window {n}: transport failure "
                         f"({cause}) — re-offering the SAME number")
        self._current_window = None
        return row

    def _write_row_file(self, row: dict) -> None:
        """Persist one played window as this process's OWN immutable artifact.

        Written into this process's own role-owned output directory ONLY. The
        sibling role process never reads it (project §2.4.2: the two agents
        share no state); the POST-MATCH aggregator — a separate step the
        launcher runs after the whole series has finished — is the only
        reader that ever merges the two roles' artifacts.
        """
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"row_{self.game_id}_g{row['index']:02d}.json"
        path.write_text(json.dumps(row, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    def _najamjad_group_rows(self, rows: list[dict]) -> list[dict]:
        """Group-keyed consensus rows for THIS process's own windows."""
        our_group = self.identity.get("group_id", najamjad_mod.OUR_GROUP_ID)
        their_group = (self.their_identity.get("group_id", "")
                       or najamjad_mod.THEIR_GROUP_ID)
        return najamjad_mod.group_rows(rows, our_group, their_group)

    def run_series_najamjad(self) -> dict:
        """Split-process series: this process plays ONLY its own windows and
        touches ONLY its own role-owned artifacts.

        Strict agent separation (project §2.4.2): no shared files, memory,
        IPC or polling between our cop and thief processes — synchronisation
        happens purely through the per-window handshake with the OPPONENT
        (busy refusals + retries). The six-row team report is assembled later
        by the POST-MATCH aggregator (``police-thief najamjad-report``),
        which the launcher runs only after the whole series has finished.
        """
        najamjad_mod.verify_terms(self.terms)          # fail loudly (their §1)
        najamjad_mod.verify_commit_vector()            # golden vector (their §5)
        self.game_started_at = datetime.now(UTC).isoformat()
        self._compute_ids()
        self.log(f"[{self.natural_role}] najamjad game_id={self.game_id} "
                 f"uid={self.game_uid} windows={self.my_windows}")
        if 1 in self.my_windows:
            self._write_declaration()
        for n in self.my_windows:
            row = self.play_window_najamjad(n)
            self.rows.append(row)
            self._write_row_file(row)
            self._write_config_artifact(n)     # own windows' config artifacts
        return self.build_najamjad_role_result()

    def build_najamjad_role_result(self) -> dict:
        """This ROLE's partial result — its own windows only, nothing merged.

        Deliberately contains no sibling data, computes no team mutual digest
        and sends no email: the six-row team report, the §7.2 signature and
        the single dispatch belong to the POST-MATCH aggregator
        (``interop/najamjad_report.py``), which runs only after the series.
        """
        if not self.game_id:
            self._compute_ids()
        our_group = self.identity.get("group_id", najamjad_mod.OUR_GROUP_ID)
        their_group = (self.their_identity.get("group_id", "")
                       or najamjad_mod.THEIR_GROUP_ID)
        own_rows = sorted(self.rows, key=lambda r: r["index"])
        grouped = self._najamjad_group_rows(own_rows)
        sub_games_report = [
            najamjad_mod.row_report(row, cr, our_group, their_group,
                                    self.game_id)
            for row, cr in zip(own_rows, grouped)]
        clean = bool(own_rows) and len(own_rows) == len(self.my_windows) \
            and all(
                r["ending"] in (CAPTURE, SURVIVAL)
                and str(r.get("audit_of_opponent", "")).startswith("Verified OK")
                and r.get("audit_delivered", True)
                and not r.get("protocol_violations")
                for r in own_rows)
        game_ended_at = datetime.now(UTC).isoformat()
        from police_thief.shared.sysinfo import detailed_hardware_spec as get_hw
        body = {
            "report_type": "najamjad_role_partial_result",
            "schema_version": SCHEMA_VERSION,
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "groups": sorted([our_group, their_group]),
            "timezone": "UTC",
            "game_started_at": self.game_started_at,
            "game_ended_at": game_ended_at,
            "natural_role": self.natural_role,
            "windows_played": [r["index"] for r in own_rows],
            "windows_expected": len(self.my_windows),
            "sub_games": sub_games_report,
            "links": {"github": {
                our_group: dict(self.identity.get("repos", {})),
                their_group: dict(self.their_identity.get("repos", {})),
            }},
            "group_details": {
                our_group: {
                    "group_id": our_group,
                    "group_name": self.identity.get("group_name", ""),
                    "members": self.identity.get("members", []),
                    "repos": self.identity.get("repos", {}),
                    "mcp_servers": self.identity.get("mcp_servers", {}),
                    "llm_model": self.identity.get("llm_model", ""),
                    "hardware_spec": get_hw(),
                },
                their_group: {
                    "group_id": their_group,
                    "group_name": self.their_identity.get("group_name", ""),
                    "members": self.their_identity.get("members", []),
                    "repos": self.their_identity.get("repos", {}),
                    "mcp_servers": self.their_identity.get("mcp_servers", {}),
                    "llm_model": self.their_identity.get("llm_model", ""),
                    "hardware_spec": {},
                },
            },
            "mutual_agreement": {
                "sha256": "",
                "deferred_to": "post-match aggregator "
                               "(police-thief najamjad-report)",
            },
            # -- internal keys the CLI / launcher read -------------------------
            "dialect": "najamjad",
            "spec_profile": "najamjad",
            "match_mode": FRIENDLY_LABEL if self.mode == FRIENDLY else "COUNTED",
            "num_sub_games": len(own_rows),
            "config_sha256": digest(self.config.shared),
            "terms_sha256": najamjad_mod.terms_sha256(self.terms),
            "totals": {"police": sum(r["police_score"] for r in own_rows),
                       "thief": sum(r["thief_score"] for r in own_rows)},
            "series_winner": "pending-aggregation",
            "all_audits_verified": clean,
            "report_status": {"status": "deferred (post-match aggregator "
                                        "files the team report)"},
        }
        body["result_sha256"] = digest(body)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._update_declaration_end(game_ended_at)
        path = self.out_dir / f"result_{self.game_id}_{self.natural_role}.json"
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        self.log(f"[{self.natural_role}] najamjad role windows done: "
                 f"{body['windows_played']} clean={clean} — team report "
                 f"deferred to the post-match aggregator")
        return body

    # -- reporting: the friendly/counted hard wall -----------------------------
    def dispatch_report(self, result: dict) -> dict:
        """FRIENDLY mode structurally cannot send email. Counted sends only when
        all audits pass and the report has not already been sent (sentinel guard)."""
        if self.mode != COUNTED:
            return {"status": "suppressed (friendly mode — no email, no report)"}
        if not result.get("all_audits_verified"):
            return {"status": "suppressed (audit failures — all audits must pass)"}
        sentinel = self.out_dir / f"report_sent_{self.natural_role}.lock"
        if sentinel.exists():
            return {"status": "duplicate_suppressed", "sentinel": str(sentinel)}
        from police_thief.infra.email_sender import GmailSender  # lazy
        game_id = self.game_id or f"interop-{self.identity.get('group_id', 'unknown')}"
        summary = {"game_id": game_id, "winner": result["series_winner"]}
        artifact_paths: dict = {}
        # Declaration
        decl = self.out_dir / f"declaration_{game_id}.json"
        if decl.exists():
            artifact_paths["declaration"] = decl
        # Config artifacts (one per sub-game)
        for cfg_path in sorted(self.out_dir.glob(f"config_{game_id}_g*.json")):
            artifact_paths[cfg_path.stem] = cfg_path
        # Log artifacts (one per sub-game)
        for log_path in sorted(self.out_dir.glob(f"log_{game_id}_g*.json")):
            artifact_paths[log_path.stem] = log_path
        # Result
        result_path = self.out_dir / f"result_{game_id}.json"
        if result_path.exists():
            artifact_paths["result"] = result_path
        sender = GmailSender(self.config)
        sender.mode = "send"  # counted always sends, never drafts
        report = sender.send_series_report(artifact_paths, summary)
        if report.get("status") == "sent":
            sentinel.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return report
