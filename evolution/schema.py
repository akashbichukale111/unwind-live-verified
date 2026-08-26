"""Typed models for trajectory evaluation and governed agent evolution.

Same discipline the rest of this repository already uses (`command_os/
schema.py`, `hyperion/schema.py`, `singularity/schema.py`): every field is
typed before any logic exists, and no field is a decorative number.

WHAT THIS PACKAGE ADDS THAT `evals/` DOES NOT ALREADY DO
-----------------------------------------------------------
`evals/` marks the cascade's ANSWER against `corpus/data/radius_truth.jsonl`
-- it asks "was the retraction set right?". That is an outcome metric and it
stays exactly as it is.

This package asks a different question: "did the agent BEHAVE well getting
there?". A mission can reach a correct answer having ignored a refusal,
burned three retries, acted on 40%-parsed evidence and skipped the human
gate. `evals/` scores that mission identically to a clean one. `evolution/`
does not.

Both are needed. An agent scored only on outcome learns to reach outcomes by
any means; that is the failure mode this package exists to close.

NOTHING HERE IS A MODEL'S SELF-REPORT
----------------------------------------
Every criterion in `evolution/criteria.py` is a pure function of fields that
`command_os/mission.py` MEASURED during the run -- `steps_executed`,
`gateway_refusals`, `worker_faults`, `evidence_completeness`,
`unsafe_actions_executed`, `verified`. An agent cannot score itself well by
saying it did well; there is no field here it writes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CriterionKey(str, Enum):
    """The seven behavioural criteria. Closed vocabulary: a criterion that is
    not on this list cannot be scored, so a candidate version cannot invent a
    flattering one."""

    TASK_SUCCESS = "TASK_SUCCESS"
    POLICY_COMPLIANCE = "POLICY_COMPLIANCE"
    TOOL_CORRECTNESS = "TOOL_CORRECTNESS"
    CONTEXT_QUALITY = "CONTEXT_QUALITY"
    RISK_DISCIPLINE = "RISK_DISCIPLINE"
    RECOVERY = "RECOVERY"
    EFFICIENCY = "EFFICIENCY"


class CriterionScore(BaseModel):
    """One criterion's result for one mission.

    `observed` carries the raw measured quantities the score was computed
    from, so a reader can recompute the score by hand from this record alone
    and does not have to trust it. That is the same contract
    `evidence/INDEX.md` holds every number in this repository to.
    """

    model_config = ConfigDict(extra="forbid")

    key: CriterionKey
    name: str
    #: 0.0 -- 1.0. Deterministic. Never sampled, never model-assigned.
    score: float
    weight: float
    #: Raw measured inputs. Recompute `score` from these to check it.
    observed: dict[str, Any] = Field(default_factory=dict)
    #: Human-readable statement of what was expected.
    expected: str = ""
    passed: bool = True
    #: Present only when `passed` is False. Names the behaviour, not a fix.
    failure: str = ""


class TrajectoryEvaluation(BaseModel):
    """The full behavioural evaluation of one mission run.

    `composite` is a weighted mean, and it is reported ALONGSIDE the per
    criterion scores -- never instead of them. This repository has refused a
    single blended trust number twice already (`command_os/trust.py`,
    `warrant/DESIGN.md`); the composite exists to order two candidate
    versions against each other in `evolution/promote.py`, and
    `promote.py` additionally requires that NO individual criterion
    regressed. A candidate cannot buy a promotion by trading risk discipline
    for efficiency.
    """

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    mission_id: str
    #: The agent version under evaluation. Ties a score to the exact
    #: instruction/policy text that produced it.
    agent_version_id: str
    agent_key: str
    objective: str
    objective_class: str

    criteria: list[CriterionScore] = Field(default_factory=list)
    composite: float = 0.0
    failures: list[str] = Field(default_factory=list)

    #: The three traces. Each is folded from the run, not narrated.
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    policy_trace: list[dict[str, Any]] = Field(default_factory=list)
    context_trace: list[dict[str, Any]] = Field(default_factory=list)

    #: The mission's own terminal status, carried verbatim so an evaluation
    #: can never read better than the mission it scores.
    outcome: str = ""
    created_at: datetime


class VersionStatus(str, Enum):
    """Lifecycle of an agent version. A version is only ever ACTIVE because a
    human promoted it; nothing in this package sets ACTIVE on its own."""

    #: Proposed by the evolution loop, never yet run in production.
    CANDIDATE = "CANDIDATE"
    #: Serving. Exactly one per `agent_key` at a time.
    ACTIVE = "ACTIVE"
    #: Was ACTIVE, replaced by a later promotion.
    SUPERSEDED = "SUPERSEDED"
    #: Evaluated and refused. Kept, never deleted -- a rejected candidate is
    #: evidence about the loop's judgement and is part of the audit record.
    REJECTED = "REJECTED"
    #: Was ACTIVE, promoted, then rolled back after a regression.
    ROLLED_BACK = "ROLLED_BACK"


class AgentVersion(BaseModel):
    """An immutable, content-addressed version of one agent's instruction and
    bounded policy.

    IMMUTABILITY IS THE POINT
    ----------------------------
    `version_id` is a hash of (`agent_key`, `instruction`, `policy`). Two
    versions with the same text ARE the same version, and a version's text
    can never change under a score that was computed for it. An evaluation
    therefore always refers to text that still exists in exactly the form it
    was scored in.

    WHAT A VERSION MAY AND MAY NOT CARRY
    ---------------------------------------
    `instruction` is prose handed to a model. `policy` is a small dict of
    BOUNDED, NUMERIC-OR-BOOLEAN operating preferences -- see
    `evolution/propose.py:MUTABLE_POLICY_KEYS`. A version carries NO scope,
    NO tool list, NO warrant schedule and NO risk threshold: those live in
    `fleet/roles.py` and are enforced by `tower/gateway.py`, which this
    package never writes to. So the strongest thing the evolution loop can
    ever do is change what an agent is TOLD; it can never change what an
    agent is ALLOWED. `tests/test_evolution_promote.py` proves that a
    candidate carrying a scope key is refused.
    """

    model_config = ConfigDict(extra="forbid")

    version_id: str
    agent_key: str
    #: Monotonic per `agent_key`, for human legibility ("Agent Version 3").
    version_n: int
    instruction: str
    policy: dict[str, Any] = Field(default_factory=dict)
    status: VersionStatus = VersionStatus.CANDIDATE
    #: The version this one was derived from. None for the seed version.
    parent_version_id: str | None = None
    #: How the TEXT was produced. See `ProposalProvenance`.
    provenance: str = "SEED"
    model: str = ""
    created_at: datetime
    #: Set only by `evolution/promote.py`, only after the gates passed, and
    #: only ever to an AUTHENTICATED human principal.
    promoted_at: datetime | None = None
    promoted_by: str | None = None
    rolled_back_at: datetime | None = None
    rollback_reason: str = ""


class ProposalProvenance(str, Enum):
    """Where a candidate's text actually came from. Set by the code path that
    produced it, never claimed -- exactly `fleet/schema.py:PlanProvenance`'s
    contract, reused deliberately so a judge only has to learn it once."""

    #: A real Gemini call produced it and the validator accepted it whole.
    GEMINI = "GEMINI"
    #: A real Gemini call produced it and the validator had to narrow it.
    GEMINI_CLAMPED = "GEMINI_CLAMPED"
    #: No model was reachable or Vertex is disabled: the deterministic
    #: proposer produced it from the failure analysis. A first-class mode.
    ZERO_MODEL = "ZERO_MODEL"
    #: The hand-written starting version. Not proposed by anything.
    SEED = "SEED"


class EvolutionProposal(BaseModel):
    """One improvement proposal: an analysis of what failed, and the
    candidate version generated from it."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    agent_key: str
    from_version_id: str
    candidate_version_id: str
    #: The failing criteria this proposal is a response to, folded from real
    #: evaluations. A proposal with an empty analysis is not generated.
    failure_analysis: list[dict[str, Any]] = Field(default_factory=list)
    #: Exactly what changed, field by field, so a reviewer diffs a list
    #: rather than two prose blobs.
    changes: list[dict[str, Any]] = Field(default_factory=list)
    provenance: ProposalProvenance = ProposalProvenance.ZERO_MODEL
    model: str = ""
    #: Narrowings the validator applied to a model's proposal. Named, never
    #: silent -- same contract as `MissionPlan.clamps`.
    clamps: list[str] = Field(default_factory=list)
    #: Evaluations this proposal was derived from, by id.
    source_evaluation_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class PromotionOutcome(str, Enum):
    PROMOTED = "PROMOTED"
    #: A gate refused. `PromotionDecision.reasons` says which and why.
    REFUSED = "REFUSED"
    #: Gates passed; waiting on an authenticated human. The candidate is NOT
    #: serving in this state.
    AWAITING_HUMAN = "AWAITING_HUMAN"
    ROLLED_BACK = "ROLLED_BACK"


class PromotionDecision(BaseModel):
    """The record of one promotion attempt.

    THE PROPERTY THAT MATTERS
    ----------------------------
    `human_principal` is an AUTHENTICATED caller carried from
    `require_human_principal`, never a module constant and never an agent.
    `evolution/promote.py:promote` raises if the principal is an
    `agent::` principal, so a model cannot authorise its own promotion even
    if it reaches the function. `tests/test_evolution_promote.py` asserts
    that directly.
    """

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    agent_key: str
    baseline_version_id: str
    candidate_version_id: str
    outcome: PromotionOutcome
    #: Every gate's finding, in the order the gates ran.
    reasons: list[str] = Field(default_factory=list)
    baseline_composite: float = 0.0
    candidate_composite: float = 0.0
    #: Per-criterion regressions. Non-empty means the promotion is refused,
    #: regardless of what the composite did.
    regressions: list[dict[str, Any]] = Field(default_factory=list)
    #: Scenario-level results behind the two composites.
    comparison: list[dict[str, Any]] = Field(default_factory=list)
    human_principal: str | None = None
    #: The independent challenger's verdict, when one ran.
    countersign: str | None = None
    created_at: datetime


__all__ = [
    "AgentVersion",
    "CriterionKey",
    "CriterionScore",
    "EvolutionProposal",
    "PromotionDecision",
    "PromotionOutcome",
    "ProposalProvenance",
    "TrajectoryEvaluation",
    "VersionStatus",
]
