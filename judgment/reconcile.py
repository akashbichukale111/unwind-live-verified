"""The claim reconciler: are these two differently-worded claims the same claim?

THE HARDEST AND MOST CONSEQUENTIAL JUDGEMENT IN THE SYSTEM, and it is wrong in
two directions with opposite costs:

  UNDER-MERGE  the graph fragments. `supplier_K.lead_time_days` and
               `supplier_K.leadtime` become two premises, a retraction lands on
               one, and half the blast radius is never reached. The failure is
               SILENT -- the cascade reports success over a radius missing the
               commitments that mattered.

  OVER-MERGE   unrelated decisions are invalidated. `supplier_K.lead_time_days`
               is fused with `supplier_L.lead_time_days`, and retracting one
               un-sends commitments built on the other. The failure is LOUD, and
               it reaches customers.

So merges are proposals, not surgery: reversible, logged, and never destructive.
The originals stay exactly where they were, with a link recorded alongside. And
a merge whose margin is thin does not get decided here at all — it routes to the
confidence gate as ASK_HUMAN, because a coin-flip on this question is the one
thing that must not happen automatically.

The deterministic pass runs first and settles the easy cases (identical
canonicals, known aliases) with no model. Only genuinely different wordings
reach T2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from judgment.model import T2Model
from lib.config import Tier
from lib.schema import Claim
from lib.telemetry import agent_decision_span

RECONCILER_PRINCIPAL = "claim-reconciler@0.3.0"
PURPOSE = "claim_reconciliation"

#: Above this, merge. Below `LOW_MARGIN`, do not merge. Between them, ask.
#: [ASSUMPTION] The band is judgement. Its width is the point: a system with a
#: single threshold has no way to say "I am not sure", and this question needs
#: one.
MERGE_THRESHOLD = 0.90
LOW_MARGIN_THRESHOLD = 0.60


class MergeOutcome(str, Enum):
    MERGED = "merged"
    DISTINCT = "distinct"
    #: In the uncertainty band. Routed to a human, not guessed.
    ASK_HUMAN = "ask_human"
    #: The model was unavailable. Nothing was merged, nothing was ruled out.
    UNRESOLVED = "unresolved"


@dataclass
class MergeProposal:
    """A proposed identity between two claims. REVERSIBLE AND LOGGED."""

    left_claim_id: str
    right_claim_id: str
    outcome: MergeOutcome
    similarity: float
    reason: str
    decided_by: str = RECONCILER_PRINCIPAL
    decided_at: datetime | None = None
    #: Set when the deterministic pass settled it without a model.
    settled_deterministically: bool = False

    def reverse(self, why: str, at: datetime) -> MergeProposal:
        """Undo a merge. The originals were never destroyed, so this is a record.

        Returning a new proposal rather than mutating means the history of a
        reconciliation is a list of events, not a field that got overwritten.
        """
        return MergeProposal(
            left_claim_id=self.left_claim_id,
            right_claim_id=self.right_claim_id,
            outcome=MergeOutcome.DISTINCT,
            similarity=self.similarity,
            reason=f"Merge reversed: {why}",
            decided_at=at,
        )


@dataclass
class ReconciliationLog:
    """Every proposal, in order. A merge nobody can audit is surgery."""

    entries: list[MergeProposal] = field(default_factory=list)

    def record(self, proposal: MergeProposal) -> MergeProposal:
        self.entries.append(proposal)
        return proposal

    def merged_pairs(self) -> list[tuple[str, str]]:
        """Net merges, after reversals. Order-sensitive, replayed not cached."""
        live: dict[tuple[str, str], bool] = {}
        for entry in self.entries:
            key = tuple(sorted((entry.left_claim_id, entry.right_claim_id)))
            live[key] = entry.outcome is MergeOutcome.MERGED
        return sorted(pair for pair, merged in live.items() if merged)


#: Alias families the deterministic pass knows. Extending this is cheap and is
#: strictly better than sending an easy case to a model.
KNOWN_ALIASES: tuple[frozenset[str], ...] = (
    frozenset({"lead_time_days", "leadtime_days", "lead_time", "leadtime"}),
    frozenset({"transit_days", "transit_time_days", "in_transit_days"}),
    frozenset({"rate_pct", "duty_rate_pct", "tariff_rate_pct"}),
    frozenset({"moq_units", "minimum_order_units", "min_order_units"}),
)


def _normalise(canonical: str) -> tuple[str, str]:
    """Split into (subject, attribute) with punctuation and case flattened."""
    subject, _, attribute = canonical.rpartition(".")
    return (
        re.sub(r"[^a-z0-9]", "", subject.lower()),
        re.sub(r"[^a-z0-9_]", "", attribute.lower()),
    )


def deterministic_similarity(left: Claim, right: Claim) -> tuple[float, str] | None:
    """Settle the easy cases with no model. Returns None when it cannot.

    Two rules only, both exact:
      - identical canonical  -> the same claim
      - different SUBJECT    -> never the same claim, whatever the attribute

    The second is the one that prevents the expensive failure. `supplier_K` and
    `supplier_L` are different companies; no amount of attribute similarity makes
    a claim about one a claim about the other, and a model asked to compare
    "supplier_K lead time" with "supplier_L lead time" will find them very
    similar indeed.
    """
    left_subject, left_attr = _normalise(left.canonical)
    right_subject, right_attr = _normalise(right.canonical)

    if left.canonical == right.canonical:
        return 1.0, "Identical canonical names."

    if left_subject != right_subject:
        return (
            0.0,
            f"Different subjects ({left_subject!r} vs {right_subject!r}). A claim "
            "about one entity is never a claim about another, however similar the "
            "attribute reads.",
        )

    for family in KNOWN_ALIASES:
        if left_attr in family and right_attr in family:
            return (
                0.97,
                f"Same subject {left_subject!r}, and {left_attr!r}/{right_attr!r} "
                "are known aliases for one attribute.",
            )

    if left.type is not right.type:
        return (
            0.05,
            f"Same subject but different claim types ({left.type.value} vs "
            f"{right.type.value}); these are not the same assertion.",
        )
    return None


def reconcile(
    left: Claim,
    right: Claim,
    model: T2Model,
    now: datetime,
    log: ReconciliationLog | None = None,
) -> MergeProposal:
    """Decide whether two claims are the same claim. Deterministic pass first."""
    log = log if log is not None else ReconciliationLog()

    with agent_decision_span(RECONCILER_PRINCIPAL, Tier.T2) as span:
        settled = deterministic_similarity(left, right)
        if settled is not None:
            similarity, reason = settled
            outcome = (
                MergeOutcome.MERGED if similarity >= MERGE_THRESHOLD else MergeOutcome.DISTINCT
            )
            span.set_attribute("unwind.reconciliation", outcome.value)
            span.set_attribute("unwind.settled_deterministically", True)
            return log.record(
                MergeProposal(
                    left_claim_id=left.claim_id,
                    right_claim_id=right.claim_id,
                    outcome=outcome,
                    similarity=similarity,
                    reason=reason,
                    decided_at=now,
                    settled_deterministically=True,
                )
            )

        prompt = (
            "Are these two premises assertions about the same underlying fact?\n"
            f"A: {left.canonical} = {left.value!r} ({left.type.value}, from {left.source_id})\n"
            f"B: {right.canonical} = {right.value!r} ({right.type.value}, from {right.source_id})\n"
            'Answer as JSON: {"same_fact": <true|false>, "confidence": <0..1>, '
            '"reasoning": "<one sentence>"}'
        )
        reply = model.complete(prompt, purpose=PURPOSE)

        if not reply.available:
            span.set_attribute("unwind.reconciliation", "unresolved")
            return log.record(
                MergeProposal(
                    left_claim_id=left.claim_id,
                    right_claim_id=right.claim_id,
                    outcome=MergeOutcome.UNRESOLVED,
                    similarity=0.0,
                    reason=(
                        f"Reconciliation could not run: {reply.reason_unavailable}. "
                        "Nothing merged and nothing ruled out -- the graph is left "
                        "exactly as it was."
                    ),
                    decided_at=now,
                )
            )

        payload = reply.as_json() or {}
        same = bool(payload.get("same_fact", False))
        confidence = float(payload.get("confidence", 0.0))
        reasoning = str(payload.get("reasoning", ""))[:300]
        similarity = confidence if same else 1.0 - confidence

        if similarity >= MERGE_THRESHOLD:
            outcome, reason = MergeOutcome.MERGED, f"Judged the same fact: {reasoning}"
        elif similarity <= LOW_MARGIN_THRESHOLD:
            outcome, reason = (
                MergeOutcome.DISTINCT,
                f"Judged distinct: {reasoning}",
            )
        else:
            outcome = MergeOutcome.ASK_HUMAN
            reason = (
                f"Similarity {similarity:.2f} falls between {LOW_MARGIN_THRESHOLD:.2f} "
                f"and {MERGE_THRESHOLD:.2f}. Merging the wrong pair invalidates "
                "unrelated commitments; leaving a real pair split silently hides "
                "half a blast radius. Neither is worth a coin flip. {reasoning}"
            ).format(reasoning=reasoning)

        span.set_attribute("unwind.reconciliation", outcome.value)
        span.set_attribute("unwind.similarity", similarity)
        return log.record(
            MergeProposal(
                left_claim_id=left.claim_id,
                right_claim_id=right.claim_id,
                outcome=outcome,
                similarity=round(similarity, 4),
                reason=reason,
                decided_at=now,
            )
        )
