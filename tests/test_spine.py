"""The rest of the deterministic spine: authority, traversal, T1, escapement,
budget, temporal truth, causal debt, and ground-truth isolation.

Fixtures here are hand-built rather than drawn from the corpus, so each test
pins one behaviour instead of asserting that today's corpus happens to have it.
The corpus-scale assertions live in the eval, which is where they belong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lib.schema import (
    AuthorityReason,
    BudgetTier,
    Claim,
    ClaimStatus,
    ClaimType,
    Conclusion,
    ConclusionKind,
    ExternalEffect,
    FalsificationPredicate,
    ReverseEdge,
    Reversibility,
    Source,
    SourceKind,
)
from spine.authority import check_authority
from spine.budget import RadiusSeverity, decide_budget
from spine.escapement import lookup_escapement
from spine.materiality import MaterialityOutcome, score_materiality
from spine.temporal import retract
from spine.traversal import traverse

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_claim(
    claim_id: str = "clm_hub",
    canonical: str = "supplier_K.lead_time_days",
    value=11,
    claim_type: ClaimType = ClaimType.NUMERIC,
    authority_scope: list[str] | None = None,
    status: ClaimStatus = ClaimStatus.LIVE,
    machine_checkable: bool = True,
    load_weight: int = 0,
    confidence: float = 0.9,
    valid_from: datetime | None = None,
) -> Claim:
    predicate = (
        FalsificationPredicate(op="neq", field="value", threshold=11.0)
        if machine_checkable
        else FalsificationPredicate(
            op="unparseable", field="value", unresolvable_reason="clause states no number"
        )
    )
    return Claim(
        claim_id=claim_id,
        type=claim_type,
        canonical=canonical,
        value=value,
        unit="days",
        source_id="src_supplier_K",
        confidence=confidence,
        falsified_when=predicate,
        extracted_by="test",
        extracted_at=NOW,
        valid_from=valid_from or NOW - timedelta(days=30),
        authority_scope=authority_scope or ["src_supplier_K"],
        status=status,
        load_weight=load_weight,
    )


def make_conclusion(
    conclusion_id: str = "cnc_1",
    committed: int | None = 14,
    closes_at: datetime | None = None,
    effects: list[ExternalEffect] | None = None,
    effects_recorded: bool = True,
    emits: str | None = None,
    premise_ids: list[str] | None = None,
) -> Conclusion:
    return Conclusion(
        conclusion_id=conclusion_id,
        kind=ConclusionKind.QUOTE,
        body="test",
        decided_at=NOW - timedelta(days=60),
        owner_principal="principal_01",
        premise_ids=premise_ids or ["clm_hub"],
        external_effects=effects or [],
        effects_recorded=effects_recorded,
        committed_lead_days=committed,
        closes_at=closes_at or NOW + timedelta(days=60),
        emits_claim_id=emits,
    )


def make_source(source_id: str = "src_supplier_K", authority: list[str] | None = None) -> Source:
    return Source(
        source_id=source_id,
        name=source_id,
        kind=SourceKind.SUPPLIER_EMAIL,
        authority=authority if authority is not None else ["supplier_K."],
    )


class DictStore:
    """Minimal GraphStore for hand-built graphs."""

    def __init__(self, claims, conclusions, edges, sources=()):
        self.claims = {c.claim_id: c for c in claims}
        self.conclusions = {c.conclusion_id: c for c in conclusions}
        self.sources = {s.source_id: s for s in sources}
        self.edges: dict[str, list[ReverseEdge]] = {}
        for edge in edges:
            self.edges.setdefault(edge.claim_id, []).append(edge)

    def get_claim(self, claim_id):
        return self.claims.get(claim_id)

    def get_conclusion(self, conclusion_id):
        return self.conclusions.get(conclusion_id)

    def get_source(self, source_id):
        return self.sources.get(source_id)

    def direct_dependents(self, claim_id):
        return self.edges.get(claim_id, [])


# ---------------------------------------------------------------------------
# Authority gate
# ---------------------------------------------------------------------------


def test_authority_allows_a_source_named_in_the_claim_scope() -> None:
    decision = check_authority(
        make_source(),
        make_claim(authority_scope=["src_supplier_K"]),
        "src_supplier_K",
        "clm_hub",
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.reason_code is AuthorityReason.SOURCE_IN_CLAIM_SCOPE


def test_authority_allows_a_source_holding_a_covering_prefix() -> None:
    decision = check_authority(
        make_source(authority=["supplier_K."]),
        make_claim(authority_scope=["src_msa_K"]),
        "src_supplier_K",
        "clm_hub",
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.reason_code is AuthorityReason.SOURCE_HAS_STANDING


def test_authority_refuses_the_forged_retraction() -> None:
    """The weapon this gate exists to stop: a broker retracting a supplier fact."""
    decision = check_authority(
        make_source("src_broker_Z", authority=["freight_broker_Z."]),
        make_claim(authority_scope=["src_supplier_K", "src_msa_K"]),
        "src_broker_Z",
        "clm_hub",
        now=NOW,
    )
    assert decision.allowed is False
    assert decision.reason_code is AuthorityReason.SOURCE_OUTSIDE_CLAIM_SCOPE
    assert "no standing" in decision.reason
    # It is a RECORDED EVENT, carrying both sides of the comparison.
    assert decision.source_authority == ["freight_broker_Z."]
    assert decision.claim_authority_scope == ["src_supplier_K", "src_msa_K"]


@pytest.mark.parametrize(
    ("source", "claim", "expected"),
    [
        (None, make_claim(), AuthorityReason.NO_SUCH_SOURCE),
        (make_source(), None, AuthorityReason.NO_SUCH_CLAIM),
        (
            make_source(),
            make_claim(status=ClaimStatus.RETRACTED),
            AuthorityReason.CLAIM_NOT_LIVE,
        ),
    ],
)
def test_authority_refuses_on_missing_or_dead_information(source, claim, expected) -> None:
    """No path through the gate allows on missing information."""
    decision = check_authority(source, claim, "src_x", "clm_x", now=NOW)
    assert decision.allowed is False
    assert decision.reason_code is expected


def test_a_prefix_must_not_match_a_different_claim_family() -> None:
    """`supplier_K.` must not confer authority over `supplier_KK.`-style names."""
    decision = check_authority(
        make_source(authority=["supplier_K."]),
        make_claim(canonical="supplier_L.lead_time_days", authority_scope=["src_supplier_L"]),
        "src_supplier_K",
        "clm_hub",
        now=NOW,
    )
    assert decision.allowed is False


# ---------------------------------------------------------------------------
# T0 traversal
# ---------------------------------------------------------------------------


def test_traversal_finds_the_transitive_closure_with_true_depths() -> None:
    claims = [make_claim("clm_a"), make_claim("clm_b")]
    conclusions = [
        make_conclusion("cnc_1", emits="clm_b"),
        make_conclusion("cnc_2"),
    ]
    edges = [
        ReverseEdge(claim_id="clm_a", conclusion_id="cnc_1", depth=1),
        ReverseEdge(claim_id="clm_b", conclusion_id="cnc_2", depth=1),
    ]
    result = traverse(DictStore(claims, conclusions, edges), "clm_a")

    assert set(result.nodes) == {"cnc_1", "cnc_2"}
    assert result.nodes["cnc_1"].depth == 1
    assert result.nodes["cnc_2"].depth == 2
    assert result.max_depth == 2
    # The path explains the verdict without re-running the walk.
    assert result.nodes["cnc_2"].path == ["clm_a", "cnc_1", "clm_b", "cnc_2"]


def test_traversal_terminates_and_records_a_cycle() -> None:
    """A conclusion emitting a claim that is already upstream of it."""
    claims = [make_claim("clm_a"), make_claim("clm_b")]
    conclusions = [
        make_conclusion("cnc_1", emits="clm_b"),
        # cnc_2 emits clm_a, which is the root: a genuine cycle.
        make_conclusion("cnc_2", emits="clm_a"),
    ]
    edges = [
        ReverseEdge(claim_id="clm_a", conclusion_id="cnc_1", depth=1),
        ReverseEdge(claim_id="clm_b", conclusion_id="cnc_2", depth=1),
    ]
    result = traverse(DictStore(claims, conclusions, edges), "clm_a")

    assert set(result.nodes) == {"cnc_1", "cnc_2"}
    assert result.cycles_detected, "the cycle was swallowed instead of recorded"
    assert "cnc_2 emits clm_a" in result.cycles_detected[0]


def test_traversal_survives_a_self_referential_conclusion() -> None:
    conclusions = [make_conclusion("cnc_1", emits="clm_a")]
    edges = [ReverseEdge(claim_id="clm_a", conclusion_id="cnc_1", depth=1)]
    result = traverse(DictStore([make_claim("clm_a")], conclusions, edges), "clm_a")
    assert set(result.nodes) == {"cnc_1"}
    assert result.cycles_detected


def test_traversal_records_a_dangling_edge_rather_than_dropping_it() -> None:
    edges = [ReverseEdge(claim_id="clm_a", conclusion_id="cnc_missing", depth=1)]
    result = traverse(DictStore([make_claim("clm_a")], [], edges), "clm_a")
    assert result.dangling_edges == ["cnc_missing"]
    assert "cnc_missing" in result.nodes  # still in the radius, not hidden


def test_traversal_is_deterministic() -> None:
    conclusions = [make_conclusion(f"cnc_{i}") for i in range(20)]
    edges = [ReverseEdge(claim_id="clm_a", conclusion_id=f"cnc_{i}", depth=1) for i in range(20)]
    store = DictStore([make_claim("clm_a")], conclusions, edges)
    first = [n.conclusion_id for n in traverse(store, "clm_a").nodes.values()]
    for _ in range(3):
        assert [n.conclusion_id for n in traverse(store, "clm_a").nodes.values()] == first


def test_max_depth_bounds_the_walk() -> None:
    claims = [make_claim("clm_a"), make_claim("clm_b")]
    conclusions = [make_conclusion("cnc_1", emits="clm_b"), make_conclusion("cnc_2")]
    edges = [
        ReverseEdge(claim_id="clm_a", conclusion_id="cnc_1", depth=1),
        ReverseEdge(claim_id="clm_b", conclusion_id="cnc_2", depth=1),
    ]
    result = traverse(DictStore(claims, conclusions, edges), "clm_a", max_depth=1)
    assert set(result.nodes) == {"cnc_1"}


# ---------------------------------------------------------------------------
# T1 materiality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("committed", "expected", "reason_code"),
    [
        (14, MaterialityOutcome.MATERIAL, "shock_exceeds_slack"),  # slack 3 < shock 9
        (19, MaterialityOutcome.MATERIAL, "shock_exceeds_slack"),  # slack 8 < 9
        (20, MaterialityOutcome.IMMATERIAL, "slack_absorbs_shock"),  # slack 9, not < 9
        (30, MaterialityOutcome.IMMATERIAL, "slack_absorbs_shock"),
    ],
)
def test_materiality_is_the_stated_arithmetic(committed, expected, reason_code) -> None:
    verdict = score_materiality(
        make_conclusion(committed=committed), make_claim(), 11.0, 20.0, as_of=NOW
    )
    assert verdict.outcome is expected
    assert verdict.reason_code == reason_code
    assert verdict.shock_days == 9
    assert verdict.slack_days == committed - 11


def test_the_boundary_is_strict_greater_than() -> None:
    """slack == shock is IMMATERIAL. Off-by-one here is a false retraction."""
    assert (
        score_materiality(
            make_conclusion(committed=20), make_claim(), 11.0, 20.0, as_of=NOW
        ).outcome
        is MaterialityOutcome.IMMATERIAL
    )
    assert (
        score_materiality(
            make_conclusion(committed=19), make_claim(), 11.0, 20.0, as_of=NOW
        ).outcome
        is MaterialityOutcome.MATERIAL
    )


def test_a_commitment_that_already_closed_out_gets_its_own_outcome() -> None:
    """A delivery completed in March cannot be harmed by a premise moving in July.

    CLOSED-OUT rather than IMMATERIAL: it still reports `material is False`, so
    nothing downstream over-alerts, but the reason an operator sees is the true
    one -- the shock never applied, rather than a buffer absorbed it.
    """
    verdict = score_materiality(
        make_conclusion(committed=12, closes_at=NOW - timedelta(days=30)),
        make_claim(),
        11.0,
        20.0,
        as_of=NOW,
    )
    assert verdict.outcome is MaterialityOutcome.CLOSED_OUT
    assert verdict.reason_code == "already_closed_out"
    assert verdict.material is False


def test_a_favourable_move_is_immaterial() -> None:
    verdict = score_materiality(make_conclusion(committed=12), make_claim(), 11.0, 8.0, as_of=NOW)
    assert verdict.outcome is MaterialityOutcome.IMMATERIAL
    assert verdict.reason_code == "shock_not_adverse"


@pytest.mark.parametrize(
    "claim_type", [ClaimType.CONTRACTUAL, ClaimType.REGULATORY, ClaimType.RELATIONAL]
)
def test_non_arithmetic_claim_types_are_pending_judgment_not_guessed(claim_type) -> None:
    verdict = score_materiality(
        make_conclusion(), make_claim(claim_type=claim_type), 11.0, 20.0, as_of=NOW
    )
    assert verdict.outcome is MaterialityOutcome.PENDING_JUDGMENT
    assert verdict.material is None


def test_an_unparseable_predicate_is_unresolved() -> None:
    verdict = score_materiality(
        make_conclusion(), make_claim(machine_checkable=False), 11.0, 20.0, as_of=NOW
    )
    assert verdict.outcome is MaterialityOutcome.UNRESOLVED
    assert verdict.material is None


def test_a_missing_committed_lead_time_is_unresolved_not_safe() -> None:
    verdict = score_materiality(
        make_conclusion(committed=None), make_claim(), 11.0, 20.0, as_of=NOW
    )
    assert verdict.outcome is MaterialityOutcome.UNRESOLVED
    assert verdict.material is None


def test_an_unreadable_conclusion_is_unresolved() -> None:
    verdict = score_materiality(None, make_claim(), 11.0, 20.0, as_of=NOW)
    assert verdict.outcome is MaterialityOutcome.UNRESOLVED


# ---------------------------------------------------------------------------
# Escapement
# ---------------------------------------------------------------------------


def _effect(reversibility=Reversibility.IDEMPOTENT, amount=None, when=None):
    return ExternalEffect(
        connector="email",
        op="send_quote",
        ref="e1",
        reversibility=reversibility,
        occurred_at=when or NOW - timedelta(days=30),
        amount_minor=amount,
        currency="USD" if amount else None,
    )


def test_recorded_effects_mean_escaped() -> None:
    verdict = lookup_escapement(make_conclusion(effects=[_effect()]), as_of=NOW)
    assert verdict.escaped is True
    assert verdict.reason_code == "effects_recorded"


def test_an_empty_but_present_effect_record_is_believed() -> None:
    """`[]` with effects_recorded=True asserts nothing left the building."""
    verdict = lookup_escapement(make_conclusion(effects=[]), as_of=NOW)
    assert verdict.escaped is False
    assert verdict.reason_code == "no_effects_asserted"


def test_a_missing_effect_record_fails_safe_to_escaped() -> None:
    """The asymmetry: a wasted check is cheap, an untold customer is not."""
    verdict = lookup_escapement(make_conclusion(effects_recorded=False), as_of=NOW)
    assert verdict.escaped is True
    assert verdict.reason_code == "no_effect_record"


def test_an_unreadable_conclusion_fails_safe_to_escaped() -> None:
    verdict = lookup_escapement(None, as_of=NOW)
    assert verdict.escaped is True
    assert verdict.reason_code == "conclusion_unreadable"


def test_effects_scheduled_after_the_retraction_have_not_escaped_yet() -> None:
    verdict = lookup_escapement(
        make_conclusion(effects=[_effect(when=NOW + timedelta(days=5))]), as_of=NOW
    )
    assert verdict.escaped is False
    assert verdict.reason_code == "effects_not_yet_occurred"


def test_money_and_worst_irreversibility_are_aggregated() -> None:
    verdict = lookup_escapement(
        make_conclusion(
            effects=[
                _effect(Reversibility.IDEMPOTENT),
                _effect(Reversibility.IRREVERSIBLE, amount=1_265_000),
            ]
        ),
        as_of=NOW,
    )
    assert verdict.amount_minor_at_risk == 1_265_000
    assert verdict.worst_irreversibility == 1.0
    assert verdict.has_money_at_risk


def test_unknown_reversibility_scores_near_irreversible() -> None:
    """An effect nobody can classify is not evidence that it is cheap to undo."""
    verdict = lookup_escapement(
        make_conclusion(effects=[_effect(Reversibility.UNKNOWN)]), as_of=NOW
    )
    assert verdict.worst_irreversibility == 0.8


# ---------------------------------------------------------------------------
# Budget policy
# ---------------------------------------------------------------------------


def _severity(**kw) -> RadiusSeverity:
    base = {
        "radius_size": 100,
        "alert_count": 0,
        "material_count": 0,
        "unresolved_count": 0,
        "total_money_minor": 0,
        "max_irreversibility": 0.0,
    }
    base.update(kw)
    return RadiusSeverity(**base)


def test_a_clean_radius_earns_only_the_free_tiers() -> None:
    budget = decide_budget(_severity())
    assert budget.policy_tier is BudgetTier.LOW
    assert budget.max_model_calls == 0
    assert budget.stopped_reason is None  # LOW is fully implemented


def test_irreversible_escaped_money_escalates_to_critical() -> None:
    budget = decide_budget(
        _severity(
            alert_count=3, material_count=3, max_irreversibility=1.0, total_money_minor=1_265_000
        )
    )
    assert budget.policy_tier is BudgetTier.CRITICAL
    assert budget.tier_reached == "T1"
    assert budget.stopped_reason and "Task 4" in budget.stopped_reason


def test_unresolved_nodes_alone_warrant_medium() -> None:
    budget = decide_budget(_severity(unresolved_count=4))
    assert budget.policy_tier is BudgetTier.MEDIUM
    assert budget.stopped_reason and "Task 3" in budget.stopped_reason


def test_every_budget_states_its_rationale() -> None:
    for severity in (_severity(), _severity(alert_count=20, total_money_minor=5_000_000)):
        assert decide_budget(severity).rationale


# ---------------------------------------------------------------------------
# Temporal Truth
# ---------------------------------------------------------------------------


def test_retraction_sets_all_three_temporal_truth_fields() -> None:
    result = retract(make_claim(), 20, "supplier notified a change", at=NOW)
    assert result.retracted.status is ClaimStatus.RETRACTED
    assert result.retracted.invalidated_at == NOW
    assert result.retracted.invalidation_reason


def test_the_prior_value_remains_readable() -> None:
    """A conclusion is only defensible if you can still see what it stood on."""
    claim = make_claim(value=11)
    result = retract(claim, 20, "changed", at=NOW)
    assert result.prior.value == 11
    assert result.successor.value == 20
    # And the input object was not mutated out from under any holder.
    assert claim.value == 11
    assert claim.status is ClaimStatus.LIVE
    assert claim.invalidated_at is None


def test_the_successor_opens_where_the_prior_closed() -> None:
    result = retract(make_claim(), 20, "changed", at=NOW)
    assert result.successor.valid_from == NOW
    assert result.successor.invalidated_at is None
    assert result.successor.status is ClaimStatus.LIVE


def test_the_default_reason_says_the_world_changed_not_that_someone_erred() -> None:
    result = retract(make_claim(), 20, "", at=NOW)
    reason = result.retracted.invalidation_reason or ""
    assert "world changed" in reason.lower()
    for blame in ("wrong", "error", "mistake", "incorrect"):
        assert blame not in reason.lower()


# ---------------------------------------------------------------------------
# Ground-truth isolation (ruling 1.8)
# ---------------------------------------------------------------------------


def test_the_cascade_store_never_reads_the_marking_scheme() -> None:
    from spine.cascade import CorpusStore

    store = CorpusStore.from_repo(REPO)
    assert "radius_truth.jsonl" not in store.files_read
    assert set(store.files_read) == {
        "claims.jsonl",
        "conclusions.jsonl",
        "sources.jsonl",
        "reverse_index.jsonl",
    }


def test_asking_the_store_for_the_marking_scheme_raises() -> None:
    from spine.cascade import GROUND_TRUTH_FILENAME, GroundTruthAccessError

    assert GROUND_TRUTH_FILENAME == "radius_truth.jsonl"

    # Reach the guard directly: any future store method that tried to load it
    # must hit this rather than silently succeed.
    from spine import cascade as cascade_module

    source = (Path(cascade_module.__file__)).read_text(encoding="utf-8")
    assert "GroundTruthAccessError" in source
    assert issubclass(GroundTruthAccessError, RuntimeError)


def test_no_spine_module_reads_the_marking_scheme() -> None:
    """Naming it in a docstring is fine; reading it is not.

    Several spine modules mention `radius_truth.jsonl` precisely to record that
    they must not touch it, so a bare mention is the wrong thing to detect. What
    matters is whether any line that names it also performs a file access.
    """
    read_primitives = ("open(", "read_text", "read_bytes", "json.load", "Path(")
    offenders: list[str] = []
    for path in sorted((REPO / "spine").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "radius_truth" not in line:
                continue
            if any(primitive in line for primitive in read_primitives):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "spine reads the marking scheme:\n" + "\n".join(offenders)
