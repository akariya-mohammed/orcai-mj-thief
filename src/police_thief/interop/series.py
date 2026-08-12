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
from police_thief.interop import refaudit, wire
from police_thief.interop import terms as terms_mod
from police_thief.interop.mcp import Inbox, LinkError, RefLink, serve_in_thread
from police_thief.interop.refcrypto import digest, seal
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

    def __init__(self, my_role: str, config, sub_game: int, seed: int) -> None:
        self.my_role = my_role
        self.n = sub_game
        self.config = config
        size = config.get("board.size", 7)
        key = "cop_start" if my_role == POLICE else "thief_start"
        start = tuple(config.get(f"positions.{key}",
                                 (0, 0) if my_role == POLICE else (3, 3)))
        self.state = OwnGameState(start, Board(size))
        self.belief = BeliefGrid(size, config.get("belief.smell_trust_weight", 4.0))
        self.scent = ScentGrid(
            size,
            center_intensity=config.get("pheromones.pheromone_center_intensity", 0.9),
            decay_rate=config.get("pheromones.pheromone_decay", 0.10),
            field_size=config.get("pheromones.pheromone_grid_size", 5))
        self.brain = TrapperPolice() if my_role == POLICE else RingRunnerThief()
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

        self.scent.deposit(self.state.position)
        self.scent.decay_all()
        snapshot = self.scent.snapshot()
        self.my_scent_history.append(dict(snapshot))

        capture_claim = None
        if self.my_role == POLICE and decision.move_type is MoveType.MOVE and \
                tuple(self.state.position) == tuple(self.belief.most_likely()):
            capture_claim = list(self.state.position)

        win_claim = None
        if self.my_role == THIEF and step >= threshold and not self.captured:
            win_claim = {"type": SURVIVAL, "step": step}
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
                 prior_counted_games: int = 0, log_fn=print) -> None:
        if mode not in (FRIENDLY, COUNTED):
            raise ValueError(f"unknown mode {mode!r}")
        if natural_role not in (POLICE, THIEF):
            raise ValueError(f"unknown role {natural_role!r}")
        self.natural_role = natural_role
        self.config = config
        self.num_games = num_games
        self.mode = mode
        self.alternate_roles = alternate_roles
        self.handshake_per_sub_game = handshake_per_sub_game
        self.turn_timeout = turn_timeout
        self.agreement_timeout = agreement_timeout
        self.audit_wait = audit_wait
        self.out_dir = Path(out_dir)
        self.seed = seed
        self.my_port = my_port
        self.log = log_fn
        self.inbox = Inbox()
        self.link = RefLink(opponent_url)
        self.terms = terms_mod.build_terms(config, num_games)
        self.identity = terms_mod.build_identity(
            config, mcp_url=mcp_url or f"http://0.0.0.0:{my_port}/mcp",
            prior_counted_games=prior_counted_games)
        self.their_identity: dict = {}
        self.rows: list[dict] = []
        self._server_thread = None
        # Computed after initial negotiation (game_id requires both group IDs)
        self.game_id: str = ""
        self.game_uid: str = ""
        self.game_started_at: str = ""

    # -- lifecycle -------------------------------------------------------------
    def start_server(self) -> None:
        self._server_thread = serve_in_thread(
            f"police-thief-interop-{self.natural_role}", self.inbox,
            port=self.my_port)
        self.log(f"[{self.natural_role}] interop MCP server on port {self.my_port} "
                 f"({self.mode.upper()} mode)")

    def wait_for_opponent(self, attempts: int = 60, delay: float = 2.0) -> bool:
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
        engine = SubGame(my_role, self.config, n, seed=self.seed + n)
        self.log(f"[{self.natural_role}] sub-game {n}: playing as {my_role}")

        if n > 1 and self.handshake_per_sub_game:
            ok, reason = self.negotiate_boundary(n)
            if not ok:
                self.log(f"[{self.natural_role}] sub-game {n}: no re-handshake: "
                         f"{reason}")
                engine.declare_technical(f"no re-handshake: {reason}")
                return self._finish_sub_game(engine, n, started_at)
        self._drain_stale_turns()

        if my_role == THIEF:                       # thief opens every sub-game
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
        return self._finish_sub_game(engine, n, started_at)

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
    def _finish_sub_game(self, engine: SubGame, n: int, started_at: str) -> dict:
        ending = engine.outcome["ending"]
        package = {"sender": engine.my_role, "records": engine.records,
                   "result_claim": ending}
        sent_ok = True
        try:
            self.link.submit_audit(package)
        except LinkError as exc:
            sent_ok = False
            self.log(f"[{self.natural_role}] sub-game {n}: audit delivery failed: "
                     f"{exc}")
        theirs: dict | None = None
        try:
            theirs = self.inbox.audits.get(timeout=self.audit_wait)
        except queue.Empty:
            pass
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
        self.log(f"[{self.natural_role}] declaration written → {path.name}")

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
    def run_series(self) -> dict:
        self.game_started_at = datetime.now(UTC).isoformat()
        if not self.wait_for_opponent():
            raise LinkError("opponent never came up")
        ok, reason = self.negotiate_boundary(1)
        if not ok:
            raise LinkError(f"initial negotiation failed: {reason}")
        # Compute game_id once both identities are known
        our_group = self.identity.get("group_id", "orcai-mj")
        their_group = self.their_identity.get("group_id", "opponent")
        self.game_id = make_game_id(our_group, their_group)
        self.game_uid = make_game_uid(our_group, their_group, digest(self.config.shared))
        self.log(f"[{self.natural_role}] game_id={self.game_id} uid={self.game_uid}")
        self._write_declaration()
        self.log(f"[{self.natural_role}] agreement verified with "
                 f"{self.their_identity.get('group_id', 'opponent')}")
        for n in range(1, self.num_games + 1):
            self.rows.append(self.play_sub_game(n))
        return self.build_result()

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
