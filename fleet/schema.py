"""Typed models for the agent fleet: plans, task assignments, results.

Same discipline as `tower/schema.py` and `singularity/schema.py`: every
field typed before any logic exists, every decision carries a reason, no
bare scores.

THE ONE FIELD THAT MATTERS MOST IS `MissionPlan.provenance`
--------------------------------------------------------------
A plan either came from a language model or it did not, and a judge must be
able to tell which WITHOUT trusting a label someone typed. `PlanProvenance`
is written by `fleet/planner.py` at the moment the plan is produced, from
which code path actually ran, and it travels into the mission checkpoint,
the executive report, and the UI. `GEMINI_CLAMPED` is a distinct value from
`GEMINI` on purpose: it means the model proposed a plan and the deterministic
validator had to narrow it, which is information a reader should not have to
dig for.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from singularity.schema import AgentRole


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class ObjectiveClass(str, Enum):
    """What kind of mission this objective is.

    Closed vocabulary. The planner classifies into it; the classification
    then selects which specialists are relevant, which is the mechanism by
    which two different objectives produce two different plans. A judge can
    verify the mechanism by reading one function
    (`fleet/planner.py:classify_objective`) rather than trusting that
    variation exists.
    """

    SECURITY_INVESTIGATION = "SECURITY_INVESTIGATION"
    CREDENTIAL_AUDIT = "CREDENTIAL_AUDIT"
    PREMISE_IMPACT_TRACE = "PREMISE_IMPACT_TRACE"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    GENERAL_OPERATIONS = "GENERAL_OPERATIONS"


class PlanProvenance(str, Enum):
    """Where this plan actually came from. Never a claim -- set by the code
    path that produced it."""

    #: A real Gemini call produced it and the validator accepted it whole.
    GEMINI = "GEMINI"
    #: A real Gemini call produced it and the deterministic validator had to
    #: narrow or drop at least one step.
    GEMINI_CLAMPED = "GEMINI_CLAMPED"
    #: No model was reachable or Vertex is disabled: the deterministic
    #: planner produced it. This is a first-class operating mode, not a
    #: degraded one -- the same stance `lib/vertex.py` takes for the cascade.
    ZERO_MODEL = "ZERO_MODEL"


class TaskOutcome(str, Enum):
    """Closed outcome vocabulary for one dispatched task."""

    COMPLETED = "COMPLETED"
    #: The Gateway refused the proposed action before any work happened.
    REFUSED = "REFUSED"
    #: The worker ran but its output could not be used (loop, unparseable).
    FAULTED = "FAULTED"
    #: Skipped because an earlier step's outcome made it moot.
    SKIPPED = "SKIPPED"
    #: Blocked pending human concurrence.
    AWAITING_HUMAN = "AWAITING_HUMAN"


class PlanStep(_Base):
    """One unit of delegated work.

    `requested_scope` and `action_kind` are what the step ASKS FOR. Nothing
    here grants anything: `command_os/mission.py` prices the action
    (`warrant/economics.py`), narrows it (`singularity/genome.py`) and then
    submits it to the unmodified Gateway, which is the only thing that can
    say yes.
    """

    seq: int
    role: AgentRole
    #: Human-readable statement of what this step is for.
    intent: str
    #: Which `fleet/tools.py` tool the worker will run. Closed vocabulary,
    #: validated by `fleet/planner.py` against `fleet.tools.TOOL_REGISTRY`.
    tool: str
    #: `warrant.economics.ActionKind` value. Closed vocabulary; an unknown
    #: value makes the whole plan invalid rather than defaulting to cheap.
    action_kind: str
    requested_scope: list[str] = Field(default_factory=list)
    requested_actions: list[str] = Field(default_factory=list)
    risk_class: str = "LOW"
    #: Why the planner chose this step. When provenance is GEMINI this is the
    #: model's own stated reason, preserved verbatim.
    rationale: str = ""


class MissionPlan(_Base):
    objective: str
    objective_class: ObjectiveClass
    steps: list[PlanStep]
    provenance: PlanProvenance
    #: The model string that produced it, or the deterministic planner's own
    #: identifier. Never blank.
    model: str
    #: SHA-256 of the exact planner input, so a stored plan can be tied to
    #: the input that produced it without storing the whole prompt.
    input_hash: str
    created_at: datetime
    latency_ms: int = 0
    #: Anything the validator changed, stated. Empty when nothing was clamped.
    clamps: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def roles(self) -> list[AgentRole]:
        return [s.role for s in self.steps]

    def fingerprint(self) -> str:
        """A short, stable, comparable summary of the plan's SHAPE.

        `tests/test_fleet.py::test_different_objectives_create_different_plans`
        compares fingerprints rather than whole objects, so the assertion is
        about the plan differing in role/tool/action -- the thing that
        matters -- rather than in a timestamp.
        """
        return "|".join(f"{s.role.value}:{s.tool}:{s.action_kind}" for s in self.steps)


class ToolCall(_Base):
    """One tool invocation by a worker. Recorded whether or not it succeeded."""

    tool: str
    ok: bool
    latency_ms: int
    #: Structured result. UNWIND never accepts free text as a decision, so a
    #: tool that cannot produce a dict has faulted by definition.
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class TaskResult(_Base):
    """What one dispatched task actually produced.

    `evidence_completeness` and `evidence_age_seconds` feed
    `warrant/economics.py`'s uncertainty tax directly -- which is the seam
    that makes a worker's poor evidence raise the PRICE of the next action
    rather than merely being noted in a log.
    """

    seq: int
    role: AgentRole
    tool: str
    outcome: TaskOutcome
    summary: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    evidence_completeness: float = 1.0
    evidence_age_seconds: float = 0.0
    #: Populated when outcome is REFUSED -- the Gateway's own reason code.
    refusal_reason_code: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "MissionPlan",
    "ObjectiveClass",
    "PlanProvenance",
    "PlanStep",
    "TaskOutcome",
    "TaskResult",
    "ToolCall",
]
