"""Cascade -> court -> settlement, composed in the one order that is safe.

    map the radius (T0)  ->  score it (T1)  ->  convene a court on what survives
    (T2)  ->  draft obligations  ->  route them to a human

MERGING TWO RADII IS PART OF THE JOB, NOT AN EDGE CASE. Premises fail in
clusters: a supplier slips and the same week a regulator moves a deadline. Two
cascades over an overlapping graph will reach many of the same commitments, and
raising two obligations against one commitment means apologising to the same
customer twice for the same thing. So radii are merged on `conclusion_id`
BEFORE any obligation exists, and the count of duplicates suppressed is
reported rather than assumed to be zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from court.arbiter import NeutralArbiter
from court.owners import CommitmentOwner
from court.protocol import Brief, Notice, Proceedings, run_repair
from court.team import RepairTeam, form_team
from judgment.model import T2Model
from lib.config import Tier
from lib.schema import Conclusion
from lib.telemetry import agent_decision_span
from settle.broker import ApprovalBroker, SignatureRequest
from settle.obligation import DraftedObligation, build_obligation

PURPOSE_DRAFT = "correction_draft"


@dataclass
class Settlement:
    """Everything one settlement produced, including what it declined to do."""

    claim_ids: list[str]
    team: RepairTeam
    proceedings: Proceedings | None
    obligations: list[DraftedObligation] = field(default_factory=list)
    requests: list[SignatureRequest] = field(default_factory=list)
    #: Commitments reached by more than one radius, deduplicated. Counted so
    #: "no duplicate obligations" is a measurement rather than a hope.
    duplicates_suppressed: int = 0
    radius_size: int = 0

    @property
    def obligation_count(self) -> int:
        return len(self.obligations)

    @property
    def dissent(self) -> list[str]:
        return self.proceedings.dissent if self.proceedings else []


def merge_alerts(results: list[Any]) -> tuple[list[Any], int]:
    """Union the alert cells of several cascades, deduplicated by commitment.

    Keeps the FIRST verdict seen for a commitment, in the order the results were
    given, so a merge is reproducible. Returns the merged list and the number of
    duplicates suppressed.
    """
    seen: dict[str, Any] = {}
    duplicates = 0
    for result in results:
        for verdict in result.alerts():
            if verdict.conclusion_id in seen:
                duplicates += 1
                continue
            seen[verdict.conclusion_id] = verdict
    return list(seen.values()), duplicates


@dataclass
class _MergedResult:
    """A radius assembled from several cascades, shaped like a single one.

    `form_team` and the rest of the court take a result and call `alerts()`;
    giving them a merged object means the multi-premise path is the same code
    path as the single-premise one, rather than a parallel implementation that
    could drift.
    """

    claim_id: str
    radius: dict[str, Any]
    _alerts: list[Any]

    def alerts(self) -> list[Any]:
        return self._alerts


def settle(
    *,
    results: list[Any],
    store: Any,
    model: T2Model,
    now: datetime,
    repair_id: str,
    broker: ApprovalBroker | None = None,
    arbiter: NeutralArbiter | None = None,
    contested_resources: dict[str, str] | None = None,
    assessor: str | None = None,
    rederiver: str | None = None,
) -> Settlement:
    """Convene a court over one or more cascades and settle what it rules on."""
    broker = broker or ApprovalBroker()
    contested_resources = contested_resources or {}

    with agent_decision_span("settlement", Tier.T2) as span:
        merged_alerts, duplicates = merge_alerts(results)
        radius: dict[str, Any] = {}
        for result in results:
            radius.update(result.radius)

        merged = _MergedResult(
            claim_id=results[0].claim_id if results else "",
            radius=radius,
            _alerts=merged_alerts,
        )

        def owner_lookup(conclusion_id: str) -> str | None:
            conclusion = store.get_conclusion(conclusion_id)
            return conclusion.owner_principal if conclusion else None

        team = form_team(merged, repair_id, owner_lookup)
        settlement = Settlement(
            claim_ids=[r.claim_id for r in results],
            team=team,
            proceedings=None,
            duplicates_suppressed=duplicates,
            radius_size=len(radius),
        )

        if team.size == 0:
            # Nothing survived to argue about. That is a real outcome, not a
            # failure: three of the four regimes settle without a hearing.
            span.set_attribute("unwind.team_size", 0)
            return settlement

        owners: list[CommitmentOwner] = []
        briefs: dict[str, Brief] = {}
        for member in team.members:
            conclusion = store.get_conclusion(member.conclusion_id)
            if conclusion is None:
                continue
            verdict = radius.get(member.conclusion_id)
            owners.append(
                CommitmentOwner(
                    owner_id=member.owner_id,
                    conclusion_id=member.conclusion_id,
                    committed_lead_days=conclusion.committed_lead_days,
                    exposure=member.exposure,
                    available_evidence=_evidence_for(conclusion),
                )
            )
            briefs[member.conclusion_id] = Brief(
                conclusion_id=member.conclusion_id,
                owner_id=member.owner_id,
                shock_days=getattr(verdict, "shock_days", None),
                slack_days=getattr(verdict, "slack_days", None),
                rederived_lead_days=None,
                contested_resource=contested_resources.get(member.conclusion_id),
            )

        notice = Notice(
            claim_id=merged.claim_id,
            old_value=None,
            new_value=None,
            reason="premise retracted; commitments resting on it must be re-argued",
            briefs=briefs,
        )

        proceedings = run_repair(
            notice=notice,
            team=team,
            owners=owners,
            model=model,
            now=now,
            arbiter=arbiter,
            total_exposure_minor=_total_exposure_minor(store, team),
            assessor=assessor,
            rederiver=rederiver,
        )
        settlement.proceedings = proceedings

        # An obligation is raised for every commitment the court did NOT
        # preserve. Preserved commitments need no correction -- that is what
        # winning the argument means.
        outcome = proceedings.outcome
        to_correct = list(outcome.conceded) + list(outcome.amended) if outcome else []

        for conclusion_id in to_correct:
            conclusion = store.get_conclusion(conclusion_id)
            if conclusion is None:
                continue
            drafted = build_obligation(
                conclusion=conclusion,
                obligation_id=f"obl_{repair_id}_{conclusion_id}",
                old_summary=_old_summary(conclusion),
                new_summary=_new_summary(conclusion, radius.get(conclusion_id)),
                correction_text=_draft_correction(conclusion, radius.get(conclusion_id), model),
                ruling_id=proceedings.repair.repair_id,
            )
            settlement.obligations.append(drafted)
            settlement.requests.append(
                broker.request_signature(
                    obligation=drafted.obligation,
                    unrecoverable_count=len(drafted.unrecoverable),
                    now=now,
                    why=(
                        f"court ruled: {outcome.ruling.decision}"
                        if outcome
                        else "settlement without a ruling"
                    ),
                )
            )

        # The team's authority ends here. Anything that still needs doing is an
        # obligation with a named human on it, not a standing committee.
        team.dissolve()

        span.set_attribute("unwind.team_size", len(team.owner_ids))
        span.set_attribute("unwind.obligations", len(settlement.obligations))
        span.set_attribute("unwind.duplicates_suppressed", duplicates)
        return settlement


def _evidence_for(conclusion: Conclusion) -> list[str]:
    """What this owner may legitimately cite. Facts on the record, not claims."""
    evidence: list[str] = []
    if conclusion.committed_lead_days is not None:
        evidence.append(f"committed_lead_days={conclusion.committed_lead_days}")
    if conclusion.closes_at is not None:
        evidence.append(f"closes_at={conclusion.closes_at.isoformat()}")
    for effect in conclusion.external_effects:
        evidence.append(f"effect:{effect.connector}.{effect.op}={effect.ref}")
    return evidence


def _total_exposure_minor(store: Any, team: RepairTeam) -> int:
    total = 0
    for member in team.members:
        conclusion = store.get_conclusion(member.conclusion_id)
        if conclusion is None:
            continue
        for effect in conclusion.external_effects:
            total += effect.amount_minor or 0
    return total


def _old_summary(conclusion: Conclusion) -> str:
    return (
        f"{conclusion.kind.value} {conclusion.conclusion_id}: "
        f"{conclusion.committed_lead_days} day lead time, decided "
        f"{conclusion.decided_at.date().isoformat()}"
    )


def _new_summary(conclusion: Conclusion, verdict: Any) -> str:
    shock = getattr(verdict, "shock_days", None)
    if shock is None:
        return (
            f"the premise under {conclusion.conclusion_id} has been retracted; the "
            "commitment is under review"
        )
    revised = (conclusion.committed_lead_days or 0) + shock
    return (
        f"the lead time this rested on moved by {shock} day(s); the commitment now "
        f"implies roughly {revised} days"
    )


def _draft_correction(conclusion: Conclusion, verdict: Any, model: T2Model) -> str:
    """The prose a counterparty would actually read.

    Model-drafted where a model exists, deterministic where it does not. The
    fallback is not a placeholder -- it is a correction a human could send as
    written, because "Vertex was down" is not a reason a customer should hear
    about their delivery late.
    """
    shock = getattr(verdict, "shock_days", None)
    prompt = (
        "Draft a short correction notice to a counterparty. State plainly what "
        "changed, what it means for them, and that a person is reviewing it. Do "
        "not apologise more than once. Do not invent numbers.\n"
        f"commitment: {conclusion.conclusion_id} ({conclusion.kind.value})\n"
        f"originally committed lead days: {conclusion.committed_lead_days}\n"
        f"movement in days: {shock}\n"
    )
    reply = model.complete(prompt, purpose=PURPOSE_DRAFT)
    if reply.available and reply.text.strip():
        return reply.text.strip()

    movement = f"by {shock} day(s)" if shock is not None else "in a way still being assessed"
    return (
        f"We previously committed to {conclusion.kind.value} "
        f"{conclusion.conclusion_id} on a lead time of "
        f"{conclusion.committed_lead_days} days.\n"
        f"The supplier information that commitment rested on has since changed "
        f"{movement}.\n"
        "We are correcting the commitment and a named person is reviewing what it "
        "means for you before anything further is sent.\n"
        "[drafted without a model; the facts above are read from the record]"
    )
