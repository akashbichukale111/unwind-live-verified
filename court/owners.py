"""Commitment owners: partisan by design, and structurally unable to rule.

Each owner holds authority over one commitment and an interest in its survival.
That interest is not a defect to be engineered away -- it is the reason the
court produces anything useful. An owner argues the best case for its
commitment; a different principal decides. Take away the partisanship and you
get a system that agrees with itself.

⚠ OWNERS ARE SINGLE-TURN AGENT TOOLS, NOT SUB-AGENTS, AND THIS IS THE REASON
THIS PROJECT NEEDS ADK 2.

    Delegating to a sub-agent hands over control: the parent cannot run a
    chosen subset in parallel and cannot reclaim the floor to rule. The court
    requires exactly that -- N owners discovered at runtime, run in parallel,
    with the arbiter keeping control. `AgentTool` (agent-as-tool) is what makes
    the parent the one still holding the gavel.

The permission boundary is enforced, not documented:

    MAY   argue, cite evidence, request evidence, propose an amendment
    MAY NOT   adjudicate its own survival -- `adjudicate()` raises, always.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from judgment.model import T2Model
from lib.config import Tier
from lib.principals import PrincipalSeparationError
from lib.schema import Challenge, Plea, PleaStance
from lib.telemetry import agent_decision_span

#: [ASSUMPTION] What an unevidenced plea is worth. Not zero -- an owner may be
#: right and inarticulate -- but it must not outweigh an evidenced one, so it
#: sits below the 0.5 an arbiter needs to prefer it to anything.
UNEVIDENCED_WEIGHT = 0.4

PURPOSE_PLEA = "court_plea"
PURPOSE_CHALLENGE = "court_challenge"


class OwnerCannotAdjudicateError(RuntimeError):
    """An owner was asked to decide the case it is a party to."""


@dataclass
class CommitmentOwner:
    """One party. Speaks for exactly one commitment and never for the court."""

    owner_id: str
    conclusion_id: str
    #: What the commitment currently says, so the owner can argue about it.
    committed_lead_days: int | None = None
    exposure: float = 0.0
    #: Facts the owner may cite. An owner that cites something not in here is
    #: making it up, and the protocol can tell.
    available_evidence: list[str] = field(default_factory=list)

    # -- the thing an owner may never do ------------------------------------

    def adjudicate(self, *_: Any, **__: Any) -> None:
        """Always raises. Present so the prohibition is executable.

        A permission that exists only as a sentence in a design document gets
        violated by the next person who needs a quick result. This one fails
        loudly, and `tests/test_court.py` asserts it does.
        """
        raise OwnerCannotAdjudicateError(
            f"{self.owner_id} was asked to adjudicate {self.conclusion_id}, which "
            "it owns. An owner may argue for its commitment and may not decide "
            "whether it survives -- that is the whole point of a separate arbiter."
        )

    # -- turn 2: the plea ----------------------------------------------------

    def plead(self, brief: Any, model: T2Model) -> Plea:
        """One structured argument. Exactly one, because the protocol is bounded.

        The stance is chosen deterministically from arithmetic the owner can
        see; the model is asked only for the PROSE of the argument. That split
        matters: if the model chose the stance, an unavailable Vertex would mean
        no plea at all, and silence from an owner reads as concession.
        """
        with agent_decision_span(self.owner_id, Tier.T2) as span:
            stance = self._stance(brief)
            evidence = list(self.available_evidence)
            reply = model.complete(self._prompt(brief, stance), purpose=PURPOSE_PLEA)

            if reply.available and reply.text.strip():
                argument = reply.text.strip()
            else:
                # No model: the owner still argues, from arithmetic alone. A
                # party that goes silent because a service is down would lose by
                # default, which is a system failure wearing a ruling's clothes.
                argument = self._fallback_argument(brief, stance, reply.reason_unavailable)

            plea = Plea(
                member_owner_id=self.owner_id,
                conclusion_id=self.conclusion_id,
                argument=argument,
                claimed_materiality=self._claimed_materiality(brief),
                stance=stance,
                evidence=evidence,
            )
            # The discount is applied by the court, not by the party -- see
            # `court.protocol.weigh`. Recorded here only for the span.
            span.set_attribute("unwind.plea_stance", stance.value)
            span.set_attribute("unwind.plea_evidence_count", len(evidence))
            return plea

    # -- turn 3: the challenge ----------------------------------------------

    def challenge(self, other: Plea, *, resource: str | None = None) -> Challenge | None:
        """Challenge a peer only where the two commitments actually conflict.

        Returns None when there is nothing to contest. An owner that challenges
        every peer is noise, and noise is what the turn cap exists to bound.
        """
        if other.member_owner_id == self.owner_id:
            return None
        if resource is None:
            return None
        return Challenge(
            challenger_owner_id=self.owner_id,
            target_owner_id=other.member_owner_id,
            argument=(
                f"{self.conclusion_id} and {other.conclusion_id} both rest on "
                f"{resource}, which cannot satisfy both at the re-derived value. "
                "Allocation is required; preserving both is not available."
            ),
            contested_resource=resource,
        )

    # -- internals -----------------------------------------------------------

    def _stance(self, brief: Any) -> PleaStance:
        """Arithmetic, not rhetoric.

        The owner concedes when the shock exceeds its slack, argues for an
        amendment when it is close, and defends outright when the buffer holds.
        A partisan agent still has to be honest about subtraction -- it is
        arguing to an arbiter that can do the same sum.
        """
        shock = getattr(brief, "shock_days", None)
        slack = getattr(brief, "slack_days", None)
        if shock is None or slack is None:
            # Cannot compute: dispute the retraction rather than concede on an
            # unknown. Conceding on missing information is how a correct
            # commitment gets withdrawn.
            return PleaStance.DISPUTE_RETRACTION
        if shock <= slack:
            return PleaStance.SURVIVE_UNCHANGED
        if shock <= slack + _AMENDMENT_ROOM:
            return PleaStance.SURVIVE_AMENDED
        return PleaStance.CONCEDE

    def _claimed_materiality(self, brief: Any) -> float | None:
        shock = getattr(brief, "shock_days", None)
        slack = getattr(brief, "slack_days", None)
        if shock is None or slack is None or shock <= 0:
            return None
        return max(0.0, min(1.0, (shock - slack) / shock))

    def _prompt(self, brief: Any, stance: PleaStance) -> str:
        return (
            "You speak for one commitment in a repair hearing. Argue its case in "
            "at most three sentences. Do not decide the outcome; you are a party, "
            "not the arbiter.\n"
            f"commitment: {self.conclusion_id}\n"
            f"committed lead days: {self.committed_lead_days}\n"
            f"shock days: {getattr(brief, 'shock_days', None)}\n"
            f"slack days: {getattr(brief, 'slack_days', None)}\n"
            f"your stance: {stance.value}\n"
            f"evidence you may cite: {self.available_evidence}\n"
        )

    def _fallback_argument(self, brief: Any, stance: PleaStance, why: str | None) -> str:
        shock = getattr(brief, "shock_days", None)
        slack = getattr(brief, "slack_days", None)
        return (
            f"[no-model plea] {self.conclusion_id}: shock {shock}d against slack "
            f"{slack}d, stance {stance.value}. Argument drafted without a model "
            f"({why or 'model unavailable'}); the arithmetic stands on its own."
        )


#: [ASSUMPTION] How far past its slack a commitment may be and still be worth
#: amending rather than conceding. Beyond this the amendment would be a new
#: commitment wearing the old one's name.
_AMENDMENT_ROOM = 3


def assert_not_own_judge(owner: CommitmentOwner, arbiter_id: str) -> None:
    """The per-owner half of ruling 1.10, checked at the seat rather than the bench."""
    if owner.owner_id == arbiter_id:
        raise PrincipalSeparationError(
            f"{owner.owner_id} holds both a seat as a party and the arbiter's "
            "gavel for the same repair."
        )
