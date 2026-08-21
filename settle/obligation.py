"""The correction obligation: the product's actual output.

⚠ THIS IS THE OBJECT THAT SEPARATES UNWIND FROM A LINEAGE TOOL. A pipeline that
ends at "here are the affected decisions" has told an operator that something is
wrong and left them to do the work. This one ends at a drafted correction
addressed to a named counterparty, with the irreversible items marked
unrecoverable rather than quietly dropped from the summary.

An obligation names four things and refuses to exist without them:

    WHO   the counterparties who were told something that is no longer true
    WHAT  the actions still reversible, listed so they can actually be done
    LOSS  the residual exposure that is NOT reversible -- a RANGE with stated
          assumptions, never a point estimate
    SIGN  the human who must sign it

It hangs off `AWAITING_AUTHORISATION` (ruling 1.9) rather than inventing a new
state, because the cascade already has a word for "the analysis is complete and
nothing may leave the building yet".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.config import Tier
from lib.schema import (
    Conclusion,
    Obligation,
    ObligationStatus,
    ResidualExposure,
    Reversibility,
)
from lib.telemetry import agent_decision_span
from settle.cartography import CounterpartyMap, map_counterparties
from settle.irreversibility import Triage, triage_all

OBLIGATION_PRINCIPAL = "correction-obligation@0.4.0"


class ObligationIncompleteError(RuntimeError):
    """An obligation was built without one of the four things it must name."""


@dataclass
class DraftedObligation:
    """The obligation document, plus the working that produced it."""

    obligation: Obligation
    conclusion_id: str
    counterparty_map: CounterpartyMap
    triaged: list[Triage] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)
    correction_text: str = ""

    @property
    def counterparties(self) -> list[str]:
        return self.obligation.counterparties

    def render(self) -> str:
        """Plain text, CLI-inspectable. Making it beautiful is Task 5's job."""
        ob = self.obligation
        lines: list[str] = []
        add = lines.append
        add("=" * 68)
        add(f"CORRECTION OBLIGATION  {ob.obligation_id}")
        add("=" * 68)
        add(f"commitment      : {ob.conclusion_id}")
        add(f"status          : {ob.status.value}")
        add(f"must be signed by: {ob.approver or '(UNASSIGNED)'}")
        if ob.ruling_id:
            add(f"arising from ruling: {ob.ruling_id}")
        add("")
        add("-- WHO WAS TOLD SOMETHING THAT IS NO LONGER TRUE " + "-" * 18)
        for name in ob.counterparties:
            tellings = self.counterparty_map.for_counterparty(name)
            add(f"  {name}")
            for telling in tellings:
                add(f"     told   : {telling.told}")
                add(f"     when   : {telling.told_at.isoformat()}")
                add(f"     via    : {telling.connector} ({telling.effect_ref})")
                add(f"     now    : {telling.must_now_be_told}")
        if not ob.counterparties:
            add("  (none recorded)")
        add("")
        add("-- STILL REVERSIBLE " + "-" * 47)
        for action in ob.reversible_actions:
            add(f"  [ ] {action}")
        if not ob.reversible_actions:
            add("  (nothing reversible remains)")
        add("")
        add("-- NOT REVERSIBLE " + "-" * 49)
        for item in self.unrecoverable:
            add(f"  [X] {item}")
        if not self.unrecoverable:
            add("  (nothing unrecoverable)")
        add("")
        exposure = ob.residual_exposure
        add("-- RESIDUAL EXPOSURE (range, not a point estimate) " + "-" * 16)
        add(
            f"  {exposure.currency} {exposure.low / 100:,.2f} "
            f"-- {exposure.currency} {exposure.high / 100:,.2f}"
        )
        if exposure.unpriced_effects:
            add(
                f"  ⚠ {exposure.unpriced_effects} unrecoverable effect(s) carry no "
                "recorded amount and are NOT priced into this range."
            )
        for assumption in exposure.assumptions:
            add(f"  · {assumption}")
        add("")
        add("-- DRAFT CORRECTION " + "-" * 47)
        for line in self.correction_text.splitlines():
            add(f"  {line}")
        add("=" * 68)
        return "\n".join(lines)


def approver_for(conclusion: Conclusion) -> str:
    """The human who must sign. Deterministic, and never the owner.

    The owner is a party to the repair; routing the signature back to it would
    reintroduce exactly the conflict of interest the court removes.
    """
    return f"human::commercial-lead::{conclusion.kind.value}"


def build_obligation(
    *,
    conclusion: Conclusion,
    obligation_id: str,
    old_summary: str,
    new_summary: str,
    correction_text: str,
    ruling_id: str | None = None,
) -> DraftedObligation:
    """Assemble the obligation, and refuse to produce a partial one."""
    with agent_decision_span(OBLIGATION_PRINCIPAL, Tier.T1) as span:
        cmap = map_counterparties(conclusion, old_summary=old_summary, new_summary=new_summary)
        triaged = triage_all(conclusion.external_effects)

        reversible_actions: list[str] = []
        unrecoverable: list[str] = []
        for item in triaged:
            effect = item.effect
            label = f"{effect.connector}.{effect.op} ({effect.ref})"
            if item.reversibility is Reversibility.IDEMPOTENT:
                reversible_actions.append(f"re-issue {label} with the corrected value")
            elif item.reversibility is Reversibility.COMPENSABLE:
                reversible_actions.append(
                    f"compensate {label}"
                    + (" -- requires signature" if item.requires_signature else "")
                )
            else:
                unrecoverable.append(f"{label}: {item.reason}")

        exposure = residual_exposure(triaged)
        approver = approver_for(conclusion)

        if not approver:
            raise ObligationIncompleteError(
                "an obligation with no signatory is a note, not an obligation."
            )

        obligation = Obligation(
            obligation_id=obligation_id,
            conclusion_id=conclusion.conclusion_id,
            counterparties=cmap.counterparties,
            reversible_actions=reversible_actions,
            residual_exposure=exposure,
            approver=approver,
            status=ObligationStatus.RAISED,
            ruling_id=ruling_id,
        )
        span.set_attribute("unwind.counterparties", len(obligation.counterparties))
        span.set_attribute("unwind.reversible_actions", len(reversible_actions))
        span.set_attribute("unwind.unrecoverable", len(unrecoverable))
        span.set_attribute("unwind.exposure_low", exposure.low)
        span.set_attribute("unwind.exposure_high", exposure.high)

        return DraftedObligation(
            obligation=obligation,
            conclusion_id=conclusion.conclusion_id,
            counterparty_map=cmap,
            triaged=triaged,
            unrecoverable=unrecoverable,
            correction_text=correction_text,
        )


def residual_exposure(triaged: list[Triage]) -> ResidualExposure:
    """A range whose two ends are two different, stated beliefs about the world.

    LOW  every compensable reverse path succeeds; only the genuinely one-way
         effects cost anything.
    HIGH no compensation lands; the compensable effects are losses too.

    Both ends are sums of AMOUNTS THAT WERE ACTUALLY RECORDED. Effects with no
    recorded amount are counted and reported, never priced -- inventing a figure
    for them would be the exact failure this project forbids.
    """
    irreversible_total = 0
    compensable_total = 0
    unpriced = 0

    for item in triaged:
        amount = item.effect.amount_minor
        if item.reversibility is Reversibility.IRREVERSIBLE:
            if amount is None:
                unpriced += 1
            else:
                irreversible_total += amount
        elif item.reversibility is Reversibility.COMPENSABLE and amount is not None:
            compensable_total += amount

    assumptions: list[str] = []
    if compensable_total:
        assumptions.append("LOW assumes every compensable reverse path completes successfully.")
        assumptions.append(
            "HIGH assumes no compensation lands and every compensable effect is also a loss."
        )
    else:
        # Stating a compensable assumption where nothing is compensable would be
        # boilerplate, and boilerplate in an assumptions list is how a reader
        # learns to skip the list.
        assumptions.append(
            "No compensable effects: the range has a single value because nothing "
            "here has a reverse path that could succeed or fail."
        )
    assumptions.append(
        "Both ends sum only amounts recorded on the effects themselves; nothing is modelled."
    )
    if unpriced:
        assumptions.append(
            f"{unpriced} unrecoverable effect(s) carry no recorded amount, so this "
            "range is a FLOOR and not a ceiling."
        )

    return ResidualExposure(
        low=irreversible_total,
        high=irreversible_total + compensable_total,
        assumptions=assumptions,
        unpriced_effects=unpriced,
    )
