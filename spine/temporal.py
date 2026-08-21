"""Temporal Truth propagation -- the world changed; nobody was wrong.

A claim is never TRUE or FALSE. It is a value, at a time, under a context, from a
source, with a confidence. So a retraction does not delete anything and does not
mark anyone mistaken. It closes an interval: the old value was correct from
`valid_from` until `invalidated_at`, and a new value takes over from there.

THE PRIOR VALUE REMAINS READABLE. That is not sentiment about history -- it is
what makes a cascade explainable six months later. A conclusion is only
defensible if you can still see the number it actually stood on at the moment it
was decided, and the system that overwrote that number cannot show you.

Every affected conclusion therefore records which version of the claim it stood
on, via `ClaimVersion`, rather than a pointer to a document that has since moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lib.config import Tier
from lib.schema import Claim, ClaimStatus
from lib.telemetry import tool_call_span


@dataclass(frozen=True)
class ClaimVersion:
    """The exact state of a claim at the instant a conclusion depended on it."""

    claim_id: str
    canonical: str
    value: float | str | bool | None
    unit: str | None
    valid_from: datetime
    invalidated_at: datetime | None
    source_id: str
    confidence: float

    def to_json(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "canonical": self.canonical,
            "value": self.value,
            "unit": self.unit,
            "valid_from": self.valid_from.isoformat(),
            "invalidated_at": (self.invalidated_at.isoformat() if self.invalidated_at else None),
            "source_id": self.source_id,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class Retraction:
    """The result of closing one claim's interval and opening the next."""

    #: The claim as it stood before. Kept whole, not diffed.
    prior: ClaimVersion
    #: The same claim document with the three Temporal Truth fields now set.
    retracted: Claim
    #: The successor claim carrying the new value, valid from the retraction.
    successor: Claim
    retracted_at: datetime
    reason: str


def snapshot(claim: Claim) -> ClaimVersion:
    return ClaimVersion(
        claim_id=claim.claim_id,
        canonical=claim.canonical,
        value=claim.value,
        unit=claim.unit,
        valid_from=claim.valid_from,
        invalidated_at=claim.invalidated_at,
        source_id=claim.source_id,
        confidence=claim.confidence,
    )


def retract(
    claim: Claim,
    new_value: float | str | bool | None,
    reason: str,
    at: datetime,
    successor_claim_id: str | None = None,
    successor_source_id: str | None = None,
) -> Retraction:
    """Close the claim's validity interval and open its successor's.

    Returns new objects; the input claim is not mutated, so a caller holding the
    prior version keeps holding it.
    """
    with tool_call_span("temporal_truth_propagation", Tier.T0, claim_id=claim.claim_id) as span:
        prior = snapshot(claim)

        retracted = claim.model_copy(
            update={
                "status": ClaimStatus.RETRACTED,
                "invalidated_at": at,
                # Phrased as the world moving, not as anyone erring. This string
                # reaches operators and, through Task 4, counterparties.
                "invalidation_reason": reason
                or (
                    f"The world changed: {claim.canonical} moved from "
                    f"{claim.value!r} to {new_value!r}."
                ),
            }
        )

        successor = claim.model_copy(
            update={
                "claim_id": successor_claim_id or f"{claim.claim_id}_v{int(at.timestamp())}",
                "value": new_value,
                "valid_from": at,
                "invalidated_at": None,
                "invalidation_reason": None,
                "status": ClaimStatus.LIVE,
                "source_id": successor_source_id or claim.source_id,
                "extracted_at": at,
            }
        )

        span.set_attribute("unwind.value_before", str(claim.value))
        span.set_attribute("unwind.value_after", str(new_value))
        return Retraction(
            prior=prior,
            retracted=retracted,
            successor=successor,
            retracted_at=at,
            reason=retracted.invalidation_reason or "",
        )
