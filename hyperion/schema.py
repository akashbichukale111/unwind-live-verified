"""Typed models for Hyperion's Firestore collection and API surface.

Mirrors `tower/schema.py`'s discipline: every field is typed before any logic
exists. `RiskAssessment` is never a bare int -- a score with no band and no
threat label collapsed to "a number" is exactly the kind of unauditable
scoring `warrant/DESIGN.md`'s "never one number" rule already refuses one
layer over.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tower.schema import GatewayReasonCode


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    def to_firestore(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)


class RiskLevel(str, Enum):
    """A closed vocabulary, the same discipline `GatewayReasonCode` already
    uses one layer down: a risk band is a routed bucket with a name, never a
    free-text severity string.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskAssessment(_Base):
    """`hyperion/risk.py:score_decision`'s output. Deterministic and
    reproducible: the same `GatewayDecision` plus the same `risk_class`
    always folds to the same score -- see that module's docstring for the
    weight table and why it is labelled [ASSUMPTION], not measured.
    """

    reason_code: GatewayReasonCode
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    threat_type: str


class HyperionEvent(_Base):
    """One append-only entry in `hyperion_events`. Written by
    `hyperion/guard.py:evaluate_with_hyperion` for every Gateway call it
    wraps -- never edited afterward, same discipline as
    `tower/memory.py:MemoryEntry` and `warrant/ledger.py:WarrantEvent`.
    """

    event_id: str
    agent_id: str
    task: str
    capability: str | None = None
    risk_class: str
    case_id: str | None = None
    allowed: bool
    reason_code: GatewayReasonCode
    reason: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    threat_type: str
    recorded_at: datetime
