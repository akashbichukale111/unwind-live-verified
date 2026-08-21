"""Typed models for Singularity-Mesh's two live decision engines
(`singularity/genome.py`, `singularity/behavior.py`) and the append-only log
they write to (`singularity/mesh_memory.py`).

Same discipline `hyperion/schema.py` and `tower/schema.py` already use:
every field is typed before any logic exists, and every score carries a
band and a reason -- never a bare number.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    def to_firestore(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)


class RiskLevel(str, Enum):
    """Same closed vocabulary as `hyperion.schema.RiskLevel`, defined here
    rather than imported so this package's zero-model import graph
    (`tests/test_singularity_zero_model.py`) never has to reach into
    `hyperion/` for a plain enum."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GenomeDecision(str, Enum):
    """The Capability Genome's closed outcome vocabulary -- an agent's
    request for this task is either granted in full, granted with some
    requested actions stripped, or denied outright."""

    ALLOW = "ALLOW"
    RESTRICT = "RESTRICT"
    DENY = "DENY"


class DriftBand(str, Enum):
    """Behavioral DNA's closed outcome vocabulary. NORMAL takes no action;
    ELEVATED and above trigger `capability_action`."""

    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    DRIFT = "DRIFT"
    CRITICAL = "CRITICAL"


class CapabilityAction(str, Enum):
    NONE = "NONE"
    RESTRICT = "RESTRICT"
    ISOLATE = "ISOLATE"


class AgentRole(str, Enum):
    """The fleet roles `singularity/fleet.py` describes and
    `singularity/genome.py` grants a base capability set to."""

    SENTINEL = "SENTINEL"
    ORCHESTRATOR = "ORCHESTRATOR"
    WORKER_SQL = "WORKER_SQL"
    WORKER_PYTHON = "WORKER_PYTHON"
    WORKER_DOCUMENT = "WORKER_DOCUMENT"
    WORKER_BROWSER = "WORKER_BROWSER"
    WORKER_COMPLIANCE = "WORKER_COMPLIANCE"


class CapabilityGenome(_Base):
    """`singularity/genome.py:compute_genome`'s output: the dynamic,
    task-bound capability identity for one agent, one task, one risk
    context -- never a standing, permanent grant."""

    agent_role: AgentRole
    task: str
    risk_class: str
    requested_actions: list[str]
    allowed_actions: list[str]
    denied_actions: list[str]
    risk_level: RiskLevel
    decision: GenomeDecision
    reason: str


class BehaviorObservation(_Base):
    """One agent's observed behaviour for a task, compared against its
    baseline profile by `singularity/behavior.py:detect_drift`."""

    agent_role: AgentRole
    tool_calls: int
    dataset: str
    latency_ms: int
    requested_export: bool = False
    requested_secret_access: bool = False


class DriftAssessment(_Base):
    """`detect_drift`'s output: a scored, banded comparison against the
    agent's `BehaviorProfile` baseline -- never a bare "anomalous" flag."""

    agent_role: AgentRole
    drift_score: int = Field(ge=0, le=100)
    drift_band: DriftBand
    capability_action: CapabilityAction
    signals: list[str]
    observation: BehaviorObservation


class MeshEvent(_Base):
    """One append-only entry in `singularity_mesh_events`. Written by either
    a Capability Genome negotiation or a Behavioral DNA assessment -- never
    edited afterward, same contract `hyperion/schema.py:HyperionEvent`
    already keeps for its own log."""

    event_id: str
    kind: str  # "genome" | "behavior"
    agent_role: str
    risk_level: RiskLevel
    allowed: bool
    reason_code: str
    reason: str
    detail: dict[str, Any]
    recorded_at: datetime
