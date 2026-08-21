"""Causal Debt -- what UNWIND shows you on a normal day, when nothing has broken.

Without this the product is dormant between retractions, and a dormant product
is a demo rather than a system. Causal debt is a live measure of unresolved
future consequence: how much of what the company has already committed to is
standing on premises that are uncertain, stale, conflicting, or fragile --
weighted by how exposed the commitment is and how hard it would be to take back.

It is deliberately NOT a prediction. Nothing here estimates a probability of
anything. It is an accounting identity over facts already recorded: confidence
values, claim ages, load counts, and effect reversibility.

EVERY CONTRIBUTION NAMES ITS PREMISE. A debt total nobody can attribute is a
number on a dashboard. `DebtContribution` carries the claim id, the factor, the
inputs and the arithmetic, so an operator can always ask "why is this number
what it is" and get a premise back rather than a shrug.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from lib.config import Tier
from lib.schema import (
    CausalDebtScore,
    Claim,
    ClaimStatus,
    Conclusion,
    ConclusionStatus,
    DebtContribution,
    DebtFactor,
)
from lib.telemetry import tool_call_span
from spine.escapement import lookup_escapement

#: [ASSUMPTION] Factor weights are judgement, not measurement. They are here in
#: one place so the ranking can be argued with rather than reverse-engineered.
FACTOR_WEIGHT: dict[DebtFactor, float] = {
    DebtFactor.UNCERTAIN: 1.0,
    DebtFactor.STALE: 0.8,
    DebtFactor.CONFLICTING: 1.5,
    DebtFactor.FRAGILE: 0.6,
}

#: A premise reaffirmed within this window carries no staleness. Beyond it,
#: staleness rises linearly and saturates at STALE_SATURATION_DAYS.
STALE_GRACE_DAYS = 90.0
STALE_SATURATION_DAYS = 730.0

#: Load above this is treated as maximally fragile. A premise carrying 200
#: dependents is not meaningfully more fragile than one carrying 100 -- both are
#: "everything falls over".
FRAGILE_SATURATION_LOAD = 100.0

#: Contributions below this are dropped to keep the report readable. Reported in
#: the output so the total is never silently short.
MIN_CONTRIBUTION = 0.001


@dataclass
class DebtReport:
    score: CausalDebtScore
    contributions: list[DebtContribution] = field(default_factory=list)
    dropped_below_threshold: int = 0
    dropped_total: float = 0.0


def _staleness(claim: Claim, as_of: datetime) -> float:
    age_days = (as_of - claim.valid_from).total_seconds() / 86400.0
    if age_days <= STALE_GRACE_DAYS:
        return 0.0
    span = STALE_SATURATION_DAYS - STALE_GRACE_DAYS
    return min(1.0, (age_days - STALE_GRACE_DAYS) / span)


def _fragility(claim: Claim) -> float:
    return min(1.0, claim.load_weight / FRAGILE_SATURATION_LOAD)


def _conflicts(claims: list[Claim]) -> dict[str, set[str]]:
    """Live claims that assert different values for the same canonical fact.

    Two sources disagreeing about one fact is the most expensive kind of debt,
    because until it is settled every decision downstream is standing on a coin
    flip that nobody has flipped.
    """
    by_canonical: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        if claim.status is ClaimStatus.LIVE:
            by_canonical[claim.canonical].append(claim)

    conflicted: dict[str, set[str]] = {}
    for canonical, group in by_canonical.items():
        values = {str(c.value) for c in group}
        if len(values) > 1:
            conflicted[canonical] = {c.claim_id for c in group}
    return conflicted


def score_causal_debt(
    claims: list[Claim],
    conclusions: list[Conclusion],
    as_of: datetime,
    top_n: int = 20,
) -> DebtReport:
    """Compute the standing debt across every live conclusion. No model call."""
    with tool_call_span("causal_debt", Tier.T1, conclusions=len(conclusions)) as span:
        claims_by_id = {c.claim_id: c for c in claims}
        conflicted = _conflicts(claims)

        contributions: list[DebtContribution] = []
        dropped_count = 0
        dropped_total = 0.0
        by_factor: dict[str, float] = defaultdict(float)
        by_claim: dict[str, float] = defaultdict(float)
        by_conclusion: dict[str, float] = defaultdict(float)
        scored_conclusions = 0

        for conclusion in conclusions:
            if conclusion.status in {
                ConclusionStatus.SUPERSEDED,
                ConclusionStatus.CORRECTED,
            }:
                continue
            if conclusion.closes_at is not None and conclusion.closes_at <= as_of:
                # Already closed out. It can no longer accrue consequence.
                continue

            escapement = lookup_escapement(conclusion, as_of=as_of)
            # Exposure: something already outside the company, that costs money,
            # carries more standing consequence than an internal draft.
            exposure = 1.0 + (1.0 if escapement.escaped else 0.0)
            if escapement.amount_minor_at_risk:
                exposure += min(2.0, escapement.amount_minor_at_risk / 1_000_000.0)
            irreversibility = max(0.1, escapement.worst_irreversibility)

            scored_conclusions += 1
            for claim_id in conclusion.premise_ids:
                claim = claims_by_id.get(claim_id)
                if claim is None or claim.status is not ClaimStatus.LIVE:
                    continue

                factors: list[tuple[DebtFactor, float, str]] = [
                    (
                        DebtFactor.UNCERTAIN,
                        1.0 - claim.confidence,
                        f"confidence {claim.confidence:.2f}",
                    ),
                    (
                        DebtFactor.STALE,
                        _staleness(claim, as_of),
                        f"last affirmed {claim.valid_from.date().isoformat()}",
                    ),
                    (
                        DebtFactor.FRAGILE,
                        _fragility(claim),
                        f"{claim.load_weight} dependents",
                    ),
                ]
                if claim.canonical in conflicted:
                    others = sorted(conflicted[claim.canonical] - {claim_id})
                    factors.append(
                        (
                            DebtFactor.CONFLICTING,
                            1.0,
                            f"disagrees with {', '.join(others) or 'another live claim'}",
                        )
                    )

                for factor, value, note in factors:
                    if value <= 0:
                        continue
                    amount = FACTOR_WEIGHT[factor] * value * exposure * irreversibility
                    if amount < MIN_CONTRIBUTION:
                        dropped_count += 1
                        dropped_total += amount
                        continue
                    contributions.append(
                        DebtContribution(
                            conclusion_id=conclusion.conclusion_id,
                            claim_id=claim_id,
                            claim_canonical=claim.canonical,
                            factor=factor,
                            factor_value=round(value, 6),
                            exposure=round(exposure, 6),
                            irreversibility=round(irreversibility, 6),
                            contribution=round(amount, 6),
                            explanation=(
                                f"{conclusion.conclusion_id} stands on "
                                f"{claim.canonical} ({claim_id}), which is "
                                f"{factor.value}: {note}. Weighted by exposure "
                                f"{exposure:.2f} and irreversibility "
                                f"{irreversibility:.2f}."
                            ),
                        )
                    )
                    by_factor[factor.value] += amount
                    by_claim[claim_id] += amount
                    by_conclusion[conclusion.conclusion_id] += amount

        total = sum(by_factor.values())
        top_claims = [
            {
                "claim_id": claim_id,
                "canonical": claims_by_id[claim_id].canonical,
                "debt": round(amount, 4),
                "load_weight": claims_by_id[claim_id].load_weight,
            }
            for claim_id, amount in sorted(by_claim.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        ]
        top_conclusions = [
            {"conclusion_id": conclusion_id, "debt": round(amount, 4)}
            for conclusion_id, amount in sorted(
                by_conclusion.items(), key=lambda kv: (-kv[1], kv[0])
            )[:top_n]
        ]

        score = CausalDebtScore(
            as_of=as_of,
            total=round(total, 4),
            conclusions_scored=scored_conclusions,
            claims_implicated=len(by_claim),
            by_factor={k: round(v, 4) for k, v in sorted(by_factor.items())},
            top_claims=top_claims,
            top_conclusions=top_conclusions,
        )
        span.set_attribute("unwind.causal_debt_total", score.total)
        span.set_attribute("unwind.conclusions_scored", scored_conclusions)
        return DebtReport(
            score=score,
            contributions=contributions,
            dropped_below_threshold=dropped_count,
            dropped_total=round(dropped_total, 6),
        )
