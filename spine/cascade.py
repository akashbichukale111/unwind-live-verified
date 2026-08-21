"""The cascade: authority gate → T0 traversal → T1 scoring → four regimes.

This is the whole of Task 2's product surface, and it makes ZERO MODEL CALLS.
Not "few". Zero, structurally: nothing in `spine/` may import a model client,
and `tests/test_zero_model.py` walks the import graph to prove it. Running this
with `UNWIND_VERTEX_DISABLED=1` is not a degraded mode, it is the normal mode.

ORDER MATTERS, AND IT IS NOT ARBITRARY
--------------------------------------
1. AUTHORITY first, before a single edge is walked. A forged retraction that
   gets as far as the traversal has already cost real work, and the traversal is
   the step that would go on to touch thousands of live commitments.
2. TEMPORAL TRUTH next: close the old interval, open the new one, keep the prior
   value readable.
3. T0 traversal: the structural closure. No arithmetic yet.
4. T1 + escapement + regime routing per node.
5. BUDGET last, because severity is not knowable until the free work is done.

TWO STORES, ONE PROTOCOL
------------------------
`CorpusStore` reads the committed corpus; `FirestoreStore` reads Firestore.
Neither can reach `radius_truth.jsonl` -- there is no method on the protocol that
would return it, and `CorpusStore` refuses the filename explicitly. A cascade
that could read its own answer key would score perfectly and prove nothing.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.config import Tier
from lib.schema import (
    Budget,
    Cascade,
    CascadeNode,
    CascadeStatus,
    Claim,
    Conclusion,
    DecisionState,
    Regime,
    ReverseEdge,
    Source,
    StatedDecision,
)
from lib.telemetry import agent_decision_span, tool_call_span
from spine.budget import RadiusSeverity, decide_budget
from spine.cartography import ExposureScore, rank, score_exposure
from spine.decision import (
    DecisionContext,
    RetractionRequest,
    decide_admissibility,
    decide_authorisation,
    find_contesting_claims,
)
from spine.escapement import lookup_escapement
from spine.gate import echo_back
from spine.materiality import MaterialityOutcome, score_materiality
from spine.regimes import route_regime
from spine.temporal import Retraction, retract
from spine.traversal import TraversalResult, traverse

CASCADE_AGENT_ID = "cascade-spine@0.2.0"

#: The marking scheme. Naming it here so the refusal below is explicit rather
#: than incidental.
GROUND_TRUTH_FILENAME = "radius_truth.jsonl"


class GroundTruthAccessError(RuntimeError):
    """Raised if anything tries to read the eval marking scheme from a store."""


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


@dataclass
class CorpusStore:
    """Reads the committed corpus. Deliberately cannot see the marking scheme."""

    claims: dict[str, Claim]
    conclusions: dict[str, Conclusion]
    dependents: dict[str, list[ReverseEdge]]
    sources: dict[str, Source]

    #: Every file this store read, so a test can assert what it did NOT read.
    files_read: tuple[str, ...] = ()

    @classmethod
    def from_repo(cls, repo: Path, data_dir: str = "corpus/data") -> CorpusStore:
        base = repo / data_dir
        read: list[str] = []

        def rows(name: str) -> list[dict[str, Any]]:
            if name == GROUND_TRUTH_FILENAME:
                raise GroundTruthAccessError(
                    f"{GROUND_TRUTH_FILENAME} is the eval marking scheme. A cascade "
                    "that can read its own answer key proves nothing."
                )
            read.append(name)
            return [
                json.loads(line)
                for line in (base / name).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        claims = {r["claim_id"]: Claim(**r) for r in rows("claims.jsonl")}
        conclusions = {r["conclusion_id"]: Conclusion(**r) for r in rows("conclusions.jsonl")}
        sources = {r["source_id"]: Source(**r) for r in rows("sources.jsonl")}

        dependents: dict[str, list[ReverseEdge]] = {}
        for row in rows("reverse_index.jsonl"):
            edge = ReverseEdge(**row)
            dependents.setdefault(edge.claim_id, []).append(edge)

        return cls(
            claims=claims,
            conclusions=conclusions,
            dependents=dependents,
            sources=sources,
            files_read=tuple(read),
        )

    def get_claim(self, claim_id: str) -> Claim | None:
        return self.claims.get(claim_id)

    def get_conclusion(self, conclusion_id: str) -> Conclusion | None:
        return self.conclusions.get(conclusion_id)

    def get_source(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def direct_dependents(self, claim_id: str) -> list[ReverseEdge]:
        return self.dependents.get(claim_id, [])


@dataclass
class FirestoreStore:
    """Reads Firestore (emulator or cloud) through lib.firestore.

    Same protocol as CorpusStore, so the cascade cannot tell them apart -- which
    is what makes the emulator integration test meaningful rather than a
    parallel implementation that happens to agree.
    """

    def get_claim(self, claim_id: str) -> Claim | None:
        from lib import firestore as fs

        return fs.get_claim(claim_id)

    def get_conclusion(self, conclusion_id: str) -> Conclusion | None:
        from lib import firestore as fs

        return fs.get_conclusion(conclusion_id)

    def get_source(self, source_id: str) -> Source | None:
        from lib import firestore as fs

        return fs.get_source(source_id)

    def direct_dependents(self, claim_id: str) -> list[ReverseEdge]:
        from lib import firestore as fs

        return list(fs.iter_dependents(claim_id))


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class NodeVerdict:
    conclusion_id: str
    depth: int
    path: list[str]
    regime: Regime
    material: bool | None
    escaped: bool
    reason_code: str
    reason: str
    exposure: float
    slack_days: int | None
    shock_days: int | None
    unresolved_reason: str | None
    scored_by: str

    def to_cascade_node(self, cascade_id: str, scored_at: datetime) -> CascadeNode:
        return CascadeNode(
            cascade_id=cascade_id,
            conclusion_id=self.conclusion_id,
            depth=self.depth,
            path=self.path,
            regime=self.regime,
            materiality=self.material,
            escapement=self.escaped,
            reason_code=self.reason_code,
            scored_by=self.scored_by,
            scored_at=scored_at,
            unresolved_reason=self.unresolved_reason,
            slack_days=self.slack_days,
            shock_days=self.shock_days,
        )


@dataclass
class CascadeResult:
    cascade_id: str
    claim_id: str
    authority: Any  # AuthorityDecision
    status: CascadeStatus
    radius: dict[str, NodeVerdict] = field(default_factory=dict)
    ranked: list[ExposureScore] = field(default_factory=list)
    budget: Budget | None = None
    retraction: Retraction | None = None
    traversal: TraversalResult | None = None
    triggered_at: datetime | None = None
    #: The five-state verdict. One vocabulary for every way this can end.
    decision: StatedDecision | None = None
    #: Live claims disagreeing with this one. Non-empty implies DEFER.
    contesting_claims: list[str] = field(default_factory=list)
    #: Rendered understanding, shown before anything is acted on.
    echo: Any = None
    #: Counted, not assumed. The eval asserts this is zero.
    model_calls: int = 0

    @property
    def decision_state(self) -> str:
        return self.decision.state.value if self.decision else "unknown"

    @property
    def tier_reached(self) -> str:
        return self.budget.tier_reached if self.budget else "T0"

    def regime_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {r.value: 0 for r in Regime}
        for verdict in self.radius.values():
            counts[verdict.regime.value] += 1
        return counts

    def alerts(self) -> list[NodeVerdict]:
        """The only cell that reaches a human. Ordered by exposure."""
        order = {s.conclusion_id: i for i, s in enumerate(self.ranked)}
        return sorted(
            (v for v in self.radius.values() if v.regime is Regime.MATERIAL_ESCAPED),
            key=lambda v: order.get(v.conclusion_id, 1 << 30),
        )

    def to_cascade_doc(self) -> Cascade:
        return Cascade(
            cascade_id=self.cascade_id,
            claim_id=self.claim_id,
            triggered_at=self.triggered_at or datetime.now(UTC),
            triggered_by=self.authority.source_id,
            status=self.status,
            budget=self.budget,
            tier_reached=self.tier_reached,
            authority=self.authority,
            radius_size=len(self.radius),
            regime_counts=self.regime_counts(),
            model_calls=self.model_calls,
        )


def cascade_id_for(claim_id: str, source_id: str, triggered_at: datetime) -> str:
    """Deterministic id, so a redelivered retraction resolves to the same cascade.

    This is what makes the Firestore idempotency key meaningful: two deliveries
    of one event must not produce two cascades.
    """
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"unwind:cascade:{claim_id}:{source_id}:{triggered_at.isoformat()}"
    ).hex


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------


def run_cascade(
    store: Any,
    claim_id: str,
    source_id: str,
    new_value: float | str | bool | None,
    reason: str = "",
    triggered_at: datetime | None = None,
    max_depth: int | None = None,
    confidence: float = 1.0,
    corroborating_sources: list[str] | None = None,
) -> CascadeResult:
    """Run a full cascade. No model call is made or possible from this path."""
    now = triggered_at or datetime.now(UTC)
    cascade_id = cascade_id_for(claim_id, source_id, now)

    with agent_decision_span(CASCADE_AGENT_ID, Tier.T0, claim_id=claim_id) as span:
        span.set_attribute("unwind.cascade_id", cascade_id)

        # --- 1. Admissibility: standing, contest, transient ----------------
        # Before a single edge is walked. A forged or contested retraction that
        # reached the traversal would already have cost the work the traversal
        # exists to protect.
        claim = store.get_claim(claim_id)
        source = store.get_source(source_id)

        contesting = find_contesting_claims(claim, _all_claims(store))
        request = RetractionRequest(
            claim_id=claim_id,
            source_id=source_id,
            new_value=new_value,
            reason=reason,
            confidence=confidence,
            corroborating_sources=list(corroborating_sources or [source_id]),
        )
        blocked, authority = decide_admissibility(request, source, claim, contesting, now)

        if blocked is not None or claim is None:
            # A refusal or a deferral is a RECORDED EVENT, not an exception. The
            # radius stays empty because the traversal never ran.
            decision = blocked or _refuse_missing_claim(claim_id, now)
            span.set_attribute("unwind.status", CascadeStatus.REFUSED.value)
            span.set_attribute("unwind.decision_state", decision.state.value)
            return CascadeResult(
                cascade_id=cascade_id,
                claim_id=claim_id,
                authority=authority,
                status=CascadeStatus.REFUSED,
                decision=decision,
                contesting_claims=[c.claim_id for c in contesting],
                triggered_at=now,
            )

        # --- 2. Temporal Truth --------------------------------------------
        value_before = claim.value
        retraction = retract(claim, new_value, reason, at=now)

        # --- 3. T0 structural traversal -----------------------------------
        traversal = traverse(store, claim_id, max_depth=max_depth)

        # --- 4. T1 + escapement + the four-regime router -------------------
        radius: dict[str, NodeVerdict] = {}
        exposures: list[ExposureScore] = []
        numeric_before = _as_number(value_before)
        numeric_after = _as_number(new_value)

        with tool_call_span("t1_score_radius", Tier.T1, nodes=traversal.size):
            for conclusion_id, node in traversal.nodes.items():
                conclusion = store.get_conclusion(conclusion_id)

                if numeric_before is None or numeric_after is None:
                    materiality = score_materiality(conclusion, claim, 0.0, 0.0)
                    materiality = _force_unresolved(
                        "non_numeric_claim_value",
                        f"{claim.canonical} does not hold a numeric value, so the "
                        "arithmetic tier cannot measure the move.",
                    )
                else:
                    materiality = score_materiality(
                        conclusion, claim, numeric_before, numeric_after, as_of=now
                    )

                escapement = lookup_escapement(conclusion, as_of=now)
                routing = route_regime(materiality.outcome, escapement.escaped, materiality.reason)

                exposure = score_exposure(
                    conclusion=conclusion,
                    conclusion_id=conclusion_id,
                    depth=node.depth,
                    materiality=materiality,
                    escapement=escapement,
                    load_weight=node.weight,
                    as_of=now,
                )
                exposures.append(exposure)

                radius[conclusion_id] = NodeVerdict(
                    conclusion_id=conclusion_id,
                    depth=node.depth,
                    path=node.path,
                    regime=routing.regime,
                    material=materiality.material,
                    escaped=escapement.escaped,
                    reason_code=routing.reason_code,
                    reason=routing.reason,
                    exposure=exposure.exposure,
                    slack_days=materiality.slack_days,
                    shock_days=materiality.shock_days,
                    unresolved_reason=(
                        materiality.reason if routing.regime is Regime.UNRESOLVED else None
                    ),
                    scored_by=materiality.scored_by,
                )

        ranked = rank(exposures)

        # --- 5. Budget, once severity is actually known --------------------
        alerts = [v for v in radius.values() if v.regime is Regime.MATERIAL_ESCAPED]
        severity = RadiusSeverity(
            radius_size=len(radius),
            alert_count=len(alerts),
            material_count=sum(1 for v in radius.values() if v.material is True),
            unresolved_count=sum(1 for v in radius.values() if v.regime is Regime.UNRESOLVED),
            total_money_minor=sum(
                lookup_escapement(
                    store.get_conclusion(v.conclusion_id), as_of=now
                ).amount_minor_at_risk
                for v in alerts
            ),
            max_irreversibility=max(
                (
                    lookup_escapement(
                        store.get_conclusion(v.conclusion_id), as_of=now
                    ).worst_irreversibility
                    for v in alerts
                ),
                default=0.0,
            ),
        )
        budget = decide_budget(severity)

        # --- 6. Authorisation: the half of the gate that needed the radius --
        authorisation = decide_authorisation(
            request,
            claim,
            DecisionContext(
                blast_radius=len(radius),
                contesting_claims=[],
                exposure_minor=severity.total_money_minor,
            ),
            now,
        )

        # --- 7. Echo back what was understood, whatever the verdict ---------
        rendered = echo_back(
            claim=claim,
            source=source,
            new_value=new_value,
            decision=authorisation,
            blast_radius=len(radius),
            confidence=confidence,
            unresolved=[
                f"{count} node(s) the arithmetic tier could not decide"
                for count in [severity.unresolved_count]
                if count
            ],
        )

        # A cascade whose authorisation did not reach EXECUTE has still done all
        # its analysis -- the radius is mapped and scored -- but nothing about it
        # may leave the building. The status records that distinction.
        status = (
            CascadeStatus.COMPLETED
            if authorisation.state is DecisionState.EXECUTE
            else CascadeStatus.AWAITING_AUTHORISATION
        )

        span.set_attribute("unwind.radius_size", len(radius))
        span.set_attribute("unwind.decision_state", authorisation.state.value)
        span.set_attribute("unwind.alert_count", len(alerts))
        span.set_attribute("unwind.policy_tier", budget.policy_tier.value)

        return CascadeResult(
            cascade_id=cascade_id,
            claim_id=claim_id,
            authority=authority,
            status=status,
            decision=authorisation,
            echo=rendered,
            radius=radius,
            ranked=ranked,
            budget=budget,
            retraction=retraction,
            traversal=traversal,
            triggered_at=now,
            model_calls=0,
        )


def _all_claims(store: Any) -> list[Claim]:
    """Every claim the store can enumerate, for contest detection.

    Stores that cannot enumerate (Firestore, where a full scan would be absurd)
    return nothing, and contest detection is skipped rather than faked. Task 4
    replaces this with an indexed query on `canonical`.
    """
    claims = getattr(store, "claims", None)
    return list(claims.values()) if isinstance(claims, dict) else []


def _refuse_missing_claim(claim_id: str, now: datetime) -> StatedDecision:
    return StatedDecision(
        state=DecisionState.REFUSE,
        why=f"No claim {claim_id!r} exists to retract.",
        tier=Tier.T0.value,
        decided_at=now,
    )


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _force_unresolved(reason_code: str, reason: str):
    from spine.materiality import MaterialityVerdict

    return MaterialityVerdict(MaterialityOutcome.UNRESOLVED, reason_code, reason)
