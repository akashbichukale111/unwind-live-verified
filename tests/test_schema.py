"""Schema invariants that were decided before any logic exists.

Temporal Truth and retraction authority are structural. Testing them now means a
later refactor that drops `invalidated_at` or lets `authority_scope` go empty
fails here rather than in a cascade.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from lib.schema import (
    Claim,
    ClaimStatus,
    ClaimType,
    Conclusion,
    ConclusionKind,
    ConclusionStatus,
    ExternalEffect,
    FalsificationPredicate,
    Regime,
    Reversibility,
    Source,
    SourceKind,
)

NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


def _claim(**overrides) -> Claim:
    payload = {
        "claim_id": "clm_test",
        "type": ClaimType.NUMERIC,
        "canonical": "supplier_K.lead_time_days",
        "value": 11,
        "unit": "days",
        "source_id": "src_supplier_K",
        "confidence": 0.9,
        "falsified_when": FalsificationPredicate(op="neq", field="value", threshold=11.0),
        "extracted_by": "premise-extractor@0.1.0",
        "extracted_at": NOW,
        "valid_from": NOW,
        "authority_scope": ["src_supplier_K"],
    }
    payload.update(overrides)
    return Claim(**payload)


def test_claim_carries_all_three_temporal_truth_fields() -> None:
    claim = _claim()
    for field_name in ("valid_from", "invalidated_at", "invalidation_reason"):
        assert field_name in Claim.model_fields, f"{field_name} missing from Claim"
    # A live claim is not "true"; it is a value valid from an instant, with no
    # invalidation recorded yet.
    assert claim.valid_from == NOW
    assert claim.invalidated_at is None
    assert claim.invalidation_reason is None
    assert claim.status is ClaimStatus.LIVE


def test_claim_rejects_empty_authority_scope() -> None:
    """An empty scope means 'anyone may retract this', which is the hole 1.4 closes."""
    with pytest.raises(ValidationError):
        _claim(authority_scope=[])


def test_source_carries_authority() -> None:
    source = Source(
        source_id="src_broker_Z",
        name="Zenith Freight Brokerage",
        kind=SourceKind.BROKER_EMAIL,
        load_rating=0.41,
        authority=["freight_broker_Z."],
    )
    assert source.authority == ["freight_broker_Z."]
    assert "authority" in Source.model_fields


def test_unresolved_is_a_first_class_conclusion_status() -> None:
    assert ConclusionStatus.UNRESOLVED.value == "unresolved"
    assert Regime.UNRESOLVED.value == "unresolved"
    conclusion = Conclusion(
        conclusion_id="cnc_test",
        kind=ConclusionKind.PROMISE,
        body="standing commitment governed by an unquantified clause",
        decided_at=NOW,
        owner_principal="principal_07",
        premise_ids=["clm_test"],
        status=ConclusionStatus.UNRESOLVED,
    )
    assert conclusion.status is ConclusionStatus.UNRESOLVED


def test_unparseable_predicate_is_not_machine_checkable() -> None:
    predicate = FalsificationPredicate(
        op="unparseable", field="value", unresolvable_reason="clause states no number"
    )
    assert predicate.machine_checkable is False
    assert FalsificationPredicate(op="neq", field="value", threshold=11.0).machine_checkable


def test_reversibility_has_an_unknown_member() -> None:
    """Unknown reversibility must be representable, not coerced to a safe default."""
    assert Reversibility.UNKNOWN.value == "unknown"


def test_escaped_is_derived_from_external_effects() -> None:
    contained = Conclusion(
        conclusion_id="cnc_a",
        kind=ConclusionKind.PLAN,
        body="internal plan",
        decided_at=NOW,
        owner_principal="principal_01",
    )
    assert contained.escaped is False

    escaped = Conclusion(
        conclusion_id="cnc_b",
        kind=ConclusionKind.QUOTE,
        body="quote sent",
        decided_at=NOW,
        owner_principal="principal_01",
        external_effects=[
            ExternalEffect(
                connector="email",
                op="send_quote",
                ref="email-1",
                reversibility=Reversibility.IDEMPOTENT,
                occurred_at=NOW,
            )
        ],
    )
    assert escaped.escaped is True


def test_four_regimes_exist_and_exactly_one_is_the_alert() -> None:
    """The matrix is still 2x2. UNRESOLVED and CLOSED_OUT sit outside it.

    UNRESOLVED means the system could not decide; CLOSED_OUT means the question
    did not apply because the commitment had already discharged. Neither is a
    cell of materiality x escapement, so neither is counted as one.
    """
    outside_the_matrix = {Regime.UNRESOLVED, Regime.CLOSED_OUT}
    operational = {r for r in Regime if r not in outside_the_matrix}
    assert len(operational) == 4
    assert Regime.MATERIAL_ESCAPED in operational
