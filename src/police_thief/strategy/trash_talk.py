"""Template trash-talk provider (task 4.9) — the league-default verbal layer.

Zero tokens, zero network: pre-written English lines parameterized by compass
region. Honest hints name a region that CONTAINS the agent's position; lies name
one that EXCLUDES it. No digits ever (Rule 27 bans coordinates). The move is
never influenced here — this is the rhetorical layer only (Rule 25).
"""
from __future__ import annotations

import random

Cell = tuple[int, int]

_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}

_LINES = [
    "Still slipping {d} while you stumble around",
    "You will never catch me, I drift {d} tonight",
    "The {d} side of town suits me fine",
    "Chasing shadows, officer? I am long gone {d}",
]
_NEUTRAL = [
    "No trail worth following tonight, officer",
    "You are colder than you think",
    "Keep guessing, the streets are all mine",
]


def regions_of(pos: Cell, size: int) -> list[str]:
    """Compass terms whose half-board region contains pos (may be empty at center)."""
    r, c = pos
    terms = []
    if r < size // 2:
        terms.append("north")
    elif r >= (size + 1) // 2:
        terms.append("south")
    if c < size // 2:
        terms.append("west")
    elif c >= (size + 1) // 2:
        terms.append("east")
    return terms


class TemplateProvider:
    """produce(position, intent) -> one bounded, digit-free line of banter."""

    LIE_RANGE = 3        # bluff only when the threat is close (plan 4.9 policy)
    LIE_PROB = 0.5

    def __init__(self, size: int = 7, rng: random.Random | None = None,
                 always_speak: bool = False) -> None:
        self.size = size
        self.rng = rng or random.Random(0)
        # always_speak models a CHATTY opponent (truthful at range, bluffing under
        # threat) for evaluating our own detector. Our peers stay silent by default.
        self.always_speak = always_speak

    def produce(self, position: Cell, intent: str) -> str:
        true_terms = regions_of(position, self.size)
        if intent == "neutral" or (intent == "truth" and not true_terms):
            return self.rng.choice(_NEUTRAL)         # nothing parseable to exploit
        if intent == "truth":
            d = self.rng.choice(sorted(true_terms))
        else:
            # Draw from EVERY direction that does not contain us, not merely the
            # opposite: a lie that is exactly invertible hands back the truth.
            false_terms = sorted(set(_OPPOSITE) - set(true_terms)) or sorted(_OPPOSITE)
            d = self.rng.choice(false_terms)
        return self.rng.choice(_LINES).format(d=d)

    def pick_intent(self, threat_distance: int) -> str:
        """Never volunteer a truthful compass claim: an opponent's detector verifies
        it and rewards the region — free localization for them. A caught lie leaks
        the same way (they invert it). So the default is SILENCE, and under threat
        we mix bluffs with silence, because speaking only to lie is itself a tell."""
        if threat_distance <= self.LIE_RANGE and self.rng.random() < self.LIE_PROB:
            return "lie"
        return "truth" if self.always_speak else "neutral"
