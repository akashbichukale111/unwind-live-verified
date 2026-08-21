"""Capability Genome: dynamic, task-bound capability identity.

THIS MODULE IMPORTS NO FRAMEWORK AND NO MODEL CLIENT
-------------------------------------------------------
Not `google.adk`, not `lib.vertex`, nothing --
`tests/test_singularity_zero_model.py` walks this module's import graph the
same way `tests/test_hyperion_zero_model.py` already does for
`hyperion/risk.py`. Negotiating what an agent may do right now, for this
task, under this risk context is table lookup and set arithmetic over a
closed vocabulary of actions -- not judgement a model should make.

CORE PRINCIPLE
---------------
An agent does not receive unlimited, permanent power. `compute_genome` is a
pure function of (role, task, risk_class, requested_actions): the same four
inputs always fold to the same `CapabilityGenome`, the same "rederive is
bit-equal" property `warrant/ledger.py:fold_balance` and
`hyperion/risk.py:score_decision` already establish one layer down. There is
no stored, standing grant anywhere in this module -- every call recomputes
from zero.

WHY A FIXED TABLE, NOT A LEARNED OR LLM-ASSIGNED POLICY
------------------------------------------------------------
[ASSUMPTION] `BASE_ACTIONS`, `DENYLISTED_VERBS`, and `RESTRICTED_RISK_SAFE`
below are chosen constants, stated as one, exactly the same honesty
discipline `hyperion/risk.py`'s `BASE_SCORE` table already documents for
itself: a demo-legible, reproducible policy, not a measured or
industry-standard one.
"""

from __future__ import annotations

from singularity.schema import (
    AgentRole,
    CapabilityGenome,
    GenomeDecision,
    RiskLevel,
)

#: [ASSUMPTION] The standing action vocabulary each role is architecturally
#: eligible for, before any task or risk narrowing. This is the ceiling, not
#: the grant -- `compute_genome` only ever narrows it.
BASE_ACTIONS: dict[AgentRole, list[str]] = {
    AgentRole.SENTINEL: ["classify_input", "flag_suspicious", "block_request"],
    AgentRole.ORCHESTRATOR: ["plan", "delegate", "monitor", "validate", "recover"],
    AgentRole.WORKER_SQL: ["sql_read", "sql_aggregate"],
    AgentRole.WORKER_PYTHON: ["run_analysis", "read_dataset"],
    AgentRole.WORKER_DOCUMENT: ["read_document", "extract_fields"],
    AgentRole.WORKER_BROWSER: ["fetch_page", "read_page"],
    AgentRole.WORKER_COMPLIANCE: ["read_policy", "flag_violation"],
}

#: [ASSUMPTION] Verbs that never survive capability negotiation regardless of
#: role or risk class -- the closed "this is always dangerous" set. Ordered
#: worst-first purely for readability; order carries no weight in the logic.
DENYLISTED_VERBS = ("export_all", "delete", "drop_table", "exfiltrate", "disable_policy")

#: [ASSUMPTION] Under HIGH or CRITICAL risk, only these action families
#: survive even if the role and task would otherwise permit more -- a
#: read/monitor-only safe subset, never a write or delegate action.
RESTRICTED_RISK_SAFE = {
    "classify_input",
    "flag_suspicious",
    "block_request",
    "monitor",
    "validate",
    "sql_read",
    "read_dataset",
    "read_document",
    "read_page",
    "read_policy",
}

#: [ASSUMPTION] Keyword → risk-class floor. A task whose text names a
#: sensitive domain or a bulk-export intent is never scored below this floor,
#: regardless of the risk_class the caller supplied -- the same "the request
#: cannot talk its way to a lower risk class" discipline
#: `tower/gateway.py`'s scope check already enforces structurally.
_RISK_FLOOR_KEYWORDS: tuple[tuple[str, RiskLevel], ...] = (
    ("secret", RiskLevel.CRITICAL),
    ("credential", RiskLevel.CRITICAL),
    ("export", RiskLevel.HIGH),
    ("finance", RiskLevel.HIGH),
    ("confidential", RiskLevel.HIGH),
    ("hr_", RiskLevel.HIGH),
)

_RISK_ORDER = (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)


def _risk_floor_for_task(task: str) -> RiskLevel:
    lowered = task.lower()
    floor = RiskLevel.LOW
    for keyword, level in _RISK_FLOOR_KEYWORDS:
        if keyword in lowered and _RISK_ORDER.index(level) > _RISK_ORDER.index(floor):
            floor = level
    return floor


def _effective_risk(risk_class: str, task: str) -> RiskLevel:
    try:
        supplied = RiskLevel(risk_class.upper())
    except ValueError:
        supplied = RiskLevel.LOW
    floor = _risk_floor_for_task(task)
    return floor if _RISK_ORDER.index(floor) > _RISK_ORDER.index(supplied) else supplied


def compute_genome(
    *,
    agent_role: AgentRole,
    task: str,
    risk_class: str,
    requested_actions: list[str],
) -> CapabilityGenome:
    """Negotiate the capability genome for one (role, task, risk, request).

    Pure function, no I/O, no clock. Narrowing happens in three ordered
    stages, each only ever removing actions, never adding one the role's
    `BASE_ACTIONS` ceiling does not already contain:

    1. Role ceiling -- `requested_actions` outside the role's base set are
       denied as `ROLE_CEILING`.
    2. Denylist -- any requested verb in `DENYLISTED_VERBS` is denied as
       `DENYLISTED`, unconditionally.
    3. Risk recalculation -- the effective risk (the higher of the caller's
       `risk_class` and the task-text risk floor) gates what survives at
       HIGH/CRITICAL to `RESTRICTED_RISK_SAFE` only.
    """
    ceiling = set(BASE_ACTIONS.get(agent_role, []))
    effective_risk = _effective_risk(risk_class, task)

    allowed: list[str] = []
    denied: list[str] = []
    denial_reasons: list[str] = []

    for action in requested_actions:
        if action not in ceiling:
            denied.append(action)
            denial_reasons.append(f"{action}: outside {agent_role.value}'s role ceiling")
            continue
        if action in DENYLISTED_VERBS:
            denied.append(action)
            denial_reasons.append(f"{action}: unconditionally denylisted")
            continue
        if (
            effective_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            and action not in RESTRICTED_RISK_SAFE
        ):
            denied.append(action)
            denial_reasons.append(f"{action}: not in the {effective_risk.value}-risk safe subset")
            continue
        allowed.append(action)

    if not requested_actions:
        decision = GenomeDecision.DENY
        reason = "no actions requested"
    elif not allowed:
        decision = GenomeDecision.DENY
        reason = "; ".join(denial_reasons)
    elif denied:
        decision = GenomeDecision.RESTRICT
        reason = "; ".join(denial_reasons)
    else:
        decision = GenomeDecision.ALLOW
        reason = (
            f"all {len(allowed)} requested action(s) within genome for {effective_risk.value} risk"
        )

    return CapabilityGenome(
        agent_role=agent_role,
        task=task,
        risk_class=risk_class,
        requested_actions=requested_actions,
        allowed_actions=allowed,
        denied_actions=denied,
        risk_level=effective_risk,
        decision=decision,
        reason=reason,
    )
