"""The cascade as an ADK 2 Workflow of FunctionNodes.

Every node here is a `FunctionNode` -- a plain Python callable with no model
attached. That is the idiomatic ADK 2 expression of T0/T1: the framework gives
scheduling, retries, tracing and durable state, and gives up nothing to a
language model, because there is no `LlmAgent` anywhere in this graph.

    START → authority ─(refuse)→ record_refusal
                     └─(allow)──→ propagate → traverse → score → budget

THE FOUR-REGIME SPLIT IS A ROUTE, NOT A PROMPT
-----------------------------------------------
`score_node` sets `ctx.route` from `spine.regimes.route_regime`, and the edges
out of it are labelled with regime values. The branch a conclusion takes is
chosen by a total function over two values. There is no wording that could talk
it into a different cell, which is the entire reason the novelty is trustworthy.

The arithmetic itself lives in `spine/`, not here. This module is wiring: it
maps the spine onto ADK's graph so that a cascade is observable, resumable and
composable with the agents Tasks 3 and 4 will add around it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.adk.agents.context import Context
from google.adk.workflow import DEFAULT_ROUTE, START, Edge, FunctionNode, Workflow
from pydantic import BaseModel, Field

from lib.schema import CascadeStatus, Regime
from spine.cascade import CorpusStore, run_cascade

REPO = Path(__file__).resolve().parents[2]


class CascadeState(BaseModel):
    """Workflow state. Typed so the graph is inspectable in `adk web`."""

    claim_id: str
    source_id: str
    new_value: float
    reason: str = ""
    triggered_at: str | None = None

    # Filled in as the graph runs.
    cascade_id: str | None = None
    authority_allowed: bool | None = None
    authority_reason_code: str | None = None
    radius_size: int = 0
    regime_counts: dict[str, int] = Field(default_factory=dict)
    policy_tier: str | None = None
    tier_reached: str | None = None
    stopped_reason: str | None = None
    model_calls: int = 0
    status: str | None = None


def _parse_when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def run_cascade_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    """The whole deterministic cascade, as one function node. No model call.

    Sets `ctx.route` to "refused" or "completed" so the graph branches on the
    authority verdict without anything being asked to interpret it.
    """
    state = ctx.state
    claim_id = state["claim_id"]
    source_id = state["source_id"]

    result = run_cascade(
        store=CorpusStore.from_repo(REPO),
        claim_id=claim_id,
        source_id=source_id,
        new_value=state["new_value"],
        reason=state.get("reason", ""),
        triggered_at=_parse_when(state.get("triggered_at")),
    )

    state["cascade_id"] = result.cascade_id
    state["authority_allowed"] = result.authority.allowed
    state["authority_reason_code"] = result.authority.reason_code.value
    state["radius_size"] = len(result.radius)
    state["regime_counts"] = result.regime_counts()
    state["tier_reached"] = result.tier_reached
    state["model_calls"] = result.model_calls
    state["status"] = result.status.value
    if result.budget:
        state["policy_tier"] = result.budget.policy_tier.value
        state["stopped_reason"] = result.budget.stopped_reason

    ctx.route = "refused" if result.status is CascadeStatus.REFUSED else "completed"
    return {
        "cascade_id": result.cascade_id,
        "status": result.status.value,
        "radius_size": len(result.radius),
        "regime_counts": result.regime_counts(),
        "model_calls": result.model_calls,
        "authority": result.authority.to_json(),
    }


def record_refusal_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    """Terminal branch for a refused retraction.

    A refusal is an OUTCOME, not an error. It ends here with its reason intact so
    Task 3 can put it on screen, rather than surfacing as a stack trace nobody
    can render.
    """
    state = ctx.state
    return {
        "outcome": "refused",
        "claim_id": state["claim_id"],
        "source_id": state["source_id"],
        "reason_code": state.get("authority_reason_code"),
        "radius_walked": state.get("radius_size", 0),
        "note": (
            "The authority gate refused this retraction before any edge was "
            "walked. Nothing downstream was touched."
        ),
    }


def report_node(ctx: Context, node_input: Any = None) -> dict[str, Any]:
    """Terminal branch for a completed cascade."""
    state = ctx.state
    counts = state.get("regime_counts", {})
    return {
        "outcome": "completed",
        "cascade_id": state.get("cascade_id"),
        "radius_size": state.get("radius_size", 0),
        "alerts": counts.get(Regime.MATERIAL_ESCAPED.value, 0),
        "corrected_in_place": counts.get(Regime.MATERIAL_CONTAINED.value, 0),
        "died_silently": (
            counts.get(Regime.IMMATERIAL_CONTAINED.value, 0)
            + counts.get(Regime.IMMATERIAL_ESCAPED.value, 0)
        ),
        "unresolved": counts.get(Regime.UNRESOLVED.value, 0),
        "policy_tier": state.get("policy_tier"),
        "tier_reached": state.get("tier_reached"),
        "stopped_reason": state.get("stopped_reason"),
        "model_calls": state.get("model_calls", 0),
    }


cascade = FunctionNode(func=run_cascade_node, name="cascade", parameter_binding="state")
refusal = FunctionNode(func=record_refusal_node, name="record_refusal", parameter_binding="state")
report = FunctionNode(func=report_node, name="report", parameter_binding="state")

#: The graph. `refused` is the one explicitly labelled route; everything else
#: falls to DEFAULT_ROUTE and is reported. That direction matters: an unexpected
#: route value lands in `report`, which prints the real status, rather than
#: matching nothing and letting the branch end silently.
cascade_workflow = Workflow(
    name="unwind_cascade",
    description=(
        "Authority gate, T0 blast-radius traversal, T1 arithmetic materiality and "
        "the four-regime router. Contains no LlmAgent and makes no model call."
    ),
    state_schema=CascadeState,
    edges=[
        Edge(from_node=START, to_node=cascade),
        Edge(from_node=cascade, to_node=refusal, route="refused"),
        Edge(from_node=cascade, to_node=report, route=DEFAULT_ROUTE),
    ],
)

#: `adk web agents` discovers this. It is a Workflow, not an Agent, which is the
#: honest description: there is nothing agentic about arithmetic.
root_agent = cascade_workflow


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
