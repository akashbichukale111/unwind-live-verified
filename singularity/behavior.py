"""Behavioral DNA: monitor what an agent's activity is becoming, not just
what its last request said.

THIS MODULE IMPORTS NO FRAMEWORK AND NO MODEL CLIENT
-------------------------------------------------------
Same zero-model discipline as `singularity/genome.py` and
`hyperion/risk.py` -- `tests/test_singularity_zero_model.py` walks this
module too. Comparing an observation against a baseline range and folding
the result into a 0-100 score plus a four-value band is arithmetic, not a
trained anomaly-detection model.

CORE PRINCIPLE
---------------
"Do not just inspect what the agent says. Inspect what the agent is
becoming." `detect_drift` never looks at a single request in isolation --
it always compares an observation against a `BehaviorProfile` baseline for
that role, and the score is a sum of independent, individually-explainable
signals, never an opaque single number.
"""

from __future__ import annotations

from singularity.schema import (
    AgentRole,
    BehaviorObservation,
    CapabilityAction,
    DriftAssessment,
    DriftBand,
)


class BehaviorProfile:
    """[ASSUMPTION] A stated, reproducible baseline per role -- the "normal"
    envelope Behavioral DNA compares every observation against. Chosen to be
    demo-legible (the same discipline `hyperion/risk.py`'s weight table
    documents for itself), not measured from production traffic that does
    not exist in this repository.
    """

    __slots__ = ("tool_calls_range", "typical_datasets", "latency_ms_range", "read_only")

    def __init__(
        self,
        *,
        tool_calls_range: tuple[int, int],
        typical_datasets: tuple[str, ...],
        latency_ms_range: tuple[int, int],
        read_only: bool,
    ) -> None:
        self.tool_calls_range = tool_calls_range
        self.typical_datasets = typical_datasets
        self.latency_ms_range = latency_ms_range
        self.read_only = read_only


#: [ASSUMPTION] One baseline per role. Workers default to a read-only,
#: sales-scoped, low-tool-call, low-latency envelope; the Orchestrator's is
#: wider because delegation legitimately fans out more calls.
BASELINES: dict[AgentRole, BehaviorProfile] = {
    AgentRole.SENTINEL: BehaviorProfile(
        tool_calls_range=(1, 5),
        typical_datasets=("requests",),
        latency_ms_range=(50, 500),
        read_only=True,
    ),
    AgentRole.ORCHESTRATOR: BehaviorProfile(
        tool_calls_range=(2, 20),
        typical_datasets=("sales", "tasks"),
        latency_ms_range=(200, 3000),
        read_only=True,
    ),
    AgentRole.WORKER_SQL: BehaviorProfile(
        tool_calls_range=(1, 20),
        typical_datasets=("sales",),
        latency_ms_range=(200, 2000),
        read_only=True,
    ),
    AgentRole.WORKER_PYTHON: BehaviorProfile(
        tool_calls_range=(1, 15),
        typical_datasets=("sales",),
        latency_ms_range=(300, 4000),
        read_only=True,
    ),
    AgentRole.WORKER_DOCUMENT: BehaviorProfile(
        tool_calls_range=(1, 10),
        typical_datasets=("documents",),
        latency_ms_range=(200, 3000),
        read_only=True,
    ),
    AgentRole.WORKER_BROWSER: BehaviorProfile(
        tool_calls_range=(1, 12),
        typical_datasets=("web",),
        latency_ms_range=(300, 5000),
        read_only=True,
    ),
    AgentRole.WORKER_COMPLIANCE: BehaviorProfile(
        tool_calls_range=(1, 10),
        typical_datasets=("policy",),
        latency_ms_range=(200, 2000),
        read_only=True,
    ),
}

#: [ASSUMPTION] Weight per independently-triggered signal, ordered worst
#: first for readability only -- capped at 100 by `detect_drift`.
_WEIGHT_TOOL_CALLS_OVER = 25
_WEIGHT_UNFAMILIAR_DATASET = 30
_WEIGHT_LATENCY_OUT_OF_RANGE = 10
_WEIGHT_EXPORT_REQUEST = 25
_WEIGHT_SECRET_ACCESS = 60

_BAND_EDGES: tuple[tuple[int, DriftBand], ...] = (
    (20, DriftBand.NORMAL),
    (45, DriftBand.ELEVATED),
    (75, DriftBand.DRIFT),
    (101, DriftBand.CRITICAL),
)


def _band_for(score: int) -> DriftBand:
    for ceiling, band in _BAND_EDGES:
        if score < ceiling:
            return band
    return DriftBand.CRITICAL  # pragma: no cover -- unreachable, score clamped to 100


def _action_for(band: DriftBand) -> CapabilityAction:
    if band in (DriftBand.NORMAL, DriftBand.ELEVATED):
        return CapabilityAction.NONE if band is DriftBand.NORMAL else CapabilityAction.RESTRICT
    if band is DriftBand.DRIFT:
        return CapabilityAction.RESTRICT
    return CapabilityAction.ISOLATE


def detect_drift(observation: BehaviorObservation) -> DriftAssessment:
    """Compare one observation against its role's baseline.

    Pure function of `observation` and the fixed `BASELINES` table -- no
    I/O, no clock, no random state. Every signal that fires is named in
    `signals`, so the resulting score is always explainable, never a bare
    number (the same rule `hyperion/schema.py:RiskAssessment`'s docstring
    already states for its own scoring).
    """
    profile = BASELINES[observation.agent_role]
    score = 0
    signals: list[str] = []

    lo, hi = profile.tool_calls_range
    if observation.tool_calls > hi:
        over = observation.tool_calls - hi
        score += min(_WEIGHT_TOOL_CALLS_OVER + over, 100)
        signals.append(f"{observation.tool_calls} tool calls exceeds baseline ceiling of {hi}")
    elif observation.tool_calls < lo:
        signals.append(f"{observation.tool_calls} tool calls below baseline floor of {lo}")
        score += 5

    if observation.dataset not in profile.typical_datasets:
        score += _WEIGHT_UNFAMILIAR_DATASET
        signals.append(
            f"dataset '{observation.dataset}' outside baseline {list(profile.typical_datasets)}"
        )

    lat_lo, lat_hi = profile.latency_ms_range
    if not (lat_lo <= observation.latency_ms <= lat_hi):
        score += _WEIGHT_LATENCY_OUT_OF_RANGE
        signals.append(
            f"latency {observation.latency_ms}ms outside baseline [{lat_lo}, {lat_hi}]ms"
        )

    if observation.requested_export:
        score += _WEIGHT_EXPORT_REQUEST
        signals.append("export requested")

    if observation.requested_secret_access:
        score += _WEIGHT_SECRET_ACCESS
        signals.append("secret/credential access attempted")

    score = min(score, 100)
    band = _band_for(score)
    if not signals:
        signals.append("within baseline on every measured signal")

    return DriftAssessment(
        agent_role=observation.agent_role,
        drift_score=score,
        drift_band=band,
        capability_action=_action_for(band),
        signals=signals,
        observation=observation,
    )
