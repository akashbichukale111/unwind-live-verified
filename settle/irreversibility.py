"""Irreversibility triage: what can still be taken back, and what cannot.

Every external effect lands in exactly one of three buckets:

    IDEMPOTENT   re-issuing the corrected artifact converges; no residue
    COMPENSABLE  cannot be undone, but a reverse path exists
    IRREVERSIBLE money or trust already left; only a correction remains

⚠ THE BIAS IS DELIBERATE AND IT POINTS AT IRREVERSIBLE.

    An effect this module cannot classify is IRREVERSIBLE, not UNKNOWN and
    certainly not idempotent. The asymmetry is the whole reason to have a
    default: mis-classifying an irreversible payment as idempotent produces an
    automated unwind attempt against money that has already gone, while
    mis-classifying an idempotent email as irreversible produces one unnecessary
    human signature. One of those costs five minutes; the other costs the
    relationship the correction was supposed to protect.

Above a cost threshold, a COMPENSABLE classification does not settle itself
either -- it goes to the approval broker regardless, because "a reverse path
exists" is a claim about a system, and systems are wrong about themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.config import Tier
from lib.schema import ExternalEffect, Reversibility
from lib.telemetry import policy_gate_span

#: [ASSUMPTION] Money above which a compensable effect still needs a signature.
#: $1,000 in minor units. Below it, an automated reverse path is proportionate.
COMPENSABLE_SIGNATURE_THRESHOLD_MINOR = 100_000

#: Operations whose reversal genuinely converges: re-issuing the corrected
#: artifact overwrites the wrong one and leaves no residue. Keyed by (connector,
#: op) because `send` means something different on email than on payments.
_IDEMPOTENT: frozenset[tuple[str, str]] = frozenset(
    {
        ("email", "send_quote"),
        ("email", "send_commitment"),
        ("erp", "issue_po"),
        ("erp", "update_schedule"),
    }
)

#: Operations with a native reverse path that does not restore the original
#: state but does discharge the obligation.
_COMPENSABLE: frozenset[tuple[str, str]] = frozenset(
    {
        ("payments", "issue_credit"),
        ("ads", "launch_flight"),
        ("erp", "reserve_capacity"),
    }
)

#: Operations known to be one-way. Listed explicitly so the classification is a
#: fact about the operation rather than a consequence of the default.
_IRREVERSIBLE: frozenset[tuple[str, str]] = frozenset(
    {
        ("payments", "pay_invoice"),
        ("payments", "settle_batch"),
        ("payments", "pay_expedite_premium"),
        ("email", "send_apology"),
        ("contracts", "countersign"),
        # A countersignature is one-way whatever the connector claims. The
        # corpus records this op as `idempotent`, which is a connector being
        # wrong about itself -- exactly the disagreement the max() above exists
        # to resolve, and it fires on 232 real effects rather than a fixture.
        ("email", "countersign_framework"),
    }
)


@dataclass(frozen=True)
class Triage:
    """One effect, classified, with the reason it landed where it did."""

    effect: ExternalEffect
    reversibility: Reversibility
    reason: str
    #: True when the classification came from the conservative default rather
    #: than from knowledge. Surfaced so a reader can tell the two apart.
    defaulted: bool
    requires_signature: bool

    @property
    def recoverable(self) -> bool:
        return self.reversibility is not Reversibility.IRREVERSIBLE


#: Severity order. The triage takes the MAXIMUM of what the record claims and
#: what the operation is known to be, so the two can only ever disagree in the
#: safe direction.
_SEVERITY: dict[Reversibility, int] = {
    Reversibility.IDEMPOTENT: 0,
    Reversibility.COMPENSABLE: 1,
    Reversibility.IRREVERSIBLE: 2,
}


def _from_op_table(effect: ExternalEffect) -> tuple[Reversibility, bool]:
    """What the OPERATION is known to be, independent of what the record says.

    Returns the classification and whether it came from the conservative
    default rather than from knowledge.
    """
    key = (effect.connector, effect.op)
    if key in _IRREVERSIBLE:
        return Reversibility.IRREVERSIBLE, False
    if key in _COMPENSABLE:
        return Reversibility.COMPENSABLE, False
    if key in _IDEMPOTENT:
        return Reversibility.IDEMPOTENT, False
    # Unrecognised operation: no opinion, so it does not drag the record
    # upwards on its own. The record's own UNKNOWN is what triggers the default.
    return Reversibility.IDEMPOTENT, True


def triage_effect(effect: ExternalEffect) -> Triage:
    """Classify one effect. Never returns UNKNOWN -- that is the point.

    Two independent signals are combined, and the more conservative wins:

        THE RECORD     what the connector said when the effect was written
        THE OP TABLE   what this operation is known to be, here

    Taking the maximum matters because the two disagree in exactly one
    interesting case: a record claiming a countersignature or a payment is
    "idempotent". That is a connector being wrong about itself, and believing
    it would send an automated unwind at something already signed.
    """
    amount = effect.amount_minor or 0
    recorded = effect.reversibility
    from_table, unrecognised = _from_op_table(effect)

    if recorded is Reversibility.UNKNOWN:
        # The record could not determine it. This is the conservative default,
        # and it is not a fallback that "should never happen" -- an unsynced
        # connector is the normal case.
        return Triage(
            effect=effect,
            reversibility=Reversibility.IRREVERSIBLE,
            reason=(
                f"the record could not determine reversibility for "
                f"{effect.connector}.{effect.op}; classified irreversible by the "
                "conservative default so it reaches a human rather than an "
                "automated unwind."
            ),
            defaulted=True,
            requires_signature=True,
        )

    resolved = max((recorded, from_table), key=lambda r: _SEVERITY[r])
    overridden = resolved is not recorded

    if resolved is Reversibility.IRREVERSIBLE:
        reason = f"{effect.connector}.{effect.op} is a one-way operation" + (
            f"; the record claimed {recorded.value}, which is not believed for this operation."
            if overridden
            else "."
        )
        return Triage(
            effect=effect,
            reversibility=resolved,
            reason=reason,
            defaulted=False,
            requires_signature=True,
        )

    if resolved is Reversibility.COMPENSABLE:
        needs = amount >= COMPENSABLE_SIGNATURE_THRESHOLD_MINOR
        return Triage(
            effect=effect,
            reversibility=resolved,
            reason=(
                f"{effect.connector}.{effect.op} has a reverse path"
                + (
                    f", and {amount} minor units is at or above the "
                    f"{COMPENSABLE_SIGNATURE_THRESHOLD_MINOR} signature threshold."
                    if needs
                    else " within the automatic threshold."
                )
            ),
            defaulted=False,
            requires_signature=needs,
        )

    return Triage(
        effect=effect,
        reversibility=Reversibility.IDEMPOTENT,
        reason=(
            f"re-issuing {effect.connector}.{effect.op} converges on the corrected "
            "artifact"
            + (
                " (operation not in the classification table; the record's "
                "idempotent claim was taken at face value)."
                if unrecognised
                else "."
            )
        ),
        defaulted=False,
        requires_signature=False,
    )


def triage_all(effects: list[ExternalEffect]) -> list[Triage]:
    with policy_gate_span("irreversibility_triage", Tier.T1) as span:
        results = [triage_effect(e) for e in effects]
        span.set_attribute("unwind.effects", len(results))
        span.set_attribute(
            "unwind.irreversible",
            sum(1 for r in results if r.reversibility is Reversibility.IRREVERSIBLE),
        )
        span.set_attribute("unwind.defaulted", sum(1 for r in results if r.defaulted))
        return results
