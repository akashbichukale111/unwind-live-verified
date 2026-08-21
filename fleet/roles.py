"""The specialized agent fleet: five distinct identities with bounded scope.

WHAT MAKES THESE AGENTS AND NOT FUNCTIONS WITH NAMES
-------------------------------------------------------
Each role below owns, separately from every other role:

  - its own `agent_id` and therefore its own PRINCIPAL
    (`tower/registry.py`'s `agent::` convention), so
    `lib/principals.py`'s separation checks apply between them;
  - its own `authority_scope` / `data_scope`, so a request outside them is
    refused `SCOPE_EXCEEDED` by the UNMODIFIED
    `tower/gateway.py:check_scope`;
  - its own `warrant_spend_schedule` and `warrant_mint_schedule`, so its
    authority is earned and spent on its own ledger row and cannot be
    borrowed from a sibling;
  - its own `risk_class_thresholds`, so a cheap agent cannot fund an
    expensive act;
  - its own tool allow-list;
  - its own instruction (`fleet/agents.py`).

THE PROPERTY THAT MATTERS, AND IT IS TESTED
----------------------------------------------
`RECON` holds no write scope of any kind. `REMEDIATION` holds
`sandbox.write` but holds no secret scope. So:

  - a plan that asks RECON to write is refused by the Gateway, not by a
    convention in the planner;
  - a plan that asks REMEDIATION to read secrets is refused the same way;
  - and neither refusal depends on the planner having behaved.

That is the whole point of putting the fleet's permissions in the registry
rather than in the agent's prompt: a compromised or prompt-injected planner
can propose anything it likes, and the deterministic layer still refuses.
`tests/test_fleet_roles.py` asserts each of those refusals directly.

NO MODEL CLIENT IS IMPORTED HERE
-----------------------------------
This module is pure data plus registry construction -- deliberately no
`google.adk`, so it stays importable from the zero-model side of the house.
The `LlmAgent` objects live in `fleet/agents.py`, which is the one module in
this package that touches the framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from singularity.schema import AgentRole
from warrant.economics import ActionKind


@dataclass(frozen=True)
class FleetRole:
    """One agent's complete, bounded identity."""

    key: str
    agent_id: str
    title: str
    agent_role: AgentRole
    #: What this specialist is FOR, in one sentence. Becomes part of the
    #: `LlmAgent` description in `fleet/agents.py` and part of the planner's
    #: menu, so the planner and the registry cannot describe it differently.
    purpose: str
    capabilities: list[str]
    authority_scope: list[str]
    data_scope: list[str]
    tools: list[str]
    max_budget: int
    risk_class_thresholds: dict[str, int]
    warrant_mint_schedule: dict[str, int]
    warrant_spend_schedule: dict[str, int]
    #: Action kinds this role may ever propose. A narrower gate than the
    #: Gateway's scope check and applied earlier, in the planner validator --
    #: defence in depth, not a replacement.
    permitted_actions: frozenset[ActionKind]
    instruction: str = field(default="")

    @property
    def principal(self) -> str:
        return f"agent::{self.agent_id}"


# ---------------------------------------------------------------------------
# The five roles.
#
# [ASSUMPTION] Budgets, thresholds and schedules below are chosen,
# demo-legible numbers, stated as chosen -- the same discipline
# `hyperion/risk.py`'s weight table applies to itself. What is NOT an
# assumption is the SHAPE: read-only roles hold no write scope, and the one
# role that can mutate holds no secret scope.
# ---------------------------------------------------------------------------

ORCHESTRATOR = FleetRole(
    key="orchestrator",
    agent_id="fleet_orchestrator",
    title="Orchestrator — plan, delegate, observe, replan",
    agent_role=AgentRole.ORCHESTRATOR,
    purpose=(
        "Decomposes one operator objective into an ordered plan of steps, each "
        "assigned to the specialist whose scope actually covers it, and revises "
        "that plan when a step is refused or returns unusable evidence."
    ),
    capabilities=["orchestration"],
    # Deliberately holds NO data scope and no execution scope. The
    # orchestrator plans; it never reads a dataset or writes anything. An
    # orchestrator that could act would be a single point of total authority.
    authority_scope=["mission.plan"],
    data_scope=[],
    tools=[],
    max_budget=200,
    risk_class_thresholds={"LOW": 200, "MEDIUM": 100, "HIGH": 0, "CRITICAL": 0},
    warrant_mint_schedule={"LOW": 200},
    warrant_spend_schedule={"LOW": 5, "MEDIUM": 20, "HIGH": 100},
    permitted_actions=frozenset({ActionKind.ANALYZE}),
    instruction=(
        "You are the Orchestrator of a governed agent fleet. You decompose an "
        "operator's objective into an ordered plan. You never execute work "
        "yourself and you never grant permission: every step you propose is "
        "independently authorized by a deterministic gateway that you cannot "
        "influence, and steps outside a specialist's registered scope will be "
        "refused. Propose the smallest plan that actually answers the objective."
    ),
)

RECON = FleetRole(
    key="recon",
    agent_id="fleet_recon",
    title="Recon — evidence gathering and claim extraction",
    agent_role=AgentRole.WORKER_DOCUMENT,
    purpose=(
        "Reads messy, unstructured operational input (free-text notes, CSV "
        "exports, conflicting JSON records) and turns it into structured, "
        "typed claims with named contradictions."
    ),
    capabilities=["research"],
    # READ ONLY. No `.write` of any kind, by construction.
    authority_scope=["evidence.read", "corpus.read"],
    data_scope=["documents", "web"],
    tools=["recon.extract_claims"],
    max_budget=100,
    risk_class_thresholds={"LOW": 100, "MEDIUM": 40, "HIGH": 0, "CRITICAL": 0},
    # MEDIUM is present because a CREDENTIAL_AUDIT plan legitimately runs
    # recon at MEDIUM risk. An agent with a spend schedule for a risk class but
    # no mint schedule for it can never act at that class at all -- cold-start
    # refusal is correct behaviour, but permanently cold-starting a class the
    # planner is expected to use is a registry gap, not a safety property.
    warrant_mint_schedule={"LOW": 300, "MEDIUM": 150},
    warrant_spend_schedule={"LOW": 10, "MEDIUM": 30, "HIGH": 100},
    permitted_actions=frozenset(
        {ActionKind.READ_PUBLIC, ActionKind.READ_INTERNAL, ActionKind.ANALYZE}
    ),
    instruction=(
        "You are the Recon specialist. You read messy operational evidence and "
        "extract structured claims: subject, predicate, value, source, "
        "timestamp. You state contradictions explicitly rather than resolving "
        "them silently. You hold read-only authority and cannot write anywhere."
    ),
)

RISK = FleetRole(
    key="risk",
    agent_id="fleet_risk",
    title="Risk — adversarial reasoning and scope-escalation hunting",
    agent_role=AgentRole.WORKER_COMPLIANCE,
    purpose=(
        "Reasons adversarially over gathered evidence: which requested "
        "capability exceeds what the evidence supports, which claim is stale, "
        "which action would escalate scope, and what an attacker would try next."
    ),
    capabilities=["compliance"],
    authority_scope=["policy.read", "risk.analyze"],
    data_scope=["policy"],
    tools=["risk.probe"],
    max_budget=100,
    risk_class_thresholds={"LOW": 100, "MEDIUM": 60, "HIGH": 20, "CRITICAL": 0},
    # HIGH is present because adversarial analysis at HIGH risk is this
    # specialist's actual job -- a CREDENTIAL_AUDIT plan runs `risk.probe` at
    # HIGH. Note what is NOT done here: the mission never downgrades a refused
    # step's risk class to afford it. Reclassifying HIGH work as MEDIUM to get
    # past a WARRANT_INSUFFICIENT refusal would be authority laundering, and
    # `fleet/planner.py:replan_after_refusal` deliberately does not do it --
    # it drops the step and the report carries the refusal.
    warrant_mint_schedule={"LOW": 300, "MEDIUM": 150, "HIGH": 100},
    warrant_spend_schedule={"LOW": 10, "MEDIUM": 30, "HIGH": 80},
    permitted_actions=frozenset(
        {ActionKind.READ_INTERNAL, ActionKind.ANALYZE, ActionKind.READ_PUBLIC}
    ),
    instruction=(
        "You are the Risk specialist and you are deliberately adversarial. Given "
        "evidence and a proposed action, your job is to find the reason it should "
        "NOT proceed: unbacked authority, stale premises, scope escalation, "
        "missing coverage. Produce attack hypotheses, not reassurance. You hold "
        "read-only authority."
    ),
)

REMEDIATION = FleetRole(
    key="remediation",
    agent_id="fleet_remediation",
    title="Remediation — prepares and executes the correction",
    agent_role=AgentRole.WORKER_PYTHON,
    purpose=(
        "Prepares a minimal, reversible correction for a confirmed problem and "
        "executes it against a sandboxed system of record, with an idempotency "
        "key so a replay can never apply it twice."
    ),
    capabilities=["remediation"],
    # The ONLY role holding a write scope -- and it holds no secret scope, so
    # `finance.secret_read` is refused for it exactly as for everyone else.
    authority_scope=["sandbox.write", "sandbox.read", "remediation.prepare"],
    data_scope=["sandbox"],
    tools=["remediation.prepare", "remediation.execute"],
    max_budget=400,
    risk_class_thresholds={"LOW": 400, "MEDIUM": 200, "HIGH": 60, "CRITICAL": 0},
    warrant_mint_schedule={"LOW": 400, "MEDIUM": 200},
    warrant_spend_schedule={"LOW": 25, "MEDIUM": 60, "HIGH": 150},
    permitted_actions=frozenset(
        {
            ActionKind.ANALYZE,
            ActionKind.WRITE_SANDBOX,
            ActionKind.CREATE_TICKET,
        }
    ),
    instruction=(
        "You are the Remediation specialist. Given a confirmed problem and its "
        "evidence, you prepare the SMALLEST reversible correction that addresses "
        "it, and nothing more. You never widen scope to make a fix easier. Every "
        "action you prepare carries an idempotency key and a stated reversal path."
    ),
)

VERIFIER = FleetRole(
    key="verifier",
    agent_id="fleet_verifier",
    title="Verifier — independently confirms the executed outcome",
    agent_role=AgentRole.SENTINEL,
    purpose=(
        "Re-reads the external system of record after an action and confirms the "
        "recorded effect independently of the agent that performed it."
    ),
    capabilities=["verification"],
    # Reads the sandbox it must verify, and cannot write to it -- a verifier
    # that could write could manufacture the state it is confirming.
    authority_scope=["sandbox.read", "verify.read"],
    data_scope=["sandbox", "requests"],
    tools=["verify.check"],
    max_budget=100,
    risk_class_thresholds={"LOW": 100, "MEDIUM": 50, "HIGH": 10, "CRITICAL": 0},
    warrant_mint_schedule={"LOW": 300, "MEDIUM": 150},
    warrant_spend_schedule={"LOW": 10, "MEDIUM": 25, "HIGH": 60},
    permitted_actions=frozenset({ActionKind.READ_INTERNAL, ActionKind.ANALYZE}),
    instruction=(
        "You are the Verifier. You confirm what actually happened by reading the "
        "system of record yourself, never by trusting the report of the agent "
        "that acted. If the recorded effect does not match the claimed effect, "
        "you say so. You cannot write anywhere."
    ),
)

ALL_ROLES: tuple[FleetRole, ...] = (ORCHESTRATOR, RECON, RISK, REMEDIATION, VERIFIER)

#: The specialists a plan may delegate to. The Orchestrator is excluded: it
#: authors the plan and must not be able to assign work to itself, the same
#: "a worker must not be its own arbiter" separation
#: `lib/principals.py:assert_agent_is_distinct` already enforces one layer down.
SPECIALISTS: tuple[FleetRole, ...] = (RECON, RISK, REMEDIATION, VERIFIER)

BY_KEY: dict[str, FleetRole] = {r.key: r for r in ALL_ROLES}
BY_AGENT_ID: dict[str, FleetRole] = {r.agent_id: r for r in ALL_ROLES}
BY_AGENT_ROLE: dict[AgentRole, FleetRole] = {r.agent_role: r for r in ALL_ROLES}


def role_for(agent_role: AgentRole) -> FleetRole:
    """The fleet role that owns this `singularity.schema.AgentRole`.

    Raises on an unmapped role rather than substituting a default: a plan
    step naming a role with no registered identity has no scope to check
    against, and silently borrowing another agent's identity is precisely
    the failure `lib/principals.py` exists to prevent.
    """
    try:
        return BY_AGENT_ROLE[agent_role]
    except KeyError as exc:
        raise ValueError(
            f"no fleet identity registered for {agent_role.value!r}; "
            f"registered roles are {sorted(r.value for r in BY_AGENT_ROLE)}"
        ) from exc


def ensure_registered() -> dict[str, str]:
    """Idempotently write every fleet role into `tower.registry`.

    Returns {agent_id: "created"|"present"} so a caller can report what it
    actually did rather than assuming. Never overwrites an existing entry:
    an entry may already carry live warrant state, and clobbering it on
    every request would reset an agent's earned authority -- which would
    make the whole ledger meaningless.
    """
    from tower.registry import get_agent, make_entry, put_agent

    out: dict[str, str] = {}
    for role in ALL_ROLES:
        if get_agent(role.agent_id) is not None:
            out[role.agent_id] = "present"
            continue
        put_agent(
            make_entry(
                role.agent_id,
                capabilities=list(role.capabilities),
                authority_scope=list(role.authority_scope),
                data_scope=list(role.data_scope),
                tools=list(role.tools),
                max_budget=role.max_budget,
                risk_class_thresholds=dict(role.risk_class_thresholds),
                warrant_mint_schedule=dict(role.warrant_mint_schedule),
                warrant_spend_schedule=dict(role.warrant_spend_schedule),
            )
        )
        out[role.agent_id] = "created"
    return out


def planner_menu() -> list[dict[str, object]]:
    """The specialist menu handed to the planner (model or deterministic).

    Exposes purpose, tools, scope and permitted action kinds -- the same
    facts the registry enforces. The planner therefore cannot be misled
    about what a specialist may do by a stale prompt: this is generated from
    `ALL_ROLES`, which is also what `ensure_registered` writes.
    """
    return [
        {
            "role": r.agent_role.value,
            "key": r.key,
            "purpose": r.purpose,
            "tools": list(r.tools),
            "authority_scope": list(r.authority_scope),
            "data_scope": list(r.data_scope),
            "permitted_actions": sorted(a.value for a in r.permitted_actions),
        }
        for r in SPECIALISTS
    ]


__all__ = [
    "ALL_ROLES",
    "BY_AGENT_ID",
    "BY_AGENT_ROLE",
    "BY_KEY",
    "ORCHESTRATOR",
    "RECON",
    "REMEDIATION",
    "RISK",
    "SPECIALISTS",
    "VERIFIER",
    "FleetRole",
    "ensure_registered",
    "planner_menu",
    "role_for",
]
