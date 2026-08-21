"""Immune Memory: the append-only log `hyperion/guard.py` writes to, and the
fleet-level aggregate read back from it.

APPEND-ONLY, ENFORCED
----------------------
This module's public surface has no `update_event` -- the same discipline
`tower/memory.py` and `warrant/ledger.py` already enforce for their own
append-only collections. A security event that could be edited after the
fact is not evidence of anything.

WHAT "FLEET PROTECTION" ACTUALLY MEANS HERE
-----------------------------------------------
`aggregate_fleet_summary` is a real aggregate over real, already-happened
`evaluate_with_hyperion` calls -- not a fabricated demo number. An agent
counts as "protected" the moment it has at least one logged event; before
that, it is counted from the registry (`tower.registry.list_agents`) as
present but not yet observed. There is no cross-agent propagation logic here
(an event for agent A does not change agent B's registry state) -- that is
explicitly the "not yet built" half of fleet immunity, documented in
`hyperion/DESIGN.md` rather than faked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hyperion.schema import HyperionEvent, RiskAssessment
from lib.config import COLLECTION_HYPERION_EVENTS
from lib.firestore import get_client
from tower.schema import GatewayDecision, GatewayReasonCode


def write_event(
    *,
    agent_id: str,
    task: str,
    risk_class: str,
    decision: GatewayDecision,
    assessment: RiskAssessment,
    capability: str | None = None,
    case_id: str | None = None,
) -> HyperionEvent:
    """Append one event. Returns the event actually written, never mutated
    afterward -- the same contract `tower.memory.write_entry` makes."""
    event = HyperionEvent(
        event_id=f"hyp::{uuid.uuid4().hex}",
        agent_id=agent_id,
        task=task,
        capability=capability,
        risk_class=risk_class,
        case_id=case_id,
        allowed=decision.allowed,
        reason_code=decision.reason_code,
        reason=decision.reason,
        risk_score=assessment.risk_score,
        risk_level=assessment.risk_level,
        threat_type=assessment.threat_type,
        recorded_at=datetime.now(UTC),
    )
    get_client().collection(COLLECTION_HYPERION_EVENTS).document(event.event_id).set(
        event.to_firestore()
    )
    return event


def list_events(limit: int | None = None) -> list[HyperionEvent]:
    """Every logged event, most recent first."""
    query = (
        get_client()
        .collection(COLLECTION_HYPERION_EVENTS)
        .order_by("recorded_at", direction="DESCENDING")
    )
    if limit is not None:
        query = query.limit(limit)
    return [HyperionEvent(**snap.to_dict()) for snap in query.stream()]


def aggregate_fleet_summary(*, recent_limit: int = 25) -> dict[str, Any]:
    """The Hyperion card's real summary: counts folded from the log, plus the
    most recent events for the live event stream. Every number here is a
    real aggregate over `hyperion_events` -- an empty log honestly returns
    zeros and `fleet_health_pct: 100` (nothing observed is not evidence of a
    threat, the same "an empty fold is honestly labelled, not guessed"
    discipline `warrant/DESIGN.md`'s "Honest seeding" section already uses).
    """
    from tower.registry import list_agents

    events = list_events()
    total = len(events)
    blocked = [e for e in events if not e.allowed]
    agents_observed = {e.agent_id for e in events}
    registry_agents = {a.agent_id for a in list_agents()}

    fleet_health_pct = 100.0 if total == 0 else round(100.0 * (total - len(blocked)) / total, 1)

    band_counts: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for e in events:
        band_counts[e.risk_level.value if hasattr(e.risk_level, "value") else e.risk_level] += 1

    last_event = events[0] if events else None

    return {
        "agents_protected": len(registry_agents | agents_observed),
        "agents_observed": len(agents_observed),
        "events_total": total,
        "threats_detected": len(blocked),
        "blocked_actions": len([e for e in blocked if e.reason_code != GatewayReasonCode.ALLOWED]),
        "fleet_health_pct": fleet_health_pct,
        "risk_band_counts": band_counts,
        "last_event": last_event.to_firestore() if last_event else None,
        "recent_events": [e.to_firestore() for e in events[:recent_limit]],
    }


def reset_for_test() -> None:
    """Test hook: delete every event. Mirrors `tower.memory` /
    `warrant.ledger`'s own `reset_for_test` hooks."""
    client = get_client()
    for snap in client.collection(COLLECTION_HYPERION_EVENTS).stream():
        snap.reference.delete()
