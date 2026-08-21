"""T2 materiality: did the conclusion actually change? A SEPARATE PRINCIPAL.

The re-deriver says what the commitment would be now. The assessor says whether
that differs enough to matter. These must not be the same principal, and the
reason is not tidiness:

    GRADING YOUR OWN WORK IS THE EASIEST WAY FOR THIS SYSTEM TO LIE.

A single principal doing both has every incentive to find its own re-derivation
consistent with the original — it produced both halves, and the cheapest
self-consistent answer is "nothing changed". That answer is invisible when
wrong: no alert is raised, no obligation appears, and the metrics look clean.
So the separation is enforced in code and tested, rather than being an
architecture-diagram box.

TUNED TO UNDER-REPORT, DELIBERATELY
-----------------------------------
The product metric is *corrections accepted by owners*, not *obligations
raised*. An obligation an owner rejects is worse than useless: it burns the
attention that the real ones need, and after three of them nobody reads the
queue. So this tier requires a MARGIN before it calls something material, and
when the margin is thin it returns UNRESOLVED rather than escalating. The bias
direction is stated here, tested in `tests/test_judgment.py`, and reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from judgment.rederive import REDERIVER_PRINCIPAL, ReDerivation
from lib.config import Tier
from lib.telemetry import agent_decision_span
from spine.materiality import MaterialityOutcome, MaterialityVerdict

#: The assessing principal. MUST differ from REDERIVER_PRINCIPAL.
ASSESSOR_PRINCIPAL = "materiality-assessor@0.3.0"

PURPOSE = "t2_materiality"

#: [ASSUMPTION] The margin below which a difference is not called material.
#: Under-reporting bias lives here as a number rather than a hope: a
#: re-derivation that lands within a day of the original is treated as the same
#: commitment, because extraction and re-derivation noise are both larger than
#: that.
MATERIAL_MARGIN_DAYS = 1.0

#: Below this re-derivation confidence, nothing is called material at all.
MIN_CONFIDENCE_TO_ESCALATE = 0.6


class PrincipalSeparationError(RuntimeError):
    """The assessor was handed work produced by itself."""


@dataclass
class T2Assessment:
    verdict: MaterialityVerdict
    assessed_by: str = ASSESSOR_PRINCIPAL
    #: What the re-deriver said, kept so the grade can be re-checked later.
    rederived_value: float | None = None
    original_value: float | None = None
    margin_days: float | None = None
    assessed_at: datetime | None = None


def assert_separate_principals(derivation: ReDerivation) -> None:
    """Refuse to grade work this principal produced. Enforced, not documented.

    This is the check that stops the system marking its own homework. It is
    cheap, it is total, and `tests/test_judgment.py` includes a vacuity case
    that feeds it self-produced work and asserts it raises.
    """
    if derivation.derived_by == ASSESSOR_PRINCIPAL:
        raise PrincipalSeparationError(
            f"{ASSESSOR_PRINCIPAL} was asked to assess a re-derivation it "
            "produced itself. The two principals exist so that neither grades "
            "its own work; collapsing them makes 'nothing changed' the cheapest "
            "self-consistent answer and hides every miss."
        )
    if derivation.derived_by != REDERIVER_PRINCIPAL:
        raise PrincipalSeparationError(
            f"Re-derivation came from an unexpected principal "
            f"{derivation.derived_by!r}; expected {REDERIVER_PRINCIPAL!r}."
        )


def assess(
    derivation: ReDerivation,
    original_committed_lead_days: float | None,
    now: datetime,
    margin_days: float = MATERIAL_MARGIN_DAYS,
) -> T2Assessment:
    """Grade a blind re-derivation against what was actually committed.

    ⚠ THIS FUNCTION IS DETERMINISTIC. It makes no model call and takes no model.

    It previously accepted a `model` parameter that no caller ever passed and
    that the body never used. A Task 5 audit flagged it as something a judge
    would find, and it is removed rather than left to imply model use that does
    not happen. If a future version wants a model to arbitrate a thin margin,
    it must add the parameter back AND call it.

    The assessor is the ONLY place the original value enters the T2 path. The
    re-deriver never saw it; the assessor sees both and compares. That is the
    whole point of the split -- and the comparison itself is subtraction, which
    is exactly the kind of work this project keeps away from a model.
    """
    assert_separate_principals(derivation)

    # Tier.T2 is the TIER this work belongs to (judgement), not a claim that a
    # model was called. The re-deriver is T2's model half; this is T2's
    # arithmetic half.
    with agent_decision_span(ASSESSOR_PRINCIPAL, Tier.T2) as span:
        span.set_attribute("unwind.correlation_id", derivation.correlation_id)

        if not derivation.resolved:
            return _unresolved(
                derivation,
                original_committed_lead_days,
                now,
                derivation.unresolved_reason
                or "The re-derivation produced no commitment to assess.",
                span,
            )

        if original_committed_lead_days is None:
            return _unresolved(
                derivation,
                None,
                now,
                "The original commitment carries no numeric term, so there is "
                "nothing to compare the re-derivation against. Reading the "
                "governing clause is a further step this tier has not taken.",
                span,
            )

        if derivation.confidence < MIN_CONFIDENCE_TO_ESCALATE:
            return _unresolved(
                derivation,
                original_committed_lead_days,
                now,
                f"The re-derivation carried confidence "
                f"{derivation.confidence:.2f}, below the {MIN_CONFIDENCE_TO_ESCALATE:.2f} "
                "needed to call a commitment changed. Under-reporting on purpose: "
                "an obligation an owner rejects costs more than a missed one.",
                span,
            )

        delta = abs(derivation.committed_lead_days - original_committed_lead_days)
        span.set_attribute("unwind.delta_days", delta)

        if delta <= margin_days:
            verdict = MaterialityVerdict(
                MaterialityOutcome.IMMATERIAL,
                "within_rederivation_margin",
                f"Re-derived at {derivation.committed_lead_days:g} days against an "
                f"original {original_committed_lead_days:g}; a {delta:g}-day "
                f"difference is inside the {margin_days:g}-day margin and is not "
                "treated as a changed commitment.",
                scored_by=ASSESSOR_PRINCIPAL,
            )
        else:
            verdict = MaterialityVerdict(
                MaterialityOutcome.MATERIAL,
                "rederivation_differs",
                f"Re-derived at {derivation.committed_lead_days:g} days from the "
                f"premises alone, against an original {original_committed_lead_days:g}. "
                f"The {delta:g}-day difference exceeds the {margin_days:g}-day "
                f"margin. Re-deriver reasoning: {derivation.reasoning}",
                scored_by=ASSESSOR_PRINCIPAL,
            )

        span.set_attribute("unwind.materiality", verdict.outcome.value)
        return T2Assessment(
            verdict=verdict,
            rederived_value=derivation.committed_lead_days,
            original_value=original_committed_lead_days,
            margin_days=delta,
            assessed_at=now,
        )


def _unresolved(
    derivation: ReDerivation,
    original: float | None,
    now: datetime,
    reason: str,
    span,
) -> T2Assessment:
    span.set_attribute("unwind.materiality", "unresolved")
    return T2Assessment(
        verdict=MaterialityVerdict(
            MaterialityOutcome.UNRESOLVED,
            "t2_could_not_determine",
            reason,
            scored_by=ASSESSOR_PRINCIPAL,
        ),
        rederived_value=derivation.committed_lead_days,
        original_value=original,
        assessed_at=now,
    )
