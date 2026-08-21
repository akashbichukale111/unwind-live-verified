"""T1 -- arithmetic materiality. Subtraction, not judgement.

A commitment holds a buffer against the premise it stands on. The retraction
delivers a shock. The commitment is harmed if and only if the shock exceeds the
buffer:

    slack_days = committed_lead_days - premise_value_before
    material   = shock_days > slack_days

Asking a model to do this would be the single worst design decision available.
It is subtraction; a model would do it correctly almost every time, and the
"almost" would be an unwind sent to a customer who did not need one.

WHAT THIS TIER REFUSES TO DO
----------------------------
Two cases route out rather than guess, and neither is defaulted to safe:

  * CONTRACTUAL / REGULATORY / RELATIONAL claims. Their falsification is a
    reading, not a computation. They are marked `pending_judgment` for T2.
  * A premise whose falsification predicate is not machine-checkable, or a
    conclusion with no recoverable committed lead time. These are UNRESOLVED,
    which is a first-class outcome and is displayed, never hidden.

THE SHOCK PROPAGATES UNDIMINISHED
---------------------------------
A conclusion four hops from the retracted claim is scored against the SAME shock
as one directly on it. [ASSUMPTION] An internal handoff is modelled as adding no
buffer of its own -- if a plan promised 30 days and the supplier slips 9, the
plan slips 9. This is the conservative direction: it can over-report harm at
depth, never under-report it. It also matches how the corpus was built, so the
eval measures whether this module is implemented correctly, not whether the
model of the world is right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from lib.config import Tier
from lib.schema import Claim, ClaimType, Conclusion
from lib.telemetry import tool_call_span

SCORER_ID = "t1-arithmetic@0.1.0"

#: Claim types whose falsification is computable. Everything else is a reading.
ARITHMETIC_CLAIM_TYPES: frozenset[ClaimType] = frozenset({ClaimType.NUMERIC, ClaimType.TEMPORAL})


class MaterialityOutcome(str, Enum):
    MATERIAL = "material"
    IMMATERIAL = "immaterial"
    #: CLOSED-OUT: the commitment discharged before the premise moved, so the
    #: shock never applied to it. Reported separately from IMMATERIAL because
    #: the reason is different -- immaterial means the buffer absorbed the move,
    #: closed-out means there was nothing left to absorb it. An operator asking
    #: "why is this not on my list" gets the true answer either way.
    CLOSED_OUT = "closed_out"
    #: Needs a reading, not a computation. T2's problem. Not a guess.
    PENDING_JUDGMENT = "pending_judgment"
    #: Could not be determined by anything. Displayed as-is.
    UNRESOLVED = "unresolved"


@dataclass
class MaterialityVerdict:
    outcome: MaterialityOutcome
    reason_code: str
    reason: str
    slack_days: int | None = None
    shock_days: int | None = None
    scored_by: str = SCORER_ID

    @property
    def material(self) -> bool | None:
        """True, False, or None. None is never coerced -- that is the point."""
        if self.outcome is MaterialityOutcome.MATERIAL:
            return True
        if self.outcome in {MaterialityOutcome.IMMATERIAL, MaterialityOutcome.CLOSED_OUT}:
            return False
        return None


def score_materiality(
    conclusion: Conclusion | None,
    root_claim: Claim,
    value_before: float,
    value_after: float,
    as_of: datetime | None = None,
) -> MaterialityVerdict:
    """Decide whether `conclusion` is harmed by the root claim's move.

    `value_before` / `value_after` describe the ROOT retraction, not the local
    premise, because the shock propagates undiminished (see module docstring).

    `as_of` is the retraction instant. It matters: a commitment that already
    closed out was fulfilled under the OLD premise and cannot be harmed by the
    new one.
    """
    with tool_call_span("t1_materiality", Tier.T1, claim_id=root_claim.claim_id) as span:
        verdict = _score(conclusion, root_claim, value_before, value_after, as_of)
        span.set_attribute("unwind.materiality", verdict.outcome.value)
        span.set_attribute("unwind.reason_code", verdict.reason_code)
        return verdict


def _score(
    conclusion: Conclusion | None,
    root_claim: Claim,
    value_before: float,
    value_after: float,
    as_of: datetime | None,
) -> MaterialityVerdict:
    if conclusion is None:
        return MaterialityVerdict(
            MaterialityOutcome.UNRESOLVED,
            "conclusion_unreadable",
            "The reverse index points at a conclusion this store cannot read. "
            "Nothing can be computed about it, so nothing is assumed.",
        )

    if root_claim.type not in ARITHMETIC_CLAIM_TYPES:
        return MaterialityVerdict(
            MaterialityOutcome.PENDING_JUDGMENT,
            "non_arithmetic_claim_type",
            f"{root_claim.canonical!r} is {root_claim.type.value}. Whether this "
            "conclusion is harmed is a reading of the claim, not a computation. "
            "Routed to T2; not guessed.",
        )

    if not root_claim.falsified_when.machine_checkable:
        return MaterialityVerdict(
            MaterialityOutcome.UNRESOLVED,
            "predicate_not_machine_checkable",
            root_claim.falsified_when.unresolvable_reason
            or "The claim's falsification predicate cannot be evaluated mechanically.",
        )

    if conclusion.committed_lead_days is None:
        return MaterialityVerdict(
            MaterialityOutcome.UNRESOLVED,
            "no_committed_lead_time",
            "This conclusion carries no recoverable committed lead time, so it "
            "holds no buffer this tier can measure. Displayed as UNRESOLVED "
            "rather than assumed unharmed.",
        )

    shock = int(round(value_after - value_before))
    slack = int(conclusion.committed_lead_days - value_before)

    # A commitment that already discharged was fulfilled under the OLD premise.
    # The new value applies going forward; it does not reach back and make a
    # delivery that already happened late. This check comes before the buffer
    # arithmetic because no amount of consumed slack matters to a closed order.
    if as_of is not None and conclusion.closes_at is not None and conclusion.closes_at <= as_of:
        return MaterialityVerdict(
            MaterialityOutcome.CLOSED_OUT,
            "already_closed_out",
            f"This commitment closed on {conclusion.closes_at.date().isoformat()}, "
            f"before the premise moved. It was fulfilled under the "
            f"{value_before:g}-day value and the new one does not reach back to it.",
            slack_days=slack,
            shock_days=shock,
        )

    if shock <= 0:
        return MaterialityVerdict(
            MaterialityOutcome.IMMATERIAL,
            "shock_not_adverse",
            f"The premise moved by {shock} days, which does not consume buffer.",
            slack_days=slack,
            shock_days=shock,
        )

    if shock > slack:
        return MaterialityVerdict(
            MaterialityOutcome.MATERIAL,
            "shock_exceeds_slack",
            f"Committed {conclusion.committed_lead_days} days against a "
            f"{value_before:g}-day premise, leaving {slack} days of buffer. The "
            f"premise moved {shock} days, which exceeds it.",
            slack_days=slack,
            shock_days=shock,
        )

    return MaterialityVerdict(
        MaterialityOutcome.IMMATERIAL,
        "slack_absorbs_shock",
        f"Committed {conclusion.committed_lead_days} days against a "
        f"{value_before:g}-day premise, leaving {slack} days of buffer, which "
        f"absorbs the {shock}-day move.",
        slack_days=slack,
        shock_days=shock,
    )
