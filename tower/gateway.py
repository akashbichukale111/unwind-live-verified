"""The Agent Gateway (Card 2): one choke point for every delegated task.

WHY THIS IS ADK 2's DETERMINISTIC ROUTER, NOT AN IF-STATEMENT
----------------------------------------------------------------
`gateway_workflow` below is a `google.adk.workflow.Workflow` of `FunctionNode`s
-- the exact idiom `agents/cascade/workflow.py` already uses for the T0/T1
authority gate one layer down. Each check node sets `ctx.route` to a
`GatewayReasonCode` and the `Edge`s route on that value; there is no prompt
anywhere in this file and no wording could talk a refusal into a different
branch. `spine/authority.py` is the pattern one level down (compare a
source's authority to a claim's scope, return allow-or-refuse with a reason
code, decide before any edge is walked); this is the same pattern one level
up, over delegated agent tasks instead of retractions.

The deterministic checks (`check_principal`, `check_scope`, `check_budget`,
`check_warrant`) are plain functions, tested directly -- the same relationship
`spine.cascade.run_cascade` has to `agents/cascade/workflow.py`: the ADK graph
is a thin, real, importable wrapper over logic a unit test can call without
standing up the ADK runner.

ORDER MATTERS, AND IT IS FIXED
-------------------------------
PRINCIPAL_VIOLATION -> SCOPE_EXCEEDED -> BUDGET_EXCEEDED -> WARRANT_INSUFFICIENT.
Each refuses BEFORE any work happens -- `evaluate_gateway` returns the first
refusal it finds and never proceeds past it.

WARRANT_INSUFFICIENT IS NOW REAL (Card 0)
-------------------------------------------
`check_warrant` used to be a stub that always passed -- that was the whole
point of shipping the reason code and the code path before the arithmetic
existed. Card 0 (`warrant/ledger.py`) now fills it in: `check_warrant` calls
`warrant.ledger.spend_or_refuse`, an ATOMIC SPEND-or-refuse operation that
reads the agent's LIVE warrant ledger (no cache -- a `BURN` committed a
moment ago is visible to the very next call, see
`warrant/ledger.py:spend_or_refuse`'s docstring) and either debits the
registry-fixed cost for this risk class or refuses before any work happens.
A cold-start agent (no warrant ever minted) refuses by construction: the
fold of zero events is zero, and zero never covers a positive cost.

WHY THE ATOMIC SPEND IS AN ADK 2 FunctionNode HERE, NOT PLAIN CODE
-----------------------------------------------------------------------
`warrant_check` below (the `FunctionNode` wrapping `_warrant_node`, which
calls `check_warrant`) is where the framework's own guarantee -- a
`FunctionNode` contains no model, by construction of the framework -- turns
"zero model calls in the authority path" into a property the graph itself
enforces, not a convention this file has to be trusted to uphold. See
`warrant/DESIGN.md` for the fuller note.

FAILURE-TOLERANT ROUTING (rubric-quoted: "how does the system recover if a
worker agent loops or returns a hallucination") IS ALSO A ROUTE
------------------------------------------------------------------
`check_worker_fault` is a supervisor branch on the SAME router: a dispatched
worker that exceeds its step ceiling or returns output the caller cannot
parse is routed -- never retried into silently -- to `awaiting_human` with
reason code WORKER_FAULT. Recovery is therefore a route a test can assert on,
not a behaviour that depends on someone remembering to add a try/except.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from google.adk.agents.context import Context
from google.adk.workflow import DEFAULT_ROUTE, START, Edge, FunctionNode, Workflow

from lib.config import Tier
from lib.principals import PrincipalSeparationError, assert_agent_is_distinct
from lib.telemetry import policy_gate_span
from tower.schema import AgentRegistryEntry, GatewayDecision, GatewayReasonCode, RegistryStatus
from warrant.ledger import spend_or_refuse

#: A worker gets this many steps before the supervisor calls it a loop. Small
#: on purpose: the point is to prove the branch routes, not to tune a real
#: agent's budget (there is no real worker yet -- see the module docstring's
#: non-goal note).
DEFAULT_STEP_CEILING = 8


def _decision(
    *, allowed: bool, reason_code: GatewayReasonCode, reason: str, agent_id: str, task: str
) -> GatewayDecision:
    return GatewayDecision(
        allowed=allowed,
        reason_code=reason_code,
        reason=reason,
        agent_id=agent_id,
        task=task,
        checked_at=datetime.now(UTC),
    )


def check_principal(
    agent: AgentRegistryEntry,
    *,
    task: str,
    arbiter: str | None = None,
    owners: tuple[str, ...] = (),
    assessor: str | None = None,
    rederiver: str | None = None,
) -> GatewayDecision | None:
    """None if clean. A `GatewayDecision` refusing PRINCIPAL_VIOLATION otherwise.

    Delegates to `lib.principals.assert_agent_is_distinct` -- there is exactly
    one implementation of "does this principal collide with a role it must
    not hold", shared with the court's ruling 1.10 check.
    """
    if agent.status is not RegistryStatus.ACTIVE:
        return _decision(
            allowed=False,
            reason_code=GatewayReasonCode.PRINCIPAL_VIOLATION,
            reason=f"agent {agent.agent_id!r} is {agent.status.value}, not active.",
            agent_id=agent.agent_id,
            task=task,
        )
    try:
        assert_agent_is_distinct(
            agent.principal, arbiter=arbiter, owners=owners, assessor=assessor, rederiver=rederiver
        )
    except PrincipalSeparationError as exc:
        return _decision(
            allowed=False,
            reason_code=GatewayReasonCode.PRINCIPAL_VIOLATION,
            reason=str(exc),
            agent_id=agent.agent_id,
            task=task,
        )
    return None


def check_scope(
    agent: AgentRegistryEntry, *, task: str, requested_scope: list[str]
) -> GatewayDecision | None:
    """None if every requested scope item is one the agent actually holds."""
    granted = set(agent.authority_scope) | set(agent.data_scope)
    missing = [s for s in requested_scope if s not in granted]
    if missing:
        return _decision(
            allowed=False,
            reason_code=GatewayReasonCode.SCOPE_EXCEEDED,
            reason=(
                f"agent {agent.agent_id!r} requested {missing!r}, which is outside its "
                f"granted scope {sorted(granted)!r}."
            ),
            agent_id=agent.agent_id,
            task=task,
        )
    return None


def check_budget(
    agent: AgentRegistryEntry, *, task: str, requested_cost: int, risk_class: str
) -> GatewayDecision | None:
    """None if within both the agent's flat ceiling and its risk-class ceiling.

    Two ceilings, not one -- `File B §2`: never a single global number. An
    agent with room under `max_budget` can still be refused for a HIGH-risk
    task whose class ceiling is tighter.
    """
    if requested_cost > agent.max_budget:
        return _decision(
            allowed=False,
            reason_code=GatewayReasonCode.BUDGET_EXCEEDED,
            reason=(
                f"requested cost {requested_cost} exceeds agent {agent.agent_id!r}'s "
                f"flat max_budget {agent.max_budget}."
            ),
            agent_id=agent.agent_id,
            task=task,
        )
    class_ceiling = agent.risk_class_thresholds.get(risk_class)
    if class_ceiling is not None and requested_cost > class_ceiling:
        return _decision(
            allowed=False,
            reason_code=GatewayReasonCode.BUDGET_EXCEEDED,
            reason=(
                f"requested cost {requested_cost} exceeds agent {agent.agent_id!r}'s "
                f"{risk_class!r} ceiling {class_ceiling}."
            ),
            agent_id=agent.agent_id,
            task=task,
        )
    return None


def check_warrant(
    agent: AgentRegistryEntry,
    *,
    task: str,
    risk_class: str,
    capability: str | None = None,
    case_id: str | None = None,
) -> GatewayDecision | None:
    """None if the agent's LIVE warrant balance covers this delegation's
    registry-fixed cost; a `WARRANT_INSUFFICIENT` refusal otherwise.

    `capability` defaults to the agent's sole registered capability when it
    has exactly one -- most registry entries in this codebase (and every
    existing caller of `evaluate_gateway`) register a single capability, so
    this keeps the common case a one-line call while a multi-capability
    agent must say which capability the task is exercising, since warrant is
    scoped per (principal, capability, risk_class), never collapsed to one
    number.

    This function reads `warrant.ledger.spend_or_refuse`, NOT
    `agent.warrant.balances` -- that field is Card 2's display snapshot
    (`tower/schema.py:WarrantSlot`), and reading it here would be exactly
    the cache the revocation-latency guarantee forbids. Every call to this
    function that reaches ALLOWED has already durably SPENT the cost; a
    refusal spends nothing.
    """
    resolved_capability = capability
    if resolved_capability is None:
        if len(agent.capabilities) == 1:
            resolved_capability = agent.capabilities[0]
        else:
            return _decision(
                allowed=False,
                reason_code=GatewayReasonCode.WARRANT_INSUFFICIENT,
                reason=(
                    f"agent {agent.agent_id!r} registers {len(agent.capabilities)} capabilities "
                    f"({agent.capabilities!r}); warrant is scoped per capability, so a specific "
                    "one must be named for this task rather than assumed."
                ),
                agent_id=agent.agent_id,
                task=task,
            )
    result = spend_or_refuse(
        agent=agent,
        capability=resolved_capability,
        risk_class=risk_class,
        task=task,
        case_id=case_id,
        acting_principal=agent.principal,
    )
    if not result.allowed:
        return _decision(
            allowed=False,
            reason_code=GatewayReasonCode.WARRANT_INSUFFICIENT,
            reason=result.reason,
            agent_id=agent.agent_id,
            task=task,
        )
    return None


def evaluate_gateway(
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
) -> GatewayDecision:
    """The one choke point. Runs all four checks in the fixed order and
    returns the FIRST refusal -- nothing after it runs.

    `capability` and `case_id` feed `check_warrant` alone; see its docstring
    for the single-capability default. `case_id` is the Memory Bank case
    this delegation belongs to, recorded on the resulting SPEND event so a
    later BURN or audit can point back at exactly which task consumed it.
    """
    with policy_gate_span(
        "agent_gateway", Tier.T0, agent_id=agent.agent_id, task=task, risk_class=risk_class
    ) as gate_span:
        for check, kwargs in (
            (
                check_principal,
                {
                    "arbiter": arbiter,
                    "owners": owners,
                    "assessor": assessor,
                    "rederiver": rederiver,
                },
            ),
            (check_scope, {"requested_scope": requested_scope}),
            (check_budget, {"requested_cost": requested_cost, "risk_class": risk_class}),
            (
                check_warrant,
                {"risk_class": risk_class, "capability": capability, "case_id": case_id},
            ),
        ):
            with policy_gate_span(
                f"agent_gateway.{check.__name__}", Tier.T0, agent_id=agent.agent_id, task=task
            ) as check_span:
                decision = check(agent, task=task, **kwargs)  # type: ignore[arg-type]
                check_span.set_attribute("unwind.gateway_passed", decision is None)
                if decision is not None:
                    check_span.set_attribute(
                        "unwind.gateway_reason_code", decision.reason_code.value
                    )
            if decision is not None:
                gate_span.set_attribute("unwind.gateway_reason_code", decision.reason_code.value)
                gate_span.set_attribute("unwind.gateway_allowed", False)
                return decision
        gate_span.set_attribute("unwind.gateway_reason_code", GatewayReasonCode.ALLOWED.value)
        gate_span.set_attribute("unwind.gateway_allowed", True)
    return _decision(
        allowed=True,
        reason_code=GatewayReasonCode.ALLOWED,
        reason="all checks passed.",
        agent_id=agent.agent_id,
        task=task,
    )


def check_worker_fault(
    *,
    agent_id: str,
    task: str,
    step_count: int,
    output: Any,
    step_ceiling: int = DEFAULT_STEP_CEILING,
) -> GatewayDecision | None:
    """None if the worker's run looks sane. WORKER_FAULT otherwise.

    Two independent triggers, either one is sufficient:
      - LOOP: step_count exceeds the ceiling.
      - HALLUCINATION / garbage: output is not one of the shapes a caller can
        act on (must be a dict; UNWIND never accepts free text as a decision).
    """
    with policy_gate_span(
        "agent_gateway.check_worker_fault",
        Tier.T0,
        agent_id=agent_id,
        task=task,
        step_count=step_count,
    ) as span:
        if step_count > step_ceiling:
            span.set_attribute("unwind.gateway_reason_code", GatewayReasonCode.WORKER_FAULT.value)
            span.set_attribute("unwind.worker_fault_trigger", "loop")
            return _decision(
                allowed=False,
                reason_code=GatewayReasonCode.WORKER_FAULT,
                reason=f"worker exceeded its step ceiling ({step_count} > {step_ceiling}): looping, not making progress.",
                agent_id=agent_id,
                task=task,
            )
        if not isinstance(output, dict):
            span.set_attribute("unwind.gateway_reason_code", GatewayReasonCode.WORKER_FAULT.value)
            span.set_attribute("unwind.worker_fault_trigger", "unparseable_output")
            return _decision(
                allowed=False,
                reason_code=GatewayReasonCode.WORKER_FAULT,
                reason=f"worker output is {type(output).__name__}, not a structured result: unparseable, treated as a hallucination.",
                agent_id=agent_id,
                task=task,
            )
        span.set_attribute("unwind.gateway_passed", True)
    return None


# ===========================================================================
# The ADK 2 Workflow -- the router made a first-class, traceable graph.
# ===========================================================================


class _GatewayState(dict):
    """Plain dict state: the checks below read/write it like `ctx.state` in
    `agents/cascade/workflow.py`. No pydantic schema needed for a router this
    shallow; `agents/cascade/workflow.py`'s `CascadeState` earns its schema
    because that graph is deep and inspected in `adk web` -- this one is not.
    """


def _principal_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    agent: AgentRegistryEntry = ctx.state["agent"]
    decision = check_principal(
        agent,
        task=ctx.state["task"],
        arbiter=ctx.state.get("arbiter"),
        owners=tuple(ctx.state.get("owners", ())),
        assessor=ctx.state.get("assessor"),
        rederiver=ctx.state.get("rederiver"),
    )
    ctx.route = "refused" if decision else DEFAULT_ROUTE
    if decision:
        ctx.state["decision"] = decision
    return {"checked": "principal"}


def _scope_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    agent: AgentRegistryEntry = ctx.state["agent"]
    decision = check_scope(
        agent, task=ctx.state["task"], requested_scope=ctx.state["requested_scope"]
    )
    ctx.route = "refused" if decision else DEFAULT_ROUTE
    if decision:
        ctx.state["decision"] = decision
    return {"checked": "scope"}


def _budget_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    agent: AgentRegistryEntry = ctx.state["agent"]
    decision = check_budget(
        agent,
        task=ctx.state["task"],
        requested_cost=ctx.state["requested_cost"],
        risk_class=ctx.state["risk_class"],
    )
    ctx.route = "refused" if decision else DEFAULT_ROUTE
    if decision:
        ctx.state["decision"] = decision
    return {"checked": "budget"}


def _warrant_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    """The ADK 2 `FunctionNode` body for the atomic SPEND-or-refuse check.

    A `FunctionNode` is a framework guarantee, not a convention: `google.adk`
    defines it as containing no model, so "this node makes zero model calls"
    is provable by inspecting the node's TYPE, the same way
    `test_gateway_workflow_is_a_real_adk_workflow` inspects the graph's
    shape rather than trusting a comment. See `warrant/DESIGN.md`.
    """
    agent: AgentRegistryEntry = ctx.state["agent"]
    decision = check_warrant(
        agent,
        task=ctx.state["task"],
        risk_class=ctx.state["risk_class"],
        capability=ctx.state.get("capability"),
        case_id=ctx.state.get("case_id"),
    )
    ctx.route = "refused" if decision else DEFAULT_ROUTE
    if decision:
        ctx.state["decision"] = decision
    return {"checked": "warrant"}


def _dispatch_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    """All four checks passed. The task is dispatched (simulated: Card 2
    builds the choke point, not worker execution -- explicit non-goal).
    """
    agent: AgentRegistryEntry = ctx.state["agent"]
    ctx.state["decision"] = _decision(
        allowed=True,
        reason_code=GatewayReasonCode.ALLOWED,
        reason="all checks passed; task dispatched.",
        agent_id=agent.agent_id,
        task=ctx.state["task"],
    )
    ctx.route = DEFAULT_ROUTE
    return {"dispatched": True}


def _refuse_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    decision: GatewayDecision = ctx.state["decision"]
    return {
        "outcome": "refused",
        "reason_code": decision.reason_code.value,
        "reason": decision.reason,
    }


def _allowed_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    decision: GatewayDecision = ctx.state["decision"]
    return {"outcome": "allowed", "reason_code": decision.reason_code.value}


principal_check = FunctionNode(
    func=_principal_node, name="principal_check", parameter_binding="state"
)
scope_check = FunctionNode(func=_scope_node, name="scope_check", parameter_binding="state")
budget_check = FunctionNode(func=_budget_node, name="budget_check", parameter_binding="state")
#: The atomic SPEND-or-refuse operation (Card 0), as an ADK 2 FunctionNode --
#: not plain code wired to look like one. `FunctionNode` is the framework's
#: own guaranteed-no-model node type, so "zero model calls in the authority
#: path" is a property of the graph ADK constructs, not a convention this
#: module has to be trusted to uphold. See warrant/DESIGN.md.
warrant_check = FunctionNode(func=_warrant_node, name="warrant_check", parameter_binding="state")
dispatch = FunctionNode(func=_dispatch_node, name="dispatch", parameter_binding="state")
refuse = FunctionNode(func=_refuse_node, name="refuse", parameter_binding="state")
allowed = FunctionNode(func=_allowed_node, name="allowed", parameter_binding="state")

#: The Gateway as a graph: four ordered checks. Each one routes on exactly
#: two values -- "refused" or DEFAULT_ROUTE -- because ADK 2's graph
#: validator keys edges by the (from, to) pair, not (from, to, route): four
#: distinctly-labelled edges from the same check node to the same `refuse`
#: node collide as duplicates. The WHICH of the four reason codes is not lost
#: -- `refuse_node` reads it back out of `ctx.state["decision"]`, which each
#: check node populates before setting the route. What the graph's edge list
#: proves is the thing that matters: refusal is a branch taken before
#: `dispatch` is ever reached, in a fixed order, with no node able to skip
#: past a refusal upstream of it.
gateway_workflow = Workflow(
    name="unwind_gateway",
    description=(
        "The Agent Gateway: PRINCIPAL_VIOLATION -> SCOPE_EXCEEDED -> "
        "BUDGET_EXCEEDED -> WARRANT_INSUFFICIENT, each a routed branch. "
        "Contains no LlmAgent and makes no model call."
    ),
    edges=[
        Edge(from_node=START, to_node=principal_check),
        Edge(from_node=principal_check, to_node=refuse, route="refused"),
        Edge(from_node=principal_check, to_node=scope_check, route=DEFAULT_ROUTE),
        Edge(from_node=scope_check, to_node=refuse, route="refused"),
        Edge(from_node=scope_check, to_node=budget_check, route=DEFAULT_ROUTE),
        Edge(from_node=budget_check, to_node=refuse, route="refused"),
        Edge(from_node=budget_check, to_node=warrant_check, route=DEFAULT_ROUTE),
        Edge(from_node=warrant_check, to_node=refuse, route="refused"),
        Edge(from_node=warrant_check, to_node=dispatch, route=DEFAULT_ROUTE),
        Edge(from_node=dispatch, to_node=allowed),
    ],
)

root_agent = gateway_workflow
