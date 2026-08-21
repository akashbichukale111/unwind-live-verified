"""Throwaway ADK 2 agent. DELETE-READY.

Its only job is to prove that ADK 2.6.3, lib.config and Vertex AI are wired to
each other end to end. It contains no UNWIND logic: no extraction, no cascade,
no scoring. When Task 2 lands the first real agent, delete this whole directory.

It does carry one thing worth keeping in mind while reading Task 2: the
`echo_tier` tool is a plain `FunctionTool`, which is what a T0/T1 node looks
like -- deterministic, no model call, callable with Vertex switched off.
"""

from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from lib.config import Tier, get_config
from lib.vertex import configure_vertex_backend

# Must run BEFORE the Agent is constructed. ADK resolves its backend from the
# environment; with nothing set it falls through to the bare Gemini API and asks
# for an API key. Vertex AI is not optional here.
configure_vertex_backend()


def echo_tier(tier: str) -> dict[str, str]:
    """Return the tier's degradation guarantee. Deterministic; no model call.

    Args:
        tier: One of "T0", "T1", "T2".

    Returns:
        A dict with the tier and whether it is permitted to call a model.
    """
    try:
        resolved = Tier(tier.upper())
    except ValueError:
        return {"tier": tier, "error": "unknown tier; expected T0, T1 or T2"}
    model_free = resolved in {Tier.T0, Tier.T1}
    return {
        "tier": resolved.value,
        "model_allowed": str(not model_free),
        "guarantee": (
            "survives a total Vertex outage"
            if model_free
            else "requires Vertex; degrades to UNRESOLVED when unavailable"
        ),
    }


root_agent = Agent(
    model=get_config().gemini_model,
    name="smoke",
    description="Delete-ready smoke test proving ADK 2 + Vertex + lib.config are wired.",
    instruction=(
        "You are a scaffolding smoke test for a project called UNWIND. "
        "You have no product behaviour. When asked about a tier, call the "
        "echo_tier tool and report exactly what it returns. Do not invent "
        "anything about UNWIND itself."
    ),
    tools=[echo_tier],
)
