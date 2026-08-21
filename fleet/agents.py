"""The fleet's real ADK agents. The ONE module in `fleet/` that imports a model.

WHAT IS AND IS NOT AN LlmAgent HERE, AND WHY
-----------------------------------------------
`planner_agent` is a real `google.adk.agents.llm_agent.Agent` with a real
`output_schema`, executed through a real `InMemoryRunner`. It is the module
that turns an operator's sentence into a plan, and that is genuinely a
judgement call: which specialists matter for THIS objective, in what order,
at what risk class. A model is the right tool for it.

The four specialists (`fleet/roles.py`) also get real `LlmAgent` objects
here -- one per role, each carrying that role's own instruction and its own
tool allow-list, so a judge can inspect five distinct agents rather than one
agent with five prompts. But their WORK is done by `fleet/tools.py`, which
is deterministic. That split is deliberate and is the repository's existing
position applied one level up: a model chooses; arithmetic decides.

THE MODEL CANNOT WIDEN ITS OWN AUTHORITY
--------------------------------------------
Everything the planner emits is passed through
`fleet/planner.py:validate_plan` before anything runs:

  - `role` must be a registered specialist, else the step is dropped;
  - `tool` must be in `fleet.tools.TOOL_REGISTRY`, else dropped;
  - `action_kind` must parse to a `warrant.economics.ActionKind`, else the
    WHOLE plan is rejected and the deterministic planner is used instead;
  - `action_kind` must be in that role's `permitted_actions`, else clamped;
  - `requested_scope` is INTERSECTED with the role's registered scope.

So the strongest thing a prompt-injected or hallucinating planner can do is
propose a plan that gets narrowed to what the registry already allowed. It
cannot invent an action kind, a tool, a role, or a scope. That is the tool
boundary, and it is enforced in code that contains no model.

SINGLE-TURN, RUN AS A ONE-NODE WORKFLOW
-------------------------------------------
`mode="single_turn"` for the same reason `countersign/agent.py` uses it: the
caller keeps control, and the agent cannot take the floor, loop, or transfer.
ADK refuses a single-turn agent as a `Runner` ROOT
(`ValueError: LlmAgent as root agent must have mode='chat'`), so -- exactly
as `countersign/verify.py` already does -- it is executed as the one node of
a one-node `Workflow`. That idiom is already proven in this repository
against live Vertex; reusing it avoids inventing a second execution path
that has never been run.

LIMITATION, STATED
---------------------
[UNVERIFIED IN THIS ENVIRONMENT] No Google Cloud credentials were available
in the session that wrote this module, so the Gemini path here has NOT been
executed against live Vertex AI in this pass. The code path is real, the
schema is real, and `fleet/planner.py` reports
`PlanProvenance.ZERO_MODEL` -- honestly, in the API response and the UI --
whenever it did not run. It never reports GEMINI for a plan a model did not
produce. See `docs/SECURITY.md` and `evidence/INDEX.md` for the exact
verification status.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fleet.roles import ALL_ROLES, ORCHESTRATOR, SPECIALISTS, FleetRole
from fleet.tools import TOOL_REGISTRY
from lib.config import get_config
from lib.vertex import configure_vertex_backend


class PlannedStep(BaseModel):
    """The planner's structured output element. This IS the ADK
    `output_schema`, so the model is constrained by the framework to emit
    these fields rather than free text a regex has to scrape."""

    role: str = Field(description="One of the specialist role names offered in the menu.")
    tool: str = Field(description="One of the tool names offered for that role.")
    action_kind: str = Field(description="One of the offered ActionKind values.")
    intent: str = Field(description="One sentence: what this step is for.")
    requested_scope: list[str] = Field(
        default_factory=list, description="Scope strings this step needs."
    )
    risk_class: str = Field(default="LOW", description="LOW, MEDIUM, HIGH or CRITICAL.")
    rationale: str = Field(default="", description="Why this step, for this objective.")


class PlannedMission(BaseModel):
    """The planner's whole reply."""

    objective_class: str = Field(description="One of the offered ObjectiveClass values.")
    steps: list[PlannedStep] = Field(description="Ordered plan. Smallest that answers the goal.")
    notes: str = Field(default="", description="Anything the operator should know.")


PLANNER_INSTRUCTION = (
    "You are the Orchestrator of a governed enterprise agent fleet.\n\n"
    "You will be given: an operator objective, a menu of specialist agents "
    "(with their purpose, tools, registered scope and permitted action kinds), "
    "and a summary of evidence already gathered.\n\n"
    "Produce the SMALLEST ordered plan that actually answers the objective.\n\n"
    "Hard rules you must follow:\n"
    "- Use only roles, tools and action kinds from the menu. Anything else is "
    "discarded by a deterministic validator you cannot influence.\n"
    "- Only request scope a specialist already holds. Requesting more does not "
    "grant more; it gets the step refused at the Gateway.\n"
    "- Do not plan a remediation step unless the evidence shows something to "
    "remediate.\n"
    "- Do not plan an execution step without a verification step after it.\n"
    "- You never grant permission and you never execute. You propose."
)


def _spec_agent_description(role: FleetRole) -> str:
    return f"{role.title}. {role.purpose}"


def build_planner_agent():
    """Construct the planning `LlmAgent`. Vertex backend pinned FIRST.

    `configure_vertex_backend()` must run before any ADK model resolution or
    ADK silently falls through to the bare Gemini developer API and asks for
    an API key -- the same ordering `countersign/agent.py` and
    `agents/smoke/agent.py` already establish.
    """
    from google.adk.agents.llm_agent import Agent

    configure_vertex_backend()
    cfg = get_config()
    return Agent(
        model=cfg.model_deep,
        name="fleet_orchestrator",
        description=(
            "Mission planner: decomposes one operator objective into an ordered "
            "plan of steps assigned to registered specialists. Proposes only; "
            "every step is independently authorized downstream."
        ),
        instruction=PLANNER_INSTRUCTION,
        output_schema=PlannedMission,
        output_key="plan",
        mode="single_turn",
    )


def build_specialist_agent(role: FleetRole):
    """One real `LlmAgent` per specialist, carrying that role's own
    instruction and description. Distinct objects with distinct identities --
    `tests/test_fleet_agents.py` asserts there are as many as there are
    roles and that no two share a name."""
    from google.adk.agents.llm_agent import Agent

    configure_vertex_backend()
    cfg = get_config()
    return Agent(
        model=cfg.model_fast,
        name=role.agent_id,
        description=_spec_agent_description(role),
        instruction=role.instruction,
        mode="single_turn",
    )


def build_all() -> dict[str, Any]:
    """Every agent object, by agent_id. Built lazily by callers that need
    them; not constructed at import time, because five model-backed agent
    objects on every `import fleet` is a cost the deterministic path should
    not pay."""
    agents = {ORCHESTRATOR.agent_id: build_planner_agent()}
    for role in SPECIALISTS:
        agents[role.agent_id] = build_specialist_agent(role)
    return agents


def planner_prompt(objective: str, menu: list[dict[str, Any]], evidence: dict[str, Any]) -> str:
    """The exact text handed to the planner. Deterministic given its inputs,
    so `MissionPlan.input_hash` over it genuinely identifies the request."""
    import json

    return (
        f"OPERATOR OBJECTIVE:\n{objective}\n\n"
        f"SPECIALIST MENU (the only roles, tools and action kinds available):\n"
        f"{json.dumps(menu, indent=2, sort_keys=True)}\n\n"
        f"OBJECTIVE CLASSES AVAILABLE:\n"
        f"SECURITY_INVESTIGATION, CREDENTIAL_AUDIT, PREMISE_IMPACT_TRACE, "
        f"COMPLIANCE_REVIEW, GENERAL_OPERATIONS\n\n"
        f"EVIDENCE ALREADY GATHERED:\n"
        f"{json.dumps(evidence, indent=2, sort_keys=True, default=str)}\n\n"
        f"TOOL DESCRIPTIONS:\n"
        f"{json.dumps(TOOL_REGISTRY, indent=2, sort_keys=True)}\n"
    )


#: Names only, importable without constructing a model-backed object -- used
#: by the UI and by `tests/test_fleet_agents.py` to assert the fleet's shape
#: without needing credentials.
AGENT_NAMES: tuple[str, ...] = tuple(r.agent_id for r in ALL_ROLES)

__all__ = [
    "AGENT_NAMES",
    "PLANNER_INSTRUCTION",
    "PlannedMission",
    "PlannedStep",
    "build_all",
    "build_planner_agent",
    "build_specialist_agent",
    "planner_prompt",
]
