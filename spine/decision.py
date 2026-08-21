"""The five-state decision router. Deterministic, and it owns the authority gate.

    EXECUTE · ASK_HUMAN · RETRY · DEFER · REFUSE

ONE DECISION VOCABULARY, NOT TWO
--------------------------------
Task 2 had the authority gate returning its own verdict type alongside a
`StatedDecision` enum that nothing produced. That is two vocabularies for one
question, and the second one always rots. The gate now returns a REFUSE through
this router, so every place the system declines to act says so the same way.

DEFER IS THE STATE NOBODY ELSE HAS
----------------------------------
The other four are familiar. DEFER means something specific and operational:
*this premise is contested — two live sources disagree about the same fact and
neither has withdrawn — so hold the cascade until they settle it.* It is not a
retry, because time alone will not fix it. It is not a refusal, because the
retraction may well be correct. It is not an escalation, because the person who
can resolve it is the source, not an operator. A supplier disputing what it said
last week is an ordinary Tuesday, and every system I have seen either picks a
side silently or drops the message.

Nothing in this module calls a model. It is a rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from lib.config import Tier
from lib.schema import (
    AuthorityDecision,
    Claim,
    ClaimStatus,
    DecisionState,
    Source,
    StatedDecision,
)
from lib.telemetry import policy_gate_span
from spine.authority import check_authority

ROUTER_ID = "five-state-router@0.3.0"


class DecisionReason(str, Enum):
    """Closed vocabulary. Free text explains; the code is what gets counted."""

    # REFUSE
    NO_STANDING = "no_standing"
    NO_SUCH_SOURCE = "no_such_source"
    NO_SUCH_CLAIM = "no_such_claim"
    CLAIM_NOT_LIVE = "claim_not_live"
    BELOW_CONFIDENCE_FLOOR = "below_confidence_floor"
    SINGLE_SOURCE_ABOVE_THRESHOLD = "single_source_above_threshold"
    # DEFER
    PREMISE_CONTESTED = "premise_contested"
    # ASK_HUMAN
    BLAST_RADIUS_REQUIRES_CONFIRMATION = "blast_radius_requires_confirmation"
    LOW_MARGIN_RECONCILIATION = "low_margin_reconciliation"
    # RETRY
    TRANSIENT_FAILURE = "transient_failure"
    # EXECUTE
    ALL_GATES_PASSED = "all_gates_passed"


#: Which states permit a cascade to proceed. Exactly one does.
PROCEEDING_STATES: frozenset[DecisionState] = frozenset({DecisionState.EXECUTE})


@dataclass
class RetractionRequest:
    """A proposed retraction, before anything has been decided about it."""

    claim_id: str
    source_id: str
    new_value: float | str | bool | None
    reason: str = ""
    #: Extraction confidence, where the retraction came from an artifact.
    confidence: float = 1.0
    #: Distinct corroborating sources asserting the same change, including this
    #: one. The two-source rule reads this.
    corroborating_sources: list[str] = field(default_factory=list)
    #: Set when the request arrived after a failure that may succeed on a retry.
    transient_error: str | None = None


@dataclass
class DecisionContext:
    """Everything the router is allowed to look at. All of it already computed."""

    blast_radius: int
    #: Live claims other than this one asserting the same canonical fact.
    contesting_claims: list[Claim] = field(default_factory=list)
    #: Money already committed across the radius, in minor units.
    exposure_minor: int = 0


def decide_admissibility(
    request: RetractionRequest,
    source: Source | None,
    claim: Claim | None,
    contesting_claims: list[Claim],
    now: datetime,
) -> tuple[StatedDecision | None, AuthorityDecision]:
    """Everything decidable BEFORE the blast radius is known.

    Standing, contest and transient failure need no radius, and each of them can
    stop a cascade outright — so they run first, before a single edge is walked.
    Returns `None` for the decision when the request is admissible and the
    authorisation half should run.

    THE GATE IS IN TWO HALVES BECAUSE ITS HALVES NEED DIFFERENT INFORMATION.
    The confidence floor scales with blast radius, and blast radius is not
    knowable until the traversal has run. That is fine, because the traversal is
    free: T0 makes no model call. So admissibility gates the cheap work, and
    authorisation gates the expensive and irreversible work that follows it.
    """
    with policy_gate_span("gate_admissibility", Tier.T0, claim_id=request.claim_id) as span:
        authority = check_authority(source, claim, request.source_id, request.claim_id, now=now)

        # --- 1. Standing. Nothing else is even asked until this passes. -----
        if not authority.allowed:
            decision = _refuse(
                _AUTHORITY_TO_REASON.get(authority.reason_code.value, DecisionReason.NO_STANDING),
                authority.reason,
                now,
            )
            _annotate(
                span,
                decision,
                _AUTHORITY_TO_REASON.get(authority.reason_code.value, DecisionReason.NO_STANDING),
            )
            return decision, authority

        # --- 2. Contest. A disputed premise is held, not resolved. ----------
        if contesting_claims:
            others = ", ".join(
                f"{c.claim_id} says {c.value!r} (from {c.source_id})"
                for c in sorted(contesting_claims, key=lambda c: c.claim_id)
            )
            decision = StatedDecision(
                state=DecisionState.DEFER,
                why=(
                    f"{claim.canonical if claim else request.claim_id} is contested: "
                    f"{others}. Two live sources disagree about one fact and neither "
                    "has withdrawn. Holding the cascade until the sources settle it "
                    "-- picking a side here would propagate a guess to every "
                    "commitment underneath."
                ),
                tier=Tier.T0.value,
                decided_at=now,
            )
            _annotate(span, decision, DecisionReason.PREMISE_CONTESTED)
            return decision, authority

        # --- 3. A transient failure is a retry, not a refusal. --------------
        if request.transient_error:
            decision = StatedDecision(
                state=DecisionState.RETRY,
                why=(
                    f"The request failed transiently ({request.transient_error}). "
                    "Retrying: nothing about the retraction itself is in doubt."
                ),
                tier=Tier.T0.value,
                decided_at=now,
            )
            _annotate(span, decision, DecisionReason.TRANSIENT_FAILURE)
            return decision, authority

        span.set_attribute("unwind.admissible", True)
        return None, authority


def decide_authorisation(
    request: RetractionRequest,
    claim: Claim | None,
    context: DecisionContext,
    now: datetime,
    floor: object | None = None,
) -> StatedDecision:
    """Everything that needs the blast radius: confidence floor, corroboration.

    Runs after the traversal, because the bar is set by what acting would cost
    and that is not knowable until the radius is mapped.
    """
    from spine.defence import ConfidenceFloor  # noqa: PLC0415 - avoids a cycle

    policy: ConfidenceFloor = floor or ConfidenceFloor()

    with policy_gate_span("gate_authorisation", Tier.T0, claim_id=request.claim_id) as span:
        verdict = policy.evaluate(
            confidence=request.confidence,
            blast_radius=context.blast_radius,
            exposure_minor=context.exposure_minor,
            corroborating_sources=request.corroborating_sources or [request.source_id],
        )
        if not verdict.passed:
            decision = StatedDecision(
                state=verdict.state, why=verdict.why, tier=Tier.T0.value, decided_at=now
            )
            _annotate(span, decision, verdict.reason_code)
            return decision

        decision = StatedDecision(
            state=DecisionState.EXECUTE,
            why=(
                f"{request.source_id} has standing over "
                f"{claim.canonical if claim else request.claim_id}, no live claim "
                f"contests it, and confidence {request.confidence:.2f} clears the "
                f"floor of {verdict.required_confidence:.2f} for a radius of "
                f"{context.blast_radius}."
            ),
            tier=Tier.T0.value,
            decided_at=now,
        )
        _annotate(span, decision, DecisionReason.ALL_GATES_PASSED)
        return decision


def decide(
    request: RetractionRequest,
    source: Source | None,
    claim: Claim | None,
    context: DecisionContext,
    now: datetime,
    floor: object | None = None,
) -> tuple[StatedDecision, AuthorityDecision]:
    """Both halves, for callers that already know the radius (tests, evals)."""
    decision, authority = decide_admissibility(
        request, source, claim, context.contesting_claims, now
    )
    if decision is not None:
        return decision, authority
    return decide_authorisation(request, claim, context, now, floor), authority


_AUTHORITY_TO_REASON: dict[str, DecisionReason] = {
    "no_such_source": DecisionReason.NO_SUCH_SOURCE,
    "no_such_claim": DecisionReason.NO_SUCH_CLAIM,
    "claim_not_live": DecisionReason.CLAIM_NOT_LIVE,
    "source_outside_claim_scope": DecisionReason.NO_STANDING,
}


def _refuse(reason_code: DecisionReason, why: str, now: datetime) -> StatedDecision:
    return StatedDecision(state=DecisionState.REFUSE, why=why, tier=Tier.T0.value, decided_at=now)


def _annotate(span, decision: StatedDecision, reason_code: DecisionReason | None = None) -> None:
    span.set_attribute("unwind.decision_state", decision.state.value)
    span.set_attribute("unwind.proceeds", decision.state in PROCEEDING_STATES)
    if reason_code is not None:
        span.set_attribute("unwind.decision_reason", reason_code.value)


def find_contesting_claims(claim: Claim | None, all_claims: list[Claim]) -> list[Claim]:
    """Live claims asserting the same canonical fact with a different value.

    This is what turns DEFER from an idea into a state the system can reach: the
    contest is discovered from the graph, not declared by a human.
    """
    if claim is None:
        return []
    return sorted(
        (
            other
            for other in all_claims
            if other.claim_id != claim.claim_id
            and other.canonical == claim.canonical
            and other.status is ClaimStatus.LIVE
            and str(other.value) != str(claim.value)
        ),
        key=lambda c: c.claim_id,
    )
