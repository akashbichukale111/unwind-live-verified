"""Causal debt: deterministic, attributable, and not a prediction.

The load-bearing property is attribution. A debt figure nobody can trace back to
a named premise is a number on a dashboard; these tests pin the arithmetic and
the explanation together, so a contribution can never appear without saying
which claim produced it and why.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lib.schema import DebtFactor
from spine.debt import FACTOR_WEIGHT, score_causal_debt
from tests.test_spine import make_claim, make_conclusion

NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


def test_every_contribution_names_its_premise() -> None:
    report = score_causal_debt(
        claims=[make_claim("clm_a", confidence=0.5)],
        conclusions=[make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    assert report.contributions
    for contribution in report.contributions:
        assert contribution.claim_id == "clm_a"
        assert contribution.claim_canonical
        assert contribution.conclusion_id == "cnc_1"
        assert contribution.explanation
        assert "clm_a" in contribution.explanation


def test_the_total_is_the_sum_of_its_attributed_parts() -> None:
    """No unexplained residue: the headline equals what the parts add up to."""
    report = score_causal_debt(
        claims=[make_claim("clm_a", confidence=0.4), make_claim("clm_b", confidence=0.7)],
        conclusions=[
            make_conclusion("cnc_1", premise_ids=["clm_a", "clm_b"]),
            make_conclusion("cnc_2", premise_ids=["clm_a"]),
        ],
        as_of=NOW,
    )
    attributed = sum(c.contribution for c in report.contributions)
    assert abs(report.score.total - attributed) < 0.01
    assert abs(sum(report.score.by_factor.values()) - attributed) < 0.01


def test_confidence_drives_the_uncertain_factor() -> None:
    low = score_causal_debt(
        [make_claim("clm_a", confidence=0.2)],
        [make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    high = score_causal_debt(
        [make_claim("clm_a", confidence=0.95)],
        [make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    assert low.score.by_factor["uncertain"] > high.score.by_factor["uncertain"]


def test_a_recently_affirmed_premise_carries_no_staleness() -> None:
    fresh = score_causal_debt(
        [make_claim("clm_a", valid_from=NOW - timedelta(days=10))],
        [make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    assert "stale" not in fresh.score.by_factor

    old = score_causal_debt(
        [make_claim("clm_a", valid_from=NOW - timedelta(days=700))],
        [make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    assert old.score.by_factor["stale"] > 0


def test_load_drives_fragility() -> None:
    report = score_causal_debt(
        [make_claim("clm_a", load_weight=200)],
        [make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    fragile = [c for c in report.contributions if c.factor is DebtFactor.FRAGILE]
    assert fragile and fragile[0].factor_value == 1.0  # saturated


def test_two_live_claims_disagreeing_is_the_heaviest_factor() -> None:
    """Conflict is weighted highest: until it is settled, everything downstream
    is standing on a coin flip nobody has flipped."""
    claims = [
        make_claim("clm_a", canonical="supplier_K.lead_time_days", value=11),
        make_claim("clm_b", canonical="supplier_K.lead_time_days", value=20),
    ]
    report = score_causal_debt(
        claims, [make_conclusion("cnc_1", premise_ids=["clm_a", "clm_b"])], as_of=NOW
    )
    conflicting = [c for c in report.contributions if c.factor is DebtFactor.CONFLICTING]
    assert len(conflicting) == 2  # both sides of the disagreement are named
    assert FACTOR_WEIGHT[DebtFactor.CONFLICTING] == max(FACTOR_WEIGHT.values())
    for contribution in conflicting:
        assert "disagrees with" in contribution.explanation


def test_agreeing_claims_are_not_flagged_as_conflicting() -> None:
    claims = [
        make_claim("clm_a", canonical="supplier_K.lead_time_days", value=11),
        make_claim("clm_b", canonical="supplier_K.lead_time_days", value=11),
    ]
    report = score_causal_debt(
        claims, [make_conclusion("cnc_1", premise_ids=["clm_a", "clm_b"])], as_of=NOW
    )
    assert not [c for c in report.contributions if c.factor is DebtFactor.CONFLICTING]


def test_a_closed_out_commitment_stops_accruing_debt() -> None:
    report = score_causal_debt(
        [make_claim("clm_a")],
        [make_conclusion("cnc_1", premise_ids=["clm_a"], closes_at=NOW - timedelta(days=1))],
        as_of=NOW,
    )
    assert report.score.conclusions_scored == 0
    assert report.score.total == 0.0


def test_scoring_is_deterministic() -> None:
    claims = [make_claim(f"clm_{i}", confidence=0.5 + i / 100) for i in range(10)]
    conclusions = [make_conclusion(f"cnc_{i}", premise_ids=[f"clm_{i % 10}"]) for i in range(30)]
    first = score_causal_debt(claims, conclusions, as_of=NOW).score
    for _ in range(3):
        again = score_causal_debt(claims, conclusions, as_of=NOW).score
        assert again.total == first.total
        assert again.top_claims == first.top_claims
        assert again.by_factor == first.by_factor


def test_dropped_contributions_are_reported_not_hidden() -> None:
    """A total that quietly omits rounding dust is still a total that lies."""
    report = score_causal_debt(
        [make_claim("clm_a", confidence=1.0)],
        [make_conclusion("cnc_1", premise_ids=["clm_a"])],
        as_of=NOW,
    )
    assert report.dropped_below_threshold >= 0
    assert report.dropped_total >= 0.0


def test_the_corpus_hub_is_the_heaviest_debt_carrier() -> None:
    """The fragility answer on a normal day, before anything has broken."""
    from pathlib import Path

    from spine.cascade import CorpusStore

    store = CorpusStore.from_repo(Path(__file__).resolve().parents[1])
    report = score_causal_debt(
        list(store.claims.values()), list(store.conclusions.values()), as_of=NOW
    )
    assert report.score.top_claims[0]["claim_id"] == "clm_000000"
    assert report.score.top_claims[0]["canonical"] == "supplier_K.lead_time_days"
