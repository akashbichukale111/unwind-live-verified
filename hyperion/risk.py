"""Deterministic risk scoring over a real `tower.gateway.GatewayDecision`.

THIS MODULE IMPORTS NO FRAMEWORK AND NO MODEL CLIENT
-------------------------------------------------------
Not `google.adk`, not `lib.vertex`, nothing -- `tests/test_hyperion_zero_model.py`
proves it by the same import-graph walk `tests/test_warrant_zero_model.py`
already uses one layer down. Scoring a security decision is exactly the kind
of arithmetic `spine/materiality.py`'s tier discipline already argues a model
should never be trusted with: the reason code IS the observation, and turning
a closed six-value enum into a 0-100 number plus a four-value band is
subtraction and table lookup, not judgement.

WHY A FIXED WEIGHT TABLE, NOT A LEARNED OR LLM-ASSIGNED SCORE
------------------------------------------------------------------
`score_decision` never calls a model. [ASSUMPTION] The base weight per reason
code and the risk-class adjustment below are chosen so the score orders
refusals the way an operator reading `tower/DESIGN.md`'s threat model already
would (an identity collision is worse than a budget overrun) and so the score
is legible within a demo's timescale -- the same honesty discipline
`warrant/DESIGN.md` uses for its decay rate: a chosen constant, stated as
one, never presented as measured or industry-standard.
"""

from __future__ import annotations

from hyperion.schema import RiskAssessment, RiskLevel
from tower.schema import GatewayDecision, GatewayReasonCode

#: [ASSUMPTION] Ordered by the threat model in `tower/DESIGN.md`: an agent
#: claiming to be someone it is not (PRINCIPAL_VIOLATION) outranks a worker
#: that merely loops (WORKER_FAULT), which outranks routine resource limits.
BASE_SCORE: dict[GatewayReasonCode, int] = {
    GatewayReasonCode.ALLOWED: 5,
    GatewayReasonCode.BUDGET_EXCEEDED: 55,
    GatewayReasonCode.WORKER_FAULT: 65,
    GatewayReasonCode.WARRANT_INSUFFICIENT: 72,
    GatewayReasonCode.SCOPE_EXCEEDED: 78,
    GatewayReasonCode.PRINCIPAL_VIOLATION: 95,
}

#: A one-line, human-legible label per reason code -- never a free-text
#: description a model wrote, so it is the same reproducible constant on
#: every call.
THREAT_TYPE: dict[GatewayReasonCode, str] = {
    GatewayReasonCode.ALLOWED: "Nominal",
    GatewayReasonCode.BUDGET_EXCEEDED: "Blast-Radius / Budget Overrun",
    GatewayReasonCode.WORKER_FAULT: "Runaway or Unparseable Output",
    GatewayReasonCode.WARRANT_INSUFFICIENT: "Unearned Authority",
    GatewayReasonCode.SCOPE_EXCEEDED: "Scope Escalation",
    GatewayReasonCode.PRINCIPAL_VIOLATION: "Identity / Principal Collision",
}

#: [ASSUMPTION] A HIGH-risk-class request carries more blast radius than a
#: LOW one regardless of outcome, so it nudges the score up -- capped at 100,
#: applied uniformly, never enough on its own to move a band on a clean
#: ALLOWED decision.
HIGH_RISK_CLASS_ADJUSTMENT = 5

#: Band edges. LOW < MEDIUM < HIGH < CRITICAL, never overlapping.
_BAND_EDGES: tuple[tuple[int, RiskLevel], ...] = (
    (25, RiskLevel.LOW),
    (50, RiskLevel.MEDIUM),
    (80, RiskLevel.HIGH),
    (101, RiskLevel.CRITICAL),
)


def _band_for(score: int) -> RiskLevel:
    for ceiling, level in _BAND_EDGES:
        if score < ceiling:
            return level
    return RiskLevel.CRITICAL  # pragma: no cover -- unreachable, score is clamped to 100


def score_decision(decision: GatewayDecision, *, risk_class: str) -> RiskAssessment:
    """Fold a real Gateway decision into a `RiskAssessment`.

    Pure function of `decision.reason_code` and `risk_class` alone -- no
    clock, no network, no random state. The same two inputs return the same
    `RiskAssessment` every time, the same "rederive is bit-equal" property
    `warrant/ledger.py:fold_balance` already establishes for balances.
    """
    base = BASE_SCORE[decision.reason_code]
    adjustment = HIGH_RISK_CLASS_ADJUSTMENT if risk_class == "HIGH" else 0
    score = min(100, base + adjustment)
    return RiskAssessment(
        reason_code=decision.reason_code,
        risk_score=score,
        risk_level=_band_for(score),
        threat_type=THREAT_TYPE[decision.reason_code],
    )
