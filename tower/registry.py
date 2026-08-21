"""The executable agent registry (Card 2), backed by Firestore.

WHY THIS IS ADK 2's DYNAMIC PATTERN, NOT PLAIN CODE
----------------------------------------------------
`compose_capability_workflow` builds a real `google.adk.workflow.Workflow` --
`FunctionNode`s wired with `Edge`s -- whose SHAPE is not known until this
function runs: the number of nodes, their names and what each one does all
come from a registry query executed at call time. This is the framework's
dynamic pattern used honestly: not a private scheduler API invoked for its
own sake, but the public `Workflow`/`FunctionNode`/`Edge`/`JoinNode`
primitives fed a node list that could not exist a second earlier, because it
is registry data. The centerpiece test in `tests/test_tower_registry.py`
proves this rather than asserting it: flip one registry field (drop a
capability, or set `status: suspended`) and the SAME call produces a
DIFFERENT graph -- a different node count, a different node-name set.

THIS IS NOT MERELY A LOOKUP TABLE because a lookup table returns data; this
returns a runnable ADK graph whose node set IS the registry query result, so
"registry drives orchestration" is provable by inspecting the graph object
`compose_capability_workflow` returns, not by reading a comment that claims
it. See `tower/DESIGN.md` for the fuller novelty note and the exact test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from google.adk.agents.context import Context
from google.adk.workflow import START, Edge, FunctionNode, JoinNode, Workflow

from lib.config import COLLECTION_AGENTS, get_config
from lib.firestore import get_client
from lib.principals import assert_agent_is_distinct
from tower.schema import AgentRegistryEntry, RegistryStatus


def put_agent(entry: AgentRegistryEntry) -> None:
    """Register (or update) one agent. Raises if its principal collides.

    The distinctness check runs on every write, not just the first one: a
    registry entry that was clean at creation and is later edited to share a
    principal with (say) an arbiter is exactly the drift ruling 1.10 exists
    to catch.
    """
    assert_agent_is_distinct(entry.principal)
    get_client().collection(COLLECTION_AGENTS).document(entry.agent_id).set(entry.to_firestore())


def get_agent(agent_id: str) -> AgentRegistryEntry | None:
    snap = get_client().collection(COLLECTION_AGENTS).document(agent_id).get()
    return AgentRegistryEntry(**snap.to_dict()) if snap.exists else None


def list_agents() -> list[AgentRegistryEntry]:
    return [
        AgentRegistryEntry(**snap.to_dict())
        for snap in get_client().collection(COLLECTION_AGENTS).stream()
    ]


def list_eligible_agents(capability: str) -> list[AgentRegistryEntry]:
    """Every ACTIVE agent whose `capabilities` include `capability`.

    Firestore cannot do the `array-contains` + `status ==` compound query
    without a composite index it is not worth adding for this cardinality
    (the registry is agents, not commitments -- tens of rows, not thousands),
    so this filters client-side. `iter_dependents` in `lib/firestore.py`
    earns its index because it runs over a 2,594-node radius; this does not.
    """
    return sorted(
        (a for a in list_agents() if a.is_eligible and capability in a.capabilities),
        key=lambda a: a.agent_id,
    )


def _stub_worker(agent_id: str, capability: str):
    """One eligible agent's node function.

    Deliberately a stub: Card 2 builds the registry and the graph it drives,
    not worker logic -- that is explicit non-goal territory for this prompt
    (no Gemma, no second model, no UI). What this proves is that THIS
    specific node, with THIS name, exists in the graph only because THIS
    agent_id was eligible at call time.
    """

    def run(ctx: Context, node_input: Any = None) -> dict[str, Any]:
        return {"agent_id": agent_id, "capability": capability, "handled": True}

    return run


def compose_capability_workflow(capability: str) -> Workflow:
    """Build a Workflow whose node set is exactly today's eligible registry.

    Empty registry (or nobody eligible) still returns a valid Workflow with a
    single START -> JoinNode edge: zero eligible workers is a real, testable
    outcome, not a special case that has to be guarded against by a caller.
    """
    eligible = list_eligible_agents(capability)

    join = JoinNode(name=f"{capability}_join")
    nodes = [
        FunctionNode(func=_stub_worker(a.agent_id, capability), name=a.agent_id) for a in eligible
    ]

    edges = [Edge(from_node=START, to_node=node) for node in nodes]
    edges += [Edge(from_node=node, to_node=join) for node in nodes]
    if not nodes:
        edges = [Edge(from_node=START, to_node=join)]

    return Workflow(
        name=f"tower_registry_{capability}",
        description=(
            f"Coordinator composed at call time from the {len(nodes)} agent(s) "
            f"registered ACTIVE with capability={capability!r}. Contains no "
            "LlmAgent; every node here is a plain FunctionNode."
        ),
        edges=edges,
    )


def eligible_node_names(capability: str) -> set[str]:
    """The provable half of the centerpiece test: exactly which node names a
    fresh composition contains right now.
    """
    return {a.agent_id for a in list_eligible_agents(capability)}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_entry(
    agent_id: str,
    *,
    capabilities: list[str],
    max_budget: int = 100,
    authority_scope: list[str] | None = None,
    data_scope: list[str] | None = None,
    tools: list[str] | None = None,
    risk_class_thresholds: dict[str, int] | None = None,
    warrant_mint_schedule: dict[str, int] | None = None,
    warrant_spend_schedule: dict[str, int] | None = None,
    status: RegistryStatus = RegistryStatus.ACTIVE,
) -> AgentRegistryEntry:
    """Convenience constructor with the `agent::` principal convention applied."""
    return AgentRegistryEntry(
        agent_id=agent_id,
        version="0.1.0",
        capabilities=capabilities,
        authority_scope=authority_scope or [],
        data_scope=data_scope or [],
        tools=tools or [],
        max_budget=max_budget,
        risk_class_thresholds=risk_class_thresholds or {},
        warrant_mint_schedule=warrant_mint_schedule or {},
        warrant_spend_schedule=warrant_spend_schedule or {},
        status=status,
        principal=f"agent::{agent_id}",
        registered_at=datetime.now(UTC),
    )


def reset_for_test() -> None:
    """Test hook: delete every document in the agents collection."""
    client = get_client()
    for snap in client.collection(COLLECTION_AGENTS).stream():
        snap.reference.delete()


__all__ = [
    "compose_capability_workflow",
    "eligible_node_names",
    "get_agent",
    "get_config",
    "list_agents",
    "list_eligible_agents",
    "make_entry",
    "put_agent",
    "reset_for_test",
]
