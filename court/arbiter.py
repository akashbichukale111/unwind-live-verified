"""The neutral arbiter: a THIRD principal, with no stake by construction.

Ruling 1.10, and it is non-negotiable. The arbiter:

    cannot own a commitment          (it holds no seat on the team)
    cannot have authored a premise   (it is not a source)
    cannot be the re-deriver         (it would rule on its own alternative)
    cannot be the assessor           (it would ratify its own materiality call)

Those four are checked by `lib.principals.assert_arbiter_is_third` before a
single plea is read, because an arbiter that shares a principal with a party
turns the whole court into one model talking to itself in different voices --
which is precisely what a Fake-Agent Detector is looking for, and precisely what
this project claims not to be.

WHAT IS DETERMINISTIC AND WHAT IS NOT
-------------------------------------
The TALLY is arithmetic: evidence discounts, exposure ordering, and allocation
of a contested resource are all computed. The model is asked for the RATIONALE
-- the written reasoning a human reads. So an unavailable Vertex costs the court
its prose, not its verdict, and the ruling still names who lost and why.

Above a cost threshold the arbiter does not rule on its own authority at all: it
issues an ADVISORY ruling that becomes a recommendation attached to a signature
request. The system does not get to spend that much on its own say-so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from judgment.model import T2Model
from lib.config import Tier
from lib.principals import assert_arbiter_is_third
from lib.schema import Challenge, Plea, PleaStance, Ruling
from lib.telemetry import agent_decision_span

#: The deciding principal. MUST differ from every owner, the assessor and the
#: re-deriver. Versioned so a ruling can be attributed to a specific behaviour.
ARBITER_PRINCIPAL = "neutral-arbiter@0.4.0"

PURPOSE_RULING = "court_ruling"

#: [ASSUMPTION] Total exposure (minor units) above which a ruling is advisory
#: rather than self-executing. Set at $50,000: large enough that routine repairs
#: settle without a human, small enough that nothing material moves unsigned.
ADVISORY_EXPOSURE_MINOR = 5_000_000


@dataclass
class ArbiterOutcome:
    """A ruling plus everything the ruling had to discard to exist."""

    ruling: Ruling
    #: Recorded, never dropped. A dissent that is discarded is a disagreement
    #: the organisation paid for and then threw away.
    dissent: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    amended: list[str] = field(default_factory=list)
    conceded: list[str] = field(default_factory=list)
    #: Set when the arbiter declined to rule and sent the question up instead.
    escalated: bool = False

    @property
    def advisory(self) -> bool:
        return self.ruling.advisory


@dataclass
class NeutralArbiter:
    """Rules on a repair. Holds no commitment and speaks for no party."""

    arbiter_id: str = ARBITER_PRINCIPAL

    def rule(
        self,
        *,
        notice: Any,
        pleas: list[Plea],
        challenges: list[Challenge],
        owner_ids: list[str],
        model: T2Model,
        now: datetime,
        total_exposure_minor: int = 0,
        converged: bool = True,
        assessor: str | None = None,
        rederiver: str | None = None,
    ) -> ArbiterOutcome:
        """Weigh the pleas and decide. Separation is checked first, always."""
        assert_arbiter_is_third(
            self.arbiter_id,
            owners=owner_ids,
            assessor=assessor,
            rederiver=rederiver,
        )

        with agent_decision_span(self.arbiter_id, Tier.T2) as span:
            weighed = [(p, _weight(p)) for p in pleas]
            contested = _contested_resources(challenges, pleas)

            preserved: list[str] = []
            amended: list[str] = []
            conceded: list[str] = []
            dissent: list[str] = []

            # A contested resource is ALLOCATED, not deadlocked: the highest
            # weighted claim keeps it and the rest are amended. Refusing to
            # choose would leave two commitments both believing they hold the
            # same slot, which is worse than either of them losing it.
            winners = _allocate(weighed, contested)

            for plea, weight in weighed:
                cid = plea.conclusion_id
                lost_allocation = cid in contested and winners.get(contested[cid]) != cid
                if not converged:
                    # Conservative default: treat as material and correct it.
                    conceded.append(cid)
                    dissent.append(
                        f"{plea.member_owner_id} argued {plea.stance.value} for {cid}; "
                        "the protocol did not converge, so the conservative "
                        "default applied rather than this plea."
                    )
                elif lost_allocation:
                    amended.append(cid)
                    dissent.append(
                        f"{plea.member_owner_id} sought {plea.stance.value} for {cid} "
                        f"but lost the allocation of {contested[cid]}."
                    )
                elif plea.stance is PleaStance.SURVIVE_UNCHANGED:
                    preserved.append(cid)
                elif plea.stance is PleaStance.SURVIVE_AMENDED:
                    amended.append(cid)
                elif plea.stance is PleaStance.DISPUTE_RETRACTION:
                    # Disputing the retraction is not the court's question --
                    # the authority gate already settled standing. Record the
                    # disagreement and treat the commitment conservatively.
                    conceded.append(cid)
                    dissent.append(
                        f"{plea.member_owner_id} disputed the retraction itself for "
                        f"{cid}; standing was already settled by the authority "
                        "gate, so the dispute is recorded, not acted on."
                    )
                else:
                    conceded.append(cid)

                if weight < 1.0 and plea.stance is not PleaStance.CONCEDE:
                    dissent.append(
                        f"{plea.member_owner_id}'s plea for {cid} was discounted to "
                        f"{weight} for citing no evidence."
                    )

            advisory = total_exposure_minor >= ADVISORY_EXPOSURE_MINOR
            decision = _decision_line(preserved, amended, conceded, converged)
            rationale = self._rationale(notice, weighed, challenges, decision, model, converged)

            ruling = Ruling(
                arbiter_id=self.arbiter_id,
                decision=decision,
                rationale=rationale,
                decided_at=now,
                advisory=advisory,
                converged=converged,
                conceded_conclusion_ids=conceded,
            )
            span.set_attribute("unwind.ruling_advisory", advisory)
            span.set_attribute("unwind.ruling_converged", converged)
            span.set_attribute("unwind.dissent_count", len(dissent))
            span.set_attribute("unwind.preserved", len(preserved))
            span.set_attribute("unwind.conceded", len(conceded))

            return ArbiterOutcome(
                ruling=ruling,
                dissent=dissent,
                preserved=preserved,
                amended=amended,
                conceded=conceded,
                escalated=advisory,
            )

    def _rationale(
        self,
        notice: Any,
        weighed: list[tuple[Plea, float]],
        challenges: list[Challenge],
        decision: str,
        model: T2Model,
        converged: bool,
    ) -> str:
        prompt = (
            "You are a neutral arbiter in a repair hearing. Write the reasoning "
            "for the decision below in at most four sentences. You did not "
            "choose the decision; explain it.\n"
            f"decision: {decision}\n"
            f"converged: {converged}\n"
            f"pleas: {[(p.member_owner_id, p.stance.value, w) for p, w in weighed]}\n"
            f"challenges: {[(c.challenger_owner_id, c.contested_resource) for c in challenges]}\n"
        )
        reply = model.complete(prompt, purpose=PURPOSE_RULING)
        if reply.available and reply.text.strip():
            return reply.text.strip()
        return (
            f"[no-model rationale] {decision}. Decided on the weighted tally of "
            f"{len(weighed)} plea(s) and {len(challenges)} challenge(s); the "
            f"written reasoning was unavailable ({reply.reason_unavailable or 'model unavailable'}), "
            "but the tally that produced the decision is recorded above."
        )


def _weight(plea: Plea) -> float:
    """Unevidenced pleas are discounted AUTOMATICALLY. Not a reminder -- a rule."""
    return 1.0 if plea.evidence else 0.4


def _contested_resources(challenges: list[Challenge], pleas: list[Plea]) -> dict[str, str]:
    """conclusion_id -> the resource it is contending for.

    A `Challenge` names OWNERS, because that is who is arguing; everything
    downstream allocates over COMMITMENTS, because that is what holds a slot.
    The translation happens here, through the pleas, which are the only place
    both identifiers appear together. Keying this map by owner id instead --
    which it did until a test caught it -- silently disabled allocation
    entirely: every lookup missed, nothing was ever contested, and two
    commitments would both have kept the same capacity.
    """
    owner_to_conclusion = {p.member_owner_id: p.conclusion_id for p in pleas}
    contested: dict[str, str] = {}
    for challenge in challenges:
        if not challenge.contested_resource:
            continue
        for owner_id in (challenge.challenger_owner_id, challenge.target_owner_id):
            conclusion_id = owner_to_conclusion.get(owner_id)
            if conclusion_id is not None:
                contested.setdefault(conclusion_id, challenge.contested_resource)
    return contested


def _allocate(weighed: list[tuple[Plea, float]], contested: dict[str, str]) -> dict[str, str]:
    """resource -> the one conclusion that keeps it.

    Deterministic: highest weighted claimed materiality, then conclusion id, so
    two runs over the same hearing allocate the same way.
    """
    best: dict[str, tuple[float, str]] = {}
    for plea, weight in weighed:
        resource = contested.get(plea.conclusion_id)
        if resource is None:
            continue
        score = (plea.claimed_materiality or 0.0) * weight
        key = (score, plea.conclusion_id)
        if resource not in best or key > best[resource]:
            best[resource] = key
    return {resource: cid for resource, (_, cid) in best.items()}


def _decision_line(
    preserved: list[str], amended: list[str], conceded: list[str], converged: bool
) -> str:
    if not converged:
        return (
            f"NON-CONVERGENT: conservative default applied to {len(conceded)} "
            "commitment(s) -- treated as material and escalated."
        )
    return f"preserved {len(preserved)}, amended {len(amended)}, conceded {len(conceded)}"
