"""NajAmjad opponent profile — isolated primitives (NAJAMJAD_MATCH_TERMS.md).

Everything NajAmjad-specific lives in this module so neither the ahk-yosi
dialect nor the amireman public-spec path is touched:

* the 14-key signed-terms digest gate (``a284082d…``), re-derived through our
  own loader and refused loudly on mismatch;
* the EXACT ``multiplicative_book_v1`` scent kernel (their §4.0) with
  max-merge accumulation and multiplicative decay — cell-for-cell table
  values, NOT our Gaussian approximation;
* the serve order their §4.0.1 requires: age the PRIOR trail, merge the fresh
  deposit at full strength, then transmit (peak is ALWAYS 0.90 on the wire);
* the mutual result signature over EXACTLY ``{game_id, aggregate, sub_games}``
  with Python DEFAULT (spaced) separators — deliberately different from both
  the compact commit/reveal canonical form and the amireman consensus digest;
* the tie rule: raw totals stay raw (75-75 stays 75-75), ``winner_group`` is
  null, ``series_tie`` is true and ``tie_award: 2`` is a separate aggregate
  field — never added into ``total_score``;
* split two-process window scheduling (their §3): our cop process plays only
  police windows against their thief door, our thief process plays only thief
  windows against their cop door, both stay alive for the whole series;
* their §3.1 connection contract: busy refusals are retriable, windows are
  re-offered under the SAME number, retries are backed off and bounded by
  WALL-CLOCK window patience, ``sub_game_number`` rides on every negotiate.

game_id / game_uid reuse the generic sorted-pair recipe in ``consensus``
(Appendix-B shape), which NajAmjad's §6 specifies identically.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from police_thief.interop import consensus, refaudit
from police_thief.interop import terms as terms_mod
from police_thief.interop.refcrypto import reference_commit

Cell = tuple[int, int]

OUR_GROUP_ID = "orcai-mj"                    # case-sensitive, THIS opponent only
THEIR_GROUP_ID = "najamjad"

#: SHA-256 of the canonical JSON of the exactly-14 signed terms (their §1).
TERMS_SHA256 = \
    "a284082dfb1572236f1b614d29295a99625539c7d33a096f7f8921bafbc3d08d"

#: Their offline commit-reveal vector (§5): payload+nonce below must hash to this.
COMMIT_VECTOR_SHA256 = \
    "4047830b8108320cbf48c1c1e1f09c6c0d47da51c225ce2cf40c7857cefc3030"
COMMIT_VECTOR_PAYLOAD = {
    "hint": "", "intent": "probe east", "move": "MOVE:E", "position": [3, 4],
    "role": "thief", "state": "ok", "step": 1, "sub_game": 1}
COMMIT_VECTOR_NONCE = "a" * 32

#: Scent arrangement A2 (their §4.0) — the kit's registered document digest.
SCENT_MODEL_NAME = "multiplicative_book_v1"
SCENT_MODEL_SHA256 = \
    "934c220d5bf62acaa3297c6c9d723ea954c220260b02292ca17f6d5daef9f4d9"

#: Their permanent named-tunnel doors (§2). Our cop dials their thief and vice versa.
THEIR_COP_URL = "https://cop.4laboratory.com/mcp"
THEIR_THIEF_URL = "https://thief.4laboratory.com/mcp"

#: §7.4 friendly recipient — BOTH team addresses (ours + NajAmjad), never the lecturer.
FRIENDLY_RECIPIENT = "jude021003@gmail.com, najikayal4@gmail.com"

# -- timing policy (their §3.1 table), NajAmjad profile only ------------------
TURN_WAIT = 60.0           # our per-turn silence watchdog (they take <= 30 s)
HANDSHAKE_REPLY = 60.0     # per negotiate attempt, inside the window budget
CALL_ATTEMPTS = 3          # per-call attempts, with backoff (RefLink default)
BACKOFF_START = 1.0
BACKOFF_CEILING = 5.0      # their §9.9: bounded exponential backoff, 5 s ceiling
WINDOW_PATIENCE = 1000.0   # 16.7 minutes of WALL CLOCK per window
AUDIT_WAIT = 30.0          # they wait 30 s for our reveal; we mirror it
REOFFER_LIMIT = 3          # bounded same-number re-offers of a failed window

BUSY_ERROR = "a mini-game is in progress; re-send this handshake at the boundary"

#: Fields that NajAmjad's declaration schema requires to be numeric (or absent).
_NUMERIC_HW_FIELDS = frozenset({"cpu_freq_mhz", "vram_gb", "ram_gb"})


def sanitize_hardware_spec(spec: dict) -> dict:
    """Strip 'unknown' from numeric-only hardware fields (NajAmjad schema §8).

    cpu_freq_mhz and vram_gb must be numeric or omitted — the stdlib exposes
    no portable frequency probe and no GPU is installed on this machine.
    String fields (os, cpu_type, gpu_type, gpu_cores_or_cuda) are kept as-is.
    """
    return {k: v for k, v in spec.items()
            if not (k in _NUMERIC_HW_FIELDS and v == "unknown")}


# -- signed terms -------------------------------------------------------------
def terms_sha256(terms: dict[str, Any]) -> str:
    """Canonical (sorted keys, compact separators, raw UTF-8) SHA-256 of terms."""
    return consensus.sha256_hex(consensus.canonical(terms))


def verify_terms(terms: dict[str, Any]) -> None:
    """Fail loudly when our loader does not re-derive their published digest."""
    actual = terms_sha256(terms)
    if actual != TERMS_SHA256:
        raise ValueError(
            f"NajAmjad terms digest mismatch: our loader derives {actual}, "
            f"the signed terms require {TERMS_SHA256} — refusing to play")


def verify_commit_vector() -> None:
    """Run their §5 golden vector through OUR sealing implementation."""
    actual = reference_commit(COMMIT_VECTOR_PAYLOAD, COMMIT_VECTOR_NONCE)
    if actual != COMMIT_VECTOR_SHA256:
        raise ValueError(
            f"NajAmjad commit-reveal vector mismatch: ours {actual}, "
            f"expected {COMMIT_VECTOR_SHA256}")


# -- negotiate envelope (their §3.1, §9.8) ------------------------------------
def signed_agreement(terms: dict[str, Any], identity: dict[str, Any],
                     sub_game_number: int) -> dict[str, Any]:
    """Reference agreement + NajAmjad riders: ``sub_game_number`` on EVERY
    negotiate, top-level ``sender``/``group_id`` (their §9.8), and the A2
    scent-model declaration (their §4.1)."""
    agreement = terms_mod.signed_agreement(terms, identity)
    agreement["sub_game_number"] = int(sub_game_number)
    agreement["sender"] = identity.get("group_id", OUR_GROUP_ID)
    agreement["group_id"] = identity.get("group_id", OUR_GROUP_ID)
    agreement["scent_model_sha256"] = SCENT_MODEL_SHA256
    return agreement


def evaluate_agreement(theirs: Any, my_terms: dict[str, Any],
                       expected_sub_game: int | None = None
                       ) -> tuple[bool, str]:
    """(accepted, reason) for an inbound NajAmjad agreement.

    Terms must match exactly (a differing negotiate is a refusal, not a
    counter-offer — their §1). A ``sub_game_number`` naming a different window
    is refused rather than adopted (their §3.1). A declared scent model must
    be A2's digest; an absent declaration is tolerated and logged upstream.
    A signature is verified when present (reference recipe) and tolerated
    when absent — the session token of the exchange is the terms equality.
    """
    if not isinstance(theirs, dict):
        return False, "agreement is not an object"
    their_terms = theirs.get("terms")
    if their_terms != my_terms:
        diff = sorted(
            k for k in set(my_terms) | set(their_terms or {})
            if not isinstance(their_terms, dict)
            or their_terms.get(k) != my_terms.get(k))
        return False, f"terms mismatch on {diff}"
    if expected_sub_game is not None:
        named = theirs.get("sub_game_number")
        if named is not None:
            try:
                named_int = int(named)
            except (TypeError, ValueError):
                return False, f"sub_game_number {named!r} is not an integer"
            if named_int != expected_sub_game:
                return False, (f"sub_game_number names window {named_int}, "
                               f"we are opening {expected_sub_game}")
    declared = theirs.get("scent_model_sha256")
    if declared is not None and declared != SCENT_MODEL_SHA256:
        return False, (f"scent model mismatch: they declare {declared!r}, "
                       f"agreed arrangement is A2 {SCENT_MODEL_SHA256}")
    signature = theirs.get("signature")
    if signature is not None:
        if reference_commit(their_terms, str(theirs.get("nonce", ""))) != signature:
            return False, "agreement signature does not verify"
    return True, "ok"


def busy_refusal() -> dict[str, Any]:
    """Our retriable busy answer — same shape as theirs (their §3.1)."""
    return {"accepted": False, "errors": [BUSY_ERROR], "retriable": True}


def is_busy_refusal(response: Any) -> bool:
    """Their busy answer is 'ask again in a moment', never an outage."""
    return (isinstance(response, dict) and response.get("accepted") is False
            and bool(response.get("errors")))


# -- scent: multiplicative_book_v1, cell-exact (their §4.0 / §4.0.1) ----------
#: The book's PAGE 44 kernel, keyed by (|dr|, |dc|) from the emitter.
KERNEL: dict[tuple[int, int], float] = {
    (0, 0): 0.90,
    (0, 1): 0.62, (1, 0): 0.62,
    (1, 1): 0.42,
    (0, 2): 0.20, (2, 0): 0.20,
    (1, 2): 0.14, (2, 1): 0.14,
    (2, 2): 0.04,
}


class KernelScentGrid:
    """A2 ``multiplicative_book_v1`` — exact table values, max-merge, x0.9 decay.

    Deliberately NOT the Gaussian in ``domain/smell.py``: NajAmjad's §4.0
    requires the registered kernel cell-for-cell (0.62, not 0.6186…), a
    max-merge against the 0.90 ceiling (a sum-then-clamp brightens a
    stationary agent's neighbours; max-merge does not), and multiplicative
    decay ``tau <- 0.9 * tau``. The epsilon floor prunes dead scent, which
    relative decay alone never reaches (their §9 footnote).

    Serve order is the CALLER's duty (SubGame): decay the prior trail, then
    deposit fresh, then snapshot — so the transmitted peak is always 0.90.
    """

    PRUNE_EPS = 1e-3

    def __init__(self, size: int, center_intensity: float = 0.9,
                 decay_rate: float = 0.10, field_size: int = 5) -> None:
        self.size = size
        self.center = center_intensity
        self.decay_factor = 1.0 - decay_rate      # 0.9 for the signed 0.1
        self.radius = field_size // 2
        self._tau: dict[Cell, float] = {}

    def deposit(self, pos: Cell) -> None:
        """Merge the exact kernel around pos — max-merge against the ceiling."""
        r0, c0 = pos
        for dr in range(-self.radius, self.radius + 1):
            for dc in range(-self.radius, self.radius + 1):
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < self.size and 0 <= c < self.size):
                    continue
                value = KERNEL.get((abs(dr), abs(dc)), 0.0)
                if value <= 0.0:
                    continue
                merged = max(self._tau.get((r, c), 0.0), value)
                self._tau[(r, c)] = min(self.center, merged)

    def decay_all(self) -> None:
        """tau <- 0.9 * tau, with the epsilon floor pruning dead scent."""
        self._tau = {cell: tau * self.decay_factor
                     for cell, tau in self._tau.items()
                     if tau * self.decay_factor >= self.PRUNE_EPS}

    def snapshot(self) -> dict[Cell, float]:
        return dict(self._tau)


# -- split two-process window scheduling (their §3) ---------------------------
def our_window_role(first_window_role: str, sub_game: int) -> str:
    """Our TEAM's role in window ``sub_game`` — alternates from window 1."""
    if sub_game % 2 == 1:
        return first_window_role
    return "thief" if first_window_role == "police" else "police"


def windows_for(fixed_role: str, first_window_role: str,
                num_games: int) -> list[int]:
    """The windows THIS process plays: its repo role, and only its repo role.

    NajAmjad open as thief (their §1 'we do not open as cop'), so by default
    our team is police in window 1 — our cop repo plays 1/3/5 and our thief
    repo plays 2/4/6. ``first_window_role`` is still a parameter so a mutual
    agreement to flip it is one flag, not a code change.
    """
    return [n for n in range(1, num_games + 1)
            if our_window_role(first_window_role, n) == fixed_role]


def opponent_url_for(fixed_role: str) -> str:
    """Per-role routing: our cop dials their thief, our thief dials their cop."""
    return THEIR_THIEF_URL if fixed_role == "police" else THEIR_COP_URL


def group_rows(rows: list[dict[str, Any]], our_group: str,
               their_group: str) -> list[dict[str, Any]]:
    """Five-key consensus rows (group-keyed roles/score) from internal rows.

    Pure function shared by the gameplay peer (its own windows only) and the
    POST-MATCH aggregator (all six merged rows) — no state crosses between
    the two role processes through this module.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        my_role = row["my_role"]
        their_role = "thief" if my_role == "police" else "police"
        our_score = (row["police_score"] if my_role == "police"
                     else row["thief_score"])
        their_score = (row["thief_score"] if my_role == "police"
                       else row["police_score"])
        if our_score > their_score:
            winner_group = our_group
        elif their_score > our_score:
            winner_group = their_group
        else:
            winner_group = None
        out.append(consensus.consensus_row(
            sub_game_number=row["index"], result=row["ending"],
            roles={our_group: my_role, their_group: their_role},
            score={our_group: our_score, their_group: their_score},
            winner_group=winner_group))
    return out


def row_report(row: dict[str, Any], cr: dict[str, Any], our_group: str,
               their_group: str, game_id: str) -> dict[str, Any]:
    """One report row: group-keyed roles/score and the PER-WINDOW commit.

    ``github_commit`` carries the repo HEAD of the process that actually
    played this window (their §7.3) — thief repo on thief windows, cop repo
    on police windows, never one SHA stamped across all six.
    """
    n = row["index"]
    return {
        "sub_game_number": n,
        "roles": cr["roles"],
        "result": cr["result"],
        "winner_group": cr["winner_group"],
        "score": cr["score"],
        "github_commit": {our_group: row.get("our_commit", ""),
                          their_group: row.get("their_commit", "")},
        "tokens": {our_group: 0, their_group: 0},
        "steps": row.get("step", 0),
        "started_at": row.get("started_at", ""),
        "ended_at": row.get("ended_at", ""),
        "audit": {
            "log_verified": bool(row.get("log_verified")),
            "tampered": row.get("audit_of_opponent") == refaudit.TAMPERED,
            "result_agreed": bool(row.get("result_agreed")),
        },
        "log_files": [f"log_{game_id}_g{n:02d}.json"],
    }


# -- mutual result signature (their §7.2 / Task 8) ----------------------------
def build_mutual_doc(game_id: str, rows: list[dict[str, Any]],
                     our_group: str, their_group: str,
                     tie_award: int = 2) -> dict[str, Any]:
    """The signed consensus object: EXACTLY ``{game_id, aggregate, sub_games}``.

    ``rows`` are five-key consensus rows (sub_game_number, result, roles,
    score, winner_group) with roles/score keyed BY GROUP ID. No game_uid, no
    groups, no timestamps, no tokens, no commits, no paths, no steps, no
    audit metadata — those live in the wider report, never in this preimage.

    Tie rule (pinned by NajAmjad's authoritative filed example, digest
    ``a3645e1f…``): on an equal raw sum, the book's +2 series-tie award is
    ADDED INTO ``aggregate.total_score`` for BOTH teams — a clean 3-3 of
    captures sums 75-75 raw and is SIGNED as 77-77 — with ``winner_group``
    null and ``series_tie`` true. The aggregate carries EXACTLY five keys
    (series_tie, sub_games_won, ties, total_score, winner_group); there is
    no ``tie_award`` key inside the signed preimage. Any raw-sum display
    belongs outside this object.
    """
    ordered = sorted((dict(r) for r in rows),
                     key=lambda r: r["sub_game_number"])
    total: dict[str, int] = {our_group: 0, their_group: 0}
    wins: dict[str, int] = {our_group: 0, their_group: 0}
    ties = 0
    for row in ordered:
        for group, score in row["score"].items():
            total[group] = total.get(group, 0) + score
        winner = row.get("winner_group")
        if winner is None:
            ties += 1
        elif winner in wins:
            wins[winner] += 1
    series_tie = total[our_group] == total[their_group]
    winner_group = None if series_tie else max(total, key=lambda g: total[g])
    if series_tie:
        for group in total:
            total[group] += tie_award       # signed INSIDE total_score (77-77)
    aggregate: dict[str, Any] = {
        "total_score": dict(total),
        "sub_games_won": dict(wins),
        "ties": ties,
        "winner_group": winner_group,
        "series_tie": series_tie,
    }
    return {"game_id": game_id, "aggregate": aggregate, "sub_games": ordered}


def mutual_digest(doc: dict[str, Any]) -> str:
    """SHA-256 over the SPACED serialisation (their §7.2).

    ``json.dumps(doc, sort_keys=True, ensure_ascii=False)`` — the
    interpreter's DEFAULT separators ``", "`` and ``": "``, deliberately NOT
    the compact form used for commit/reveal, and NOT ``refcrypto.
    mutual_digest`` (ahk-yosi shape) nor ``consensus.consensus_sha``
    (amireman compact form). Keyed apart so no profile can drift another.
    """
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
