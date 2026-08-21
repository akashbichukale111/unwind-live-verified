"""`evaluate_with_hyperion`: the one place Hyperion touches the Gateway --
by calling it, unchanged, never by replacing or shadowing it.

WHY THIS IS A WRAPPER, NOT A SECOND GATEWAY
-----------------------------------------------
`tower.gateway.evaluate_gateway` is Card 2's one choke point, and it stays
that way: this function calls it with the exact arguments it already accepts
and returns its exact `GatewayDecision`, untouched. What Hyperion adds is
read-only on top -- a deterministic score (`hyperion.risk.score_decision`)
and a durable log entry (`hyperion.immune_memory.write_event`) -- so a caller
that already uses `evaluate_gateway` directly sees identical enforcement
whether or not Hyperion is wired in front of it. There is no code path here
that can overturn what the Gateway decided.
"""

from __future__ import annotations

from hyperion.immune_memory import write_event
from hyperion.risk import score_decision
from hyperion.schema import RiskAssessment
from tower.gateway import evaluate_gateway
from tower.schema import AgentRegistryEntry, GatewayDecision


def evaluate_with_hyperion(
    agent: AgentRegistryEntry,
    *,
    task: str,
    requested_scope: list[str],
    requested_cost: int,
    risk_class: str,
    arbiter: str | None = None,
    owners: tuple[str, ...] = (),
    assessor: str | None = None,
    rederiver: str | None = None,
    capability: str | None = None,
    case_id: str | None = None,
) -> tuple[GatewayDecision, RiskAssessment]:
    """Real Gateway enforcement, plus a risk score and a durable log entry.

    Returns exactly what `evaluate_gateway` returned, alongside the
    `RiskAssessment` folded from it. The log write happens after the real
    decision is already final -- Hyperion observes, it does not gate.
    """
    decision = evaluate_gateway(
        agent,
        task=task,
        requested_scope=requested_scope,
        requested_cost=requested_cost,
        risk_class=risk_class,
        arbiter=arbiter,
        owners=owners,
        assessor=assessor,
        rederiver=rederiver,
        capability=capability,
        case_id=case_id,
    )
    assessment = score_decision(decision, risk_class=risk_class)
    write_event(
        agent_id=agent.agent_id,
        task=task,
        risk_class=risk_class,
        decision=decision,
        assessment=assessment,
        capability=capability,
        case_id=case_id,
    )
    return decision, assessment
