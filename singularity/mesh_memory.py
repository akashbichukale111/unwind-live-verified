"""Mesh Memory: the append-only log Singularity-Mesh's two live decision
engines write to, and the fleet-level aggregate read back from it.

Same discipline `hyperion/immune_memory.py` already establishes one card
over: APPEND-ONLY, ENFORCED (no `update_event` anywhere in this module's
public surface), and every aggregate returned is a real fold over real,
already-happened `write_genome_event` / `write_behavior_event` calls -- an
empty log honestly returns zeros, never a fabricated placeholder.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from lib.config import COLLECTION_SINGULARITY_EVENTS
from lib.firestore import get_client
from singularity.schema import CapabilityGenome, DriftAssessment, MeshEvent


def write_genome_event(genome: CapabilityGenome) -> MeshEvent:
    event = MeshEvent(
        event_id=f"sm::genome::{uuid.uuid4().hex}",
        kind="genome",
        agent_role=genome.agent_role.value,
        risk_level=genome.risk_level,
        allowed=genome.decision.value == "ALLOW",
        reason_code=genome.decision.value,
        reason=genome.reason,
        detail=genome.to_firestore(),
        recorded_at=datetime.now(UTC),
    )
    get_client().collection(COLLECTION_SINGULARITY_EVENTS).document(event.event_id).set(
        event.to_firestore()
    )
    return event


def write_behavior_event(assessment: DriftAssessment) -> MeshEvent:
    event = MeshEvent(
        event_id=f"sm::behavior::{uuid.uuid4().hex}",
        kind="behavior",
        agent_role=assessment.agent_role.value,
        risk_level=_risk_level_for_band(assessment.drift_band.value),
        allowed=assessment.capability_action.value == "NONE",
        reason_code=assessment.drift_band.value,
        reason="; ".join(assessment.signals),
        detail=assessment.to_firestore(),
        recorded_at=datetime.now(UTC),
    )
    get_client().collection(COLLECTION_SINGULARITY_EVENTS).document(event.event_id).set(
        event.to_firestore()
    )
    return event


def _risk_level_for_band(band: str) -> Any:
    from singularity.schema import RiskLevel

    return {
        "NORMAL": RiskLevel.LOW,
        "ELEVATED": RiskLevel.MEDIUM,
        "DRIFT": RiskLevel.HIGH,
        "CRITICAL": RiskLevel.CRITICAL,
    }[band]


def list_events(limit: int | None = None) -> list[MeshEvent]:
    """Every logged event, most recent first."""
    query = (
        get_client()
        .collection(COLLECTION_SINGULARITY_EVENTS)
        .order_by("recorded_at", direction="DESCENDING")
    )
    if limit is not None:
        query = query.limit(limit)
    return [MeshEvent(**snap.to_dict()) for snap in query.stream()]


def aggregate_mesh_summary(*, recent_limit: int = 25) -> dict[str, Any]:
    """The card's real summary: counts folded from the log, plus the most
    recent events for the live observability stream. Every number here is a
    real aggregate over `singularity_mesh_events`; an empty log honestly
    returns zeros (the same "an empty fold is honestly labelled, not
    guessed" discipline `hyperion/immune_memory.py:aggregate_fleet_summary`
    already uses).
    """
    events = list_events()
    total = len(events)
    genome_events = [e for e in events if e.kind == "genome"]
    behavior_events = [e for e in events if e.kind == "behavior"]
    denials = [e for e in genome_events if not e.allowed]
    isolations = [e for e in behavior_events if e.reason_code == "CRITICAL"]
    restrictions = [e for e in behavior_events if e.reason_code in ("ELEVATED", "DRIFT")]

    return {
        "events_total": total,
        "genome_events_total": len(genome_events),
        "behavior_events_total": len(behavior_events),
        "capability_denials": len(denials),
        "behavioral_isolations": len(isolations),
        "behavioral_restrictions": len(restrictions),
        "recent_events": [e.to_firestore() for e in events[:recent_limit]],
    }


def reset_for_test() -> None:
    """Test hook: delete every event. Mirrors
    `hyperion.immune_memory.reset_for_test`."""
    client = get_client()
    for snap in client.collection(COLLECTION_SINGULARITY_EVENTS).stream():
        snap.reference.delete()
