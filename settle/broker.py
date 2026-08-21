"""The approval broker: routes an obligation to the human who must sign it.

The permission boundary is the entire point, and it is enforced rather than
described:

    MAY      request a signature, with exactly the context needed to decide
    MAY NOT  approve. `approve()` does not exist on this object. The only way
             an obligation becomes SIGNED is `record_human_signature`, which
             demands a named human and refuses any principal that looks like an
             agent in this system.

An unapproved obligation stays visibly open. It does not expire, it does not
age out, and there is no timeout that quietly discharges it -- because the
failure mode of a correction system is not "too many open items", it is "an
item that closed itself and nobody told the customer".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from lib.config import Tier
from lib.schema import Obligation, ObligationStatus
from lib.telemetry import agent_decision_span

BROKER_PRINCIPAL = "approval-broker@0.4.0"

#: Principals the broker will never accept as a signatory. An obligation signed
#: by the system that raised it is not an approval, it is a loop.
_AGENT_MARKERS = ("@", "agent::", "principal_", "scripted", "arbiter", "owner")


class BrokerCannotApproveError(RuntimeError):
    """The broker was asked to approve rather than to route."""


class NotAHumanError(RuntimeError):
    """Something that is not a human tried to sign."""


@dataclass(frozen=True)
class SignatureRequest:
    """What a human is actually shown. Context, not a dump."""

    obligation_id: str
    approver: str
    conclusion_id: str
    counterparties: list[str]
    reversible_count: int
    unrecoverable_count: int
    exposure_low: int
    exposure_high: int
    currency: str
    requested_at: datetime
    why: str

    def render(self) -> str:
        return (
            f"SIGNATURE REQUESTED  {self.obligation_id}\n"
            f"  to        : {self.approver}\n"
            f"  commitment: {self.conclusion_id}\n"
            f"  affects   : {len(self.counterparties)} counterparty(ies)\n"
            f"  reversible: {self.reversible_count}   unrecoverable: {self.unrecoverable_count}\n"
            f"  exposure  : {self.currency} {self.exposure_low / 100:,.2f}"
            f" -- {self.currency} {self.exposure_high / 100:,.2f}\n"
            f"  why       : {self.why}"
        )


@dataclass
class ApprovalBroker:
    """Routes. Never decides."""

    broker_id: str = BROKER_PRINCIPAL
    #: Every request ever made, so an open obligation is discoverable rather
    #: than merely un-closed.
    outstanding: dict[str, SignatureRequest] = field(default_factory=dict)

    def approve(self, *_: object, **__: object) -> None:
        """Always raises. Present so the prohibition is executable, not implied."""
        raise BrokerCannotApproveError(
            "the approval broker may request a signature and may not supply one. "
            "An obligation approved by the system that raised it has not been "
            "approved by anybody."
        )

    def request_signature(
        self,
        *,
        obligation: Obligation,
        unrecoverable_count: int,
        now: datetime,
        why: str,
    ) -> SignatureRequest:
        """Route the obligation and move it to AWAITING_SIGNATURE."""
        with agent_decision_span(self.broker_id, Tier.T1) as span:
            if not obligation.approver:
                raise NotAHumanError(
                    f"obligation {obligation.obligation_id} has no approver; there is "
                    "nobody to route it to."
                )
            request = SignatureRequest(
                obligation_id=obligation.obligation_id,
                approver=obligation.approver,
                conclusion_id=obligation.conclusion_id,
                counterparties=list(obligation.counterparties),
                reversible_count=len(obligation.reversible_actions),
                unrecoverable_count=unrecoverable_count,
                exposure_low=obligation.residual_exposure.low,
                exposure_high=obligation.residual_exposure.high,
                currency=obligation.residual_exposure.currency,
                requested_at=now,
                why=why,
            )
            obligation.status = ObligationStatus.AWAITING_SIGNATURE
            self.outstanding[obligation.obligation_id] = request
            span.set_attribute("unwind.obligation_id", obligation.obligation_id)
            span.set_attribute("unwind.approver", obligation.approver)
            return request

    def record_human_signature(
        self, obligation: Obligation, *, human: str, at: datetime
    ) -> Obligation:
        """The only path to SIGNED, and it requires a human who is not us."""
        if not human.startswith("human::"):
            raise NotAHumanError(
                f"{human!r} is not a human signatory. Only a 'human::' principal may "
                "sign an obligation; anything else is the system approving itself."
            )
        lowered = human.lower()
        if any(marker in lowered.removeprefix("human::") for marker in _AGENT_MARKERS):
            raise NotAHumanError(f"{human!r} carries an agent marker and may not sign.")
        obligation.status = ObligationStatus.SIGNED
        self.outstanding.pop(obligation.obligation_id, None)
        _ = at
        return obligation

    def open_obligations(self) -> list[SignatureRequest]:
        """Everything still waiting. Never filtered by age."""
        return sorted(self.outstanding.values(), key=lambda r: r.obligation_id)
