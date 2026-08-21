"""`warrant/economics.py`: the Warrant Market and the uncertainty tax.

Pure arithmetic, so these tests need no emulator, no credentials and no
clock. That is itself the point: the price of an action is re-derivable
from its inputs forever, the same "rederive is bit-equal" property
`fold_balance` establishes for balances.
"""

from __future__ import annotations

import pytest

from warrant.economics import (
    BASE_COST_BP,
    MAX_TAX_PCT,
    MUTATING_ACTIONS,
    REQUIRES_HUMAN,
    ActionKind,
    UncertaintySignals,
    assess_uncertainty,
    parse_action_kind,
    price_action,
)


def test_every_action_kind_has_a_price() -> None:
    """An unpriced action kind would be executable at an undefined cost."""
    assert set(BASE_COST_BP) == set(ActionKind)


def test_prices_are_ordered_by_blast_radius() -> None:
    assert (
        BASE_COST_BP[ActionKind.READ_PUBLIC]
        < BASE_COST_BP[ActionKind.READ_INTERNAL]
        < BASE_COST_BP[ActionKind.WRITE_SANDBOX]
        < BASE_COST_BP[ActionKind.CREATE_TICKET]
        < BASE_COST_BP[ActionKind.PRODUCTION_MUTATION]
        < BASE_COST_BP[ActionKind.SECRET_ACCESS]
    )


def test_zero_uncertainty_costs_exactly_base() -> None:
    clean = UncertaintySignals()
    for kind in ActionKind:
        priced = price_action(kind, clean)
        assert priced.tax_pct == 0
        assert priced.cost_bp == BASE_COST_BP[kind]


@pytest.mark.parametrize(
    "signals,expected_substring",
    [
        (UncertaintySignals(evidence_age_seconds=99_999), "stale evidence"),
        (UncertaintySignals(evidence_completeness=0.4), "incomplete evidence"),
        (UncertaintySignals(drift_band="CRITICAL"), "drift band CRITICAL"),
        (UncertaintySignals(model_disagreement=True), "challenger disagreed"),
        (UncertaintySignals(external_state_changed=True), "external state changed"),
        (UncertaintySignals(risk_divergence=True), "risk signals diverged"),
    ],
)
def test_each_signal_fires_independently_and_names_itself(
    signals: UncertaintySignals, expected_substring: str
) -> None:
    """Never a bare percentage: an operator reading a refusal must be able to
    see WHICH missing evidence made the action unaffordable."""
    assessment = assess_uncertainty(signals)
    assert assessment.tax_pct > 0
    assert any(expected_substring in c for c in assessment.contributions)


def test_uncertainty_strictly_raises_cost() -> None:
    """The mechanism the whole idea rests on."""
    uncertain = UncertaintySignals(
        evidence_completeness=0.5, drift_band="DRIFT", model_disagreement=True
    )
    for kind in ActionKind:
        assert price_action(kind, uncertain).cost_bp > BASE_COST_BP[kind]


def test_tax_is_capped_and_says_so() -> None:
    maximal = UncertaintySignals(
        evidence_age_seconds=10**9,
        evidence_completeness=0.0,
        drift_band="CRITICAL",
        model_disagreement=True,
        external_state_changed=True,
        risk_divergence=True,
    )
    assessment = assess_uncertainty(maximal)
    assert assessment.tax_pct == MAX_TAX_PCT
    assert assessment.capped is True
    assert any("capped" in c for c in assessment.contributions)


def test_the_cap_preserves_the_ordering_that_matters() -> None:
    """A maximally uncertain internal read must still price below a clean
    ticket creation, or the tax has stopped being a tax and become a ban."""
    maximal = UncertaintySignals(evidence_completeness=0.0, drift_band="CRITICAL")
    worst_read = price_action(ActionKind.READ_INTERNAL, maximal).cost_bp
    clean_ticket = price_action(ActionKind.CREATE_TICKET, UncertaintySignals()).cost_bp
    assert worst_read < clean_ticket


def test_price_rounds_up_never_toward_the_agent() -> None:
    """10bp at +25% is 12.5bp, which must cost 13, not 12."""
    signals = UncertaintySignals(drift_band="ELEVATED")  # +20%
    priced = price_action(ActionKind.READ_INTERNAL, signals)
    assert priced.tax_pct == 20
    assert priced.cost_bp == 12  # ceil(10 * 1.20)
    signals = UncertaintySignals(risk_divergence=True)  # +25%
    assert price_action(ActionKind.READ_INTERNAL, signals).cost_bp == 13  # ceil(12.5)


def test_no_float_survives_into_the_committed_price() -> None:
    priced = price_action(ActionKind.CREATE_TICKET, UncertaintySignals(drift_band="DRIFT"))
    assert isinstance(priced.cost_bp, int)
    assert isinstance(priced.base_bp, int)
    assert isinstance(priced.tax_pct, int)


def test_pricing_is_deterministic() -> None:
    signals = UncertaintySignals(evidence_completeness=0.62, drift_band="DRIFT")
    first = price_action(ActionKind.CREATE_TICKET, signals)
    for _ in range(20):
        assert price_action(ActionKind.CREATE_TICKET, signals) == first


def test_unknown_action_kind_raises_rather_than_defaulting() -> None:
    """The tool boundary for a model-authored plan: an action nobody costed
    must be unrepresentable, not cheap."""
    with pytest.raises(ValueError, match="closed"):
        parse_action_kind("DELETE_EVERYTHING")
    with pytest.raises(ValueError):
        parse_action_kind("")


def test_action_kind_parse_is_case_insensitive_but_still_closed() -> None:
    assert parse_action_kind("create_ticket") is ActionKind.CREATE_TICKET
    assert parse_action_kind(" READ_PUBLIC ") is ActionKind.READ_PUBLIC


def test_mutating_and_human_required_sets_are_coherent() -> None:
    """Everything that requires a human must also be something that changes
    state or reads a secret -- a human gate on a public read is friction with
    no safety value."""
    for kind in REQUIRES_HUMAN:
        assert kind in MUTATING_ACTIONS or kind is ActionKind.SECRET_ACCESS
    assert ActionKind.READ_PUBLIC not in MUTATING_ACTIONS
    assert ActionKind.ANALYZE not in MUTATING_ACTIONS


def test_priced_action_record_is_fully_auditable() -> None:
    record = price_action(
        ActionKind.CREATE_TICKET, UncertaintySignals(evidence_completeness=0.5)
    ).as_record()
    assert set(record) >= {
        "action_kind",
        "base_bp",
        "tax_pct",
        "cost_bp",
        "contributions",
        "requires_human",
        "mutating",
    }
