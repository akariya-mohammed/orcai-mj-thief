"""Task 4.9: template trash-talk — free text, <=15 words, NO digits (Rule 27),
intent-consistent (honest hint contains the truth, lie excludes it), 0 tokens."""
import random

from police_thief.domain.hints import parse_hint
from police_thief.strategy.trash_talk import TemplateProvider


def _samples():
    prov = TemplateProvider(size=7, rng=random.Random(42))
    for pos in [(0, 0), (5, 2), (1, 6), (6, 3), (3, 3)]:
        for intent in ("truth", "lie", "neutral"):
            yield pos, intent, prov.produce(pos, intent)


def test_word_cap_and_no_digits_everywhere():
    for _, _, text in _samples():
        assert text and len(text.split()) <= 15
        assert not any(ch.isdigit() for ch in text)        # Rule 27: no coordinates


def test_honest_hint_contains_the_truth():
    prov = TemplateProvider(size=7, rng=random.Random(1))
    for _ in range(10):
        text = prov.produce((5, 2), "truth")               # south-west in truth
        claim = parse_hint(text, 7)
        if claim is not None:                               # neutral lines parse None
            assert (5, 2) in claim.cells


def test_lie_excludes_the_truth():
    prov = TemplateProvider(size=7, rng=random.Random(2))
    for _ in range(10):
        text = prov.produce((5, 2), "lie")
        claim = parse_hint(text, 7)
        assert claim is not None                            # a lie must actually claim
        assert (5, 2) not in claim.cells


def test_center_position_still_produces_legal_output():
    prov = TemplateProvider(size=7, rng=random.Random(3))
    honest = prov.produce((3, 3), "truth")                  # center: no true compass term
    assert honest and len(honest.split()) <= 15
    lie = prov.produce((3, 3), "lie")
    assert parse_hint(lie, 7) is not None                   # any direction is a lie here


def test_same_seed_same_stream():
    a = TemplateProvider(size=7, rng=random.Random(7))
    b = TemplateProvider(size=7, rng=random.Random(7))
    assert [a.produce((5, 2), "lie") for _ in range(5)] == \
           [b.produce((5, 2), "lie") for _ in range(5)]


def test_at_range_we_volunteer_nothing():
    # P1-3: a TRUTHFUL compass hint is free localization for the opponent (their
    # detector verifies it and rewards the region). Zero information is strictly
    # better than catchable information, so at range we say nothing parseable.
    prov = TemplateProvider(size=7, rng=random.Random(9))
    assert all(prov.pick_intent(6) == "neutral" for _ in range(20))
    assert "truth" not in [prov.pick_intent(d) for d in range(1, 7) for _ in range(20)]


def test_under_threat_we_mix_bluffs_with_silence():
    # Speaking ONLY when we bluff would make "he spoke" the tell. Mix them.
    prov = TemplateProvider(size=7, rng=random.Random(9))
    near = [prov.pick_intent(2) for _ in range(50)]
    assert "lie" in near and "neutral" in near


def test_neutral_output_is_unparseable_zero_information():
    prov = TemplateProvider(size=7, rng=random.Random(11))
    for pos in [(0, 0), (5, 2), (3, 3), (6, 6)]:
        text = prov.produce(pos, "neutral")
        assert parse_hint(text, 7) is None          # no region claim leaks
        assert text and len(text.split()) <= 15
        assert not any(ch.isdigit() for ch in text)


def test_lies_are_not_exactly_invertible():
    # If a lie were always the exact opposite of the truth, an opponent could
    # simply invert it. Draw from ALL non-containing directions instead.
    prov = TemplateProvider(size=7, rng=random.Random(5))
    seen = {parse_hint(prov.produce((6, 6), "lie"), 7).terms for _ in range(40)}
    assert len(seen) > 1                            # more than one false story
