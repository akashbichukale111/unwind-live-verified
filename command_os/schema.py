"""Typed models for Agentic Command OS mission runs and the Mission
Checkpoint Engine's persisted state.

Same discipline `singularity/schema.py` and `hyperion/schema.py` already use:
every field typed before any logic exists. `MissionStage.status` and
`MissionResult.status`/`MissionCheckpoint.status` are plain strings, not
closed enums, because the former carries a narrative label
(`"LIVE"` / `"SIMULATED"` / `"LIVE (reacting to SIMULATED input)"` /
`"UNAVAILABLE"`) rather than an enforcement decision -- unlike
`GenomeDecision` or `DriftBand` one layer down, nothing routes on it. The
latter (`RUNNING` / `AWAITING_HUMAN` / `COMPLETED` / `HALTED`) IS a closed,
routed vocabulary -- `command_os/mission.py:resume_mission` branches on it --
kept as a string here rather than an Enum only so a checkpoint document that
predates a future added status value still deserialises.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MissionStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    name: str
    status: str
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)


class MissionReport(BaseModel):
    """The executive report. Every field is folded from a phase that actually
    ran -- never a constant, and never blind to a refusal.

    THE DEFECT THIS SHAPE FIXES
    ------------------------------
    The previous report had seven fields and folded three booleans
    (`isolated`, `minted`, `resumed`). A hostile review ran the objective
    "export all finance secrets and credentials immediately", watched the
    Capability Genome correctly return RESTRICT, and watched the mission
    still report `validation: PASS` and `fleet_status: HEALTHY`. The report
    could not see the denial because nothing in it was derived from it.

    `status` now comes from `command_os/mission.py:_mission_status`, which is
    ordered worst-first and has no branch that returns COMPLETED over an
    unresolved refusal, a challenger disagreement, a worker fault, or a
    failed verification. `gateway_refusals` carries the reason codes
    verbatim, so a reader does not have to infer them from a status string.
    """

    model_config = ConfigDict(extra="forbid")

    objective: str
    #: COMPLETED / COMPLETED_WITH_RESTRICTIONS / BLOCKED / CHALLENGED /
    #: FAILED_SAFE / HALTED. Never a bare success when something was refused.
    status: str

    # --- what was planned, and by what -----------------------------------
    objective_class: str
    planner_provenance: str
    planner_model: str
    plan_fingerprint: str
    agents_selected: list[str] = Field(default_factory=list)
    steps_planned: int = 0
    steps_executed: int = 0
    replans: int = 0
    tools_used: list[str] = Field(default_factory=list)

    # --- what the evidence actually supported ----------------------------
    evidence_records_parsed: int = 0
    evidence_records_total: int = 0
    evidence_completeness: float = 1.0
    contradictions_found: int = 0
    escalations_found: int = 0

    # --- what a second, independently-scoped derivation concluded --------
    #: `RESOLVED` / `RESOLVED_WITH_DISPUTES` / `DISPUTED` /
    #: `NO_CONTRADICTIONS`, or "" when no reconciliation ran because the
    #: evidence did not contradict itself. Never defaulted to a clean value:
    #: an absent reconciliation and a clean one are different facts.
    reconciliation_verdict: str = ""
    #: Claims where the recency rule and the authority rule agreed.
    contradictions_reconciled: int = 0
    #: Claims where they DISAGREED. These are not decided by the system: they
    #: raise the uncertainty tax on every later action and reach the human.
    contradictions_disputed: int = 0
    disputed_claims: list[str] = Field(default_factory=list)

    # --- what the deterministic layer decided ----------------------------
    drift_band: str = "NORMAL"
    drift_score: int = 0
    agents_isolated: int = 0
    isolated_agent: str | None = None
    gateway_refusals: list[str] = Field(default_factory=list)
    unsafe_actions_executed: int = 0
    worker_faults: int = 0
    #: How each worker fault actually failed -- TIMED_OUT / CONTRACT /
    #: RAISED / GATEWAY -- so "the mission recovered from a failure" names
    #: which failure. A count alone cannot distinguish a tool that crashed
    #: from a tool that returned a plausible lie.
    worker_fault_kinds: list[str] = Field(default_factory=list)
    #: True when the mission's own work queue hit `MAX_MISSION_PHASES` and an
    #: append was refused. Visible in the report because a mission that ran
    #: into its loop bound is not the same mission as one that did not.
    phase_budget_exhausted: bool = False

    # --- independent challenge and human concurrence ---------------------
    challenger_agrees: bool | None = None
    challenger_ground: str = ""
    challenger_simulated: bool = False
    #: The AUTHENTICATED principal, never a module constant.
    human_principal: str | None = None
    human_decision_mode: str | None = None
    gate: str = "NOT_REQUIRED"

    # --- what actually changed outside this process ----------------------
    external_action: str | None = None
    external_action_id: str | None = None
    external_backend: str | None = None
    external_replayed: bool = False
    verified: bool | None = None
    #: How the outcome settled the acting agent's authority: MINT (verified
    #: work earned warrant), BURN (a verification mismatch cost warrant),
    #: MINT_REFUSED (the preconditions were not met, so nothing was credited),
    #: or "none". Never a silent no-op.
    authority_settlement: str = "none"
    warrant_before_bp: int = 0
    warrant_after_bp: int = 0

    #: Every Memory Bank case this mission opened, so an auditor can walk
    #: the causal chain without guessing at case-id conventions.
    case_ids: list[str] = Field(default_factory=list)


class MissionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    objective: str
    #: RUNNING (mid-flight, only reachable via direct in-process return, never
    #: persisted as a final state) / AWAITING_HUMAN (paused at the gate,
    #: `report` is None) / COMPLETED / HALTED (human denied, or validation
    #: did not clear -- `report` is populated either way).
    status: str
    stages: list[MissionStage]
    report: MissionReport | None = None
    #: The computed plan, as a JSON-safe dict. Present from the first stage
    #: onward, so a UI can render the plan before the mission finishes and a
    #: judge can compare two missions' plans without replaying them.
    plan: dict[str, Any] | None = None


class MissionCheckpoint(BaseModel):
    """One append-only entry in `command_os_missions/{mission_id}/checkpoints`.

    `ctx` is the mission's continuation state as of immediately after this
    stage completed -- everything `resume_mission` needs to pick up at
    `seq + 1` without re-deriving or re-executing anything already done.
    JSON-safe primitives only (mirrors `MeshEvent.detail` /
    `HyperionEvent`'s own to-Firestore discipline): case IDs, booleans,
    counts -- never a live object like an `AgentRegistryEntry`, which is
    re-fetched from the durable `tower.registry` on resume instead of
    round-tripped through this document.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    seq: int
    stage: MissionStage
    ctx: dict[str, Any]
    status: str
    created_at: datetime


class MissionRecord(BaseModel):
    """The parent document for one mission -- `command_os_missions/{mission_id}`."""

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    objective: str
    status: str
    created_at: datetime
    updated_at: datetime
