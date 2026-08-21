"""Escapement -- did this decision already leave the building?

Escapement decides which of the four regimes a conclusion lands in, and only one
of those cells is an alert. A decision still sitting inside the company can be
corrected in place and nobody outside ever knows. A decision that was sent,
signed, shipped or paid cannot; the only remaining move is to tell someone.

THE DEFAULT IS ESCAPED, DELIBERATELY
------------------------------------
When the effect record is missing or unreadable, this returns ESCAPED. The
asymmetry is the whole design: treating a contained item as escaped costs one
wasted check by one person; treating an escaped item as contained means a
customer is never told. Fail-safe here means fail-noisy.

An EMPTY effect list is not a missing record. `external_effects: []` with
`effects_recorded: True` is a positive assertion that nothing left the building,
and it is believed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from lib.config import Tier
from lib.schema import Conclusion, ExternalEffect, Reversibility
from lib.telemetry import tool_call_span

#: How hard each class of effect is to take back. Used by the budgeter to decide
#: how much investigation a radius earns, and by Task 4 to pick a settlement.
IRREVERSIBILITY: dict[Reversibility, float] = {
    Reversibility.IDEMPOTENT: 0.1,
    Reversibility.COMPENSABLE: 0.5,
    Reversibility.IRREVERSIBLE: 1.0,
    #: Unknown is scored close to irreversible on purpose. An effect nobody can
    #: classify is not evidence that it is cheap to undo.
    Reversibility.UNKNOWN: 0.8,
}


@dataclass
class EscapementVerdict:
    escaped: bool
    reason_code: str
    reason: str
    effects: list[ExternalEffect] = field(default_factory=list)
    earliest_escape: datetime | None = None
    amount_minor_at_risk: int = 0
    worst_irreversibility: float = 0.0

    @property
    def has_money_at_risk(self) -> bool:
        return self.amount_minor_at_risk > 0


def lookup_escapement(
    conclusion: Conclusion | None, as_of: datetime | None = None
) -> EscapementVerdict:
    """Read `external_effects` and decide whether anything got out.

    `as_of` bounds what counts: an effect scheduled after the retraction has not
    escaped yet and can still be stopped in place.
    """
    with tool_call_span("escapement_lookup", Tier.T0) as span:
        verdict = _lookup(conclusion, as_of)
        span.set_attribute("unwind.escaped", verdict.escaped)
        span.set_attribute("unwind.reason_code", verdict.reason_code)
        return verdict


def _lookup(conclusion: Conclusion | None, as_of: datetime | None) -> EscapementVerdict:
    if conclusion is None:
        return EscapementVerdict(
            escaped=True,
            reason_code="conclusion_unreadable",
            reason=(
                "The conclusion could not be read, so whether anything left the "
                "building is unknown. Failing safe to ESCAPED: an unnecessary "
                "check is cheap, an untold customer is not."
            ),
        )

    if not conclusion.effects_recorded:
        return EscapementVerdict(
            escaped=True,
            reason_code="no_effect_record",
            reason=(
                "No trustworthy outbound record exists for this conclusion. "
                "Failing safe to ESCAPED rather than assuming silence means "
                "nothing was sent."
            ),
        )

    effects = list(conclusion.external_effects)
    if as_of is not None:
        effects = [e for e in effects if e.occurred_at <= as_of]

    if not effects:
        if conclusion.external_effects:
            return EscapementVerdict(
                escaped=False,
                reason_code="effects_not_yet_occurred",
                reason=(
                    "Every recorded effect is scheduled after the retraction, so "
                    "nothing has left the building yet and it can still be "
                    "stopped in place."
                ),
            )
        return EscapementVerdict(
            escaped=False,
            reason_code="no_effects_asserted",
            reason=(
                "The effect record is present and empty: this decision was never "
                "acted on outside the company."
            ),
        )

    amount = sum(e.amount_minor or 0 for e in effects)
    worst = max(IRREVERSIBILITY[e.reversibility] for e in effects)
    earliest = min(e.occurred_at for e in effects)
    ops = sorted({f"{e.connector}.{e.op}" for e in effects})

    return EscapementVerdict(
        escaped=True,
        reason_code="effects_recorded",
        reason=(
            f"{len(effects)} effect(s) already occurred ({', '.join(ops)}), "
            f"earliest {earliest.date().isoformat()}."
        ),
        effects=effects,
        earliest_escape=earliest,
        amount_minor_at_risk=amount,
        worst_irreversibility=worst,
    )
