"""Hyperion's deterministic risk scoring: a fixed weight table, reproducible,
zero model calls. No Firestore, no emulator -- pure function tests, the same
register `tests/test_warrant_ledger.py`'s pure `fold_balance` tests use.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hyperion.risk import score_decision
from hyperion.schema import RiskLevel
from tower.schema import GatewayDecision, GatewayReasonCode


def _decision(reason_code: GatewayReasonCode, *, allowed: bool) -> GatewayDecision:
    return GatewayDecision(
        allowed=allowed,
        reason_code=reason_code,
        reason="test fixture",
        agent_id="test_agent",
        task="test task",
        checked_at=datetime.now(UTC),
    )


def test_allowed_scores_low() -> None:
    assessment = score_decision(
        _decision(GatewayReasonCode.ALLOWED, allowed=True), risk_class="LOW"
    )
    assert assessment.risk_level is RiskLevel.LOW
    assert assessment.threat_type == "Nominal"


def test_principal_violation_scores_critical() -> None:
    assessment = score_decision(
        _decision(GatewayReasonCode.PRINCIPAL_VIOLATION, allowed=False), risk_class="LOW"
    )
    assert assessment.risk_level is RiskLevel.CRITICAL
    assert assessment.risk_score == 95


def test_scope_exceeded_scores_high() -> None:
    assessment = score_decision(
        _decision(GatewayReasonCode.SCOPE_EXCEEDED, allowed=False), risk_class="LOW"
    )
    assert assessment.risk_level is RiskLevel.HIGH
    assert assessment.threat_type == "Scope Escalation"


def test_high_risk_class_only_ever_adds_a_bounded_adjustment() -> None:
    low = score_decision(_decision(GatewayReasonCode.ALLOWED, allowed=True), risk_class="LOW")
    high = score_decision(_decision(GatewayReasonCode.ALLOWED, allowed=True), risk_class="HIGH")
    assert high.risk_score == low.risk_score + 5
    assert high.risk_level is RiskLevel.LOW  # a nominal HIGH-risk-class ALLOWED stays LOW


def test_score_never_exceeds_100() -> None:
    assessment = score_decision(
        _decision(GatewayReasonCode.PRINCIPAL_VIOLATION, allowed=False), risk_class="HIGH"
    )
    assert assessment.risk_score == 100


def test_scoring_is_deterministic_and_reproducible() -> None:
    d = _decision(GatewayReasonCode.WARRANT_INSUFFICIENT, allowed=False)
    first = score_decision(d, risk_class="HIGH")
    second = score_decision(d, risk_class="HIGH")
    assert first == second


@pytest.mark.parametrize("reason_code", list(GatewayReasonCode))
def test_every_reason_code_has_a_score_and_a_threat_type(reason_code: GatewayReasonCode) -> None:
    assessment = score_decision(_decision(reason_code, allowed=True), risk_class="LOW")
    assert 0 <= assessment.risk_score <= 100
    assert assessment.threat_type
