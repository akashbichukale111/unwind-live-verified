"""The Countersign agent (Card 3): a single-turn ADK 2 `AgentTool`.

WHY THIS IS ADK 2's SINGLE-TURN AgentTool, NOT PLAIN CODE OR A FREE-RUNNING
AGENT
-----------------------------------------------------------------------------
`countersign_tool` below is a real `google.adk.tools.agent_tool.AgentTool`
wrapping a real `google.adk.agents.llm_agent.Agent` (== `LlmAgent`)
constructed with `mode="single_turn"` -- ADK 2's own vocabulary for "an
agent that completes a task without chatting with the user" (see the field's
docstring in `google/adk/agents/llm_agent.py`).

The caller (`countersign/verify.py`'s minting flow) retains control at every
step: the verifier is handed one case's material, answers EXACTLY once --
`VERDICT: AGREE|DISAGREE` plus one ground line -- and the turn ends. It
cannot take the floor, redirect the workflow, call a further tool, transfer
to another agent, or write anywhere; `single_turn` mode removes that surface
at the framework level rather than by convention. A free-running
conversational agent as verifier would itself need governing (who checks
that IT didn't drift, loop, or get talked into agreeing) -- the single-turn
shape is what lets Countersign be trusted without a second Countersign
watching it.

This is the same "framework guarantee, not a convention" argument
`tower/gateway.py`'s `FunctionNode` docstring makes for the warrant SPEND
check, one layer over: there, the framework guarantees NO MODEL; here, the
framework guarantees NO SECOND TURN.

EXECUTION PATH
---------------
`AgentTool.run_async` expects a `ToolContext` built from a live
`InvocationContext`, which only exists inside a running agent invocation --
ADK's public surface does not support constructing one standalone (the same
reason `AgentTool`'s own docstring calls direct usage "discouraged" in
favour of `sub_agents=[...]`). Discovered while wiring this up: ADK also
refuses to run a `mode="single_turn"` agent as a `Runner`'s ROOT at all
(`ValueError: LlmAgent as root agent must have mode='chat'`) -- the mode's
own docstring says single_turn's home is "as a node in a workflow". So
`countersign/verify.py` executes the SAME `countersign_agent` object this
module's `countersign_tool` wraps as the one node of a one-node ADK 2
`Workflow` (`Workflow(edges=[Edge(from_node=START, to_node=countersign_agent)])`),
the identical `Workflow`/`Edge`/`START` idiom `tower/gateway.py` already
uses one layer down, run through `InMemoryRunner(node=workflow)`. The
`AgentTool` object itself is still real and independently inspectable
(`isinstance(countersign_tool, AgentTool)`, `countersign_tool.agent.mode ==
"single_turn"`) -- `tests/test_countersign_verify.py::test_countersign_agent_is_a_real_single_turn_agent_tool`
proves this the same
way `test_gateway_workflow_is_a_real_adk_workflow` proves the Gateway's
graph is real rather than asserted in prose. See `countersign/DESIGN.md`
for the live-Vertex verification this execution path was checked against.
"""

from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool

from lib.config import get_config
from lib.vertex import configure_vertex_backend

#: The verifier is told exactly what it may do and exactly how to answer.
#: Two lines, nothing else -- this is what makes `countersign/verify.py`'s
#: parse deterministic rather than a best-effort scrape of free text.
INSTRUCTION = (
    "You are an independent verifier for a decision-support system. You will "
    "be shown ONE case's extraction or judgement material: what was decided, "
    "and on what evidence. Your only job is to independently assess whether "
    "the material actually supports that judgement.\n\n"
    "You may not revise the judgement, take any action, call a tool, or ask "
    "a follow-up question -- you get exactly one turn.\n\n"
    "Respond with EXACTLY two lines and nothing else:\n"
    "VERDICT: AGREE or DISAGREE\n"
    "GROUND: one sentence stating the specific reason for your verdict."
)


def build_countersign_agent() -> Agent:
    """Construct the single-turn Gemma agent. Must run BEFORE any Vertex
    client exists -- `configure_vertex_backend()` pins the ADK/google-genai
    backend to Vertex from `lib.config`, the same ordering
    `agents/smoke/agent.py` uses, because without it ADK resolves to the
    bare Gemini developer API and asks for an API key that does not exist
    here.
    """
    configure_vertex_backend()
    cfg = get_config()
    return Agent(
        model=cfg.gemma_model,
        name="countersign_gemma",
        description=(
            "Independent-family verifier gating warrant mints (Card 3). "
            "Never chosen by, or able to influence, the judgement it reviews."
        ),
        instruction=INSTRUCTION,
        # SINGLE-TURN, not chat/task: see the module docstring. This is the
        # field that makes "the caller retains control" a property of the
        # agent's configuration, not a hope about its behaviour.
        mode="single_turn",
    )


#: The real agent object, constructed at import time -- the same discipline
#: `agents/smoke/agent.py:root_agent` and `tower/gateway.py:gateway_workflow`
#: already use: a module-level object a test can inspect directly, not a
#: factory nobody calls.
countersign_agent = build_countersign_agent()

#: The real ADK 2 AgentTool. `skip_summarization=True` because the caller
#: (`countersign/verify.py`) parses the verifier's own two-line reply
#: directly; an extra summarization pass would be a second, unaudited model
#: call between the verdict and the code that acts on it.
countersign_tool = AgentTool(agent=countersign_agent, skip_summarization=True)

__all__ = ["INSTRUCTION", "build_countersign_agent", "countersign_agent", "countersign_tool"]
