"""Persistence for evaluations, versions, proposals and promotion decisions.

APPEND-ONLY, WITH ONE NAMED EXCEPTION
----------------------------------------
Evaluations, proposals and decisions are append-only: there is no update
function for any of them on this module's public surface. That is the same
contract `command_os/checkpoint.py`, `hyperion/immune_memory.py` and
`singularity/mesh_memory.py` already hold to.

Versions are the exception, and the exception is deliberate and narrow:
`set_status` exists because a version's LIFECYCLE genuinely changes (a
CANDIDATE becomes ACTIVE, an ACTIVE becomes SUPERSEDED). It can change
`status`, `promoted_at`, `promoted_by`, `rolled_back_at` and
`rollback_reason` and NOTHING ELSE -- the instruction and policy are
content-addressed by `version_id`, so mutating them would produce a document
whose id no longer describes its contents. `set_status` therefore refuses
any other field, and `tests/test_evolution_versions.py` asserts that.

QUERY SHAPE
--------------
Every read here is scoped to one collection and ordered by a single field,
or filtered by a single equality with no ordering -- deliberately never a
`.where()` combined with an `.order_by()` on a different field, which is
what forced `decision_memory`'s composite index (see `docs/DEPLOY.md`). This
module needs no new entry in `infra/indexes.json`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from evolution.schema import (
    AgentVersion,
    EvolutionProposal,
    PromotionDecision,
    TrajectoryEvaluation,
    VersionStatus,
)
from lib.firestore import get_client

COLLECTION_EVALUATIONS = "evolution_evaluations"
COLLECTION_VERSIONS = "evolution_versions"
COLLECTION_PROPOSALS = "evolution_proposals"
COLLECTION_DECISIONS = "evolution_decisions"

#: The only fields `set_status` may touch. Everything else about a version is
#: content-addressed and therefore immutable by construction.
_MUTABLE_VERSION_FIELDS = frozenset(
    {"status", "promoted_at", "promoted_by", "rolled_back_at", "rollback_reason"}
)


def _col(name: str):
    return get_client().collection(name)


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------


def write_evaluation(evaluation: TrajectoryEvaluation) -> TrajectoryEvaluation:
    """Content-addressed id, so re-scoring an unchanged mission overwrites an
    identical document rather than creating a second row that would read as a
    second measurement."""
    _col(COLLECTION_EVALUATIONS).document(evaluation.evaluation_id).set(
        evaluation.model_dump(mode="json")
    )
    return evaluation


def get_evaluation(evaluation_id: str) -> TrajectoryEvaluation | None:
    snap = _col(COLLECTION_EVALUATIONS).document(evaluation_id).get()
    return TrajectoryEvaluation(**snap.to_dict()) if snap.exists else None


def list_evaluations(*, limit: int = 50) -> list[TrajectoryEvaluation]:
    query = _col(COLLECTION_EVALUATIONS).order_by("created_at").limit(limit)
    return [TrajectoryEvaluation(**s.to_dict()) for s in query.stream()]


def evaluations_for_mission(mission_id: str) -> list[TrajectoryEvaluation]:
    """Single equality filter, no ordering -- no composite index required."""
    query = _col(COLLECTION_EVALUATIONS).where("mission_id", "==", mission_id)
    rows = [TrajectoryEvaluation(**s.to_dict()) for s in query.stream()]
    return sorted(rows, key=lambda e: e.created_at)


def evaluations_for_version(version_id: str) -> list[TrajectoryEvaluation]:
    query = _col(COLLECTION_EVALUATIONS).where("agent_version_id", "==", version_id)
    rows = [TrajectoryEvaluation(**s.to_dict()) for s in query.stream()]
    return sorted(rows, key=lambda e: e.created_at)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def write_version(version: AgentVersion) -> AgentVersion:
    _col(COLLECTION_VERSIONS).document(version.version_id).set(version.model_dump(mode="json"))
    return version


def get_version(version_id: str) -> AgentVersion | None:
    snap = _col(COLLECTION_VERSIONS).document(version_id).get()
    return AgentVersion(**snap.to_dict()) if snap.exists else None


def list_versions(*, agent_key: str | None = None) -> list[AgentVersion]:
    col = _col(COLLECTION_VERSIONS)
    if agent_key:
        rows = [
            AgentVersion(**s.to_dict()) for s in col.where("agent_key", "==", agent_key).stream()
        ]
    else:
        rows = [AgentVersion(**s.to_dict()) for s in col.stream()]
    return sorted(rows, key=lambda v: (v.agent_key, v.version_n))


def active_version(agent_key: str) -> AgentVersion | None:
    """The one version serving for this agent, or None.

    Returns the HIGHEST `version_n` among ACTIVE rows rather than the first
    found. If two rows were ever ACTIVE at once -- which `promote` makes
    impossible, but a partial write could in principle leave behind -- the
    newer one wins and `tests/test_evolution_promote.py` covers the case
    explicitly, because silently picking an arbitrary one is how a rollback
    quietly fails to take effect.
    """
    actives = [v for v in list_versions(agent_key=agent_key) if v.status is VersionStatus.ACTIVE]
    if not actives:
        return None
    return max(actives, key=lambda v: v.version_n)


def next_version_n(agent_key: str) -> int:
    existing = list_versions(agent_key=agent_key)
    return (max((v.version_n for v in existing), default=0)) + 1


def set_status(
    version_id: str,
    status: VersionStatus,
    *,
    promoted_by: str | None = None,
    rollback_reason: str = "",
    now: datetime | None = None,
    **forbidden: Any,
) -> AgentVersion:
    """Lifecycle transition. Refuses any field outside `_MUTABLE_VERSION_FIELDS`.

    `**forbidden` exists purely to catch a future caller that tries to smuggle
    an instruction change through the one function that is allowed to write to
    an existing version document.
    """
    if forbidden:
        raise ValueError(
            f"set_status may only change {sorted(_MUTABLE_VERSION_FIELDS)}; "
            f"refused: {sorted(forbidden)}"
        )
    version = get_version(version_id)
    if version is None:
        raise ValueError(f"unknown version {version_id!r}")
    now = now or datetime.now(UTC)
    patch: dict[str, Any] = {"status": status.value}
    if status is VersionStatus.ACTIVE:
        patch["promoted_at"] = now.isoformat()
        patch["promoted_by"] = promoted_by
    if status is VersionStatus.ROLLED_BACK:
        patch["rolled_back_at"] = now.isoformat()
        patch["rollback_reason"] = rollback_reason
    _col(COLLECTION_VERSIONS).document(version_id).set(patch, merge=True)
    updated = get_version(version_id)
    assert updated is not None
    return updated


def ensure_seeded(now: datetime | None = None) -> list[AgentVersion]:
    """Write version 1 for every role that has no version yet.

    Idempotent by content address: re-running writes the identical document
    to the identical id. A role whose instruction text has since changed gets
    a NEW seed id rather than a mutated old one, which is correct -- it is a
    different version, and the old evaluations still refer to the old text.
    """
    from evolution.versions import seed_versions

    written: list[AgentVersion] = []
    for seed in seed_versions(now=now):
        if get_version(seed.version_id) is None:
            written.append(write_version(seed))
    return written


# ---------------------------------------------------------------------------
# Proposals and decisions -- append-only, no update surface at all
# ---------------------------------------------------------------------------


def write_proposal(proposal: EvolutionProposal) -> EvolutionProposal:
    _col(COLLECTION_PROPOSALS).document(proposal.proposal_id).set(proposal.model_dump(mode="json"))
    return proposal


def get_proposal(proposal_id: str) -> EvolutionProposal | None:
    snap = _col(COLLECTION_PROPOSALS).document(proposal_id).get()
    return EvolutionProposal(**snap.to_dict()) if snap.exists else None


def list_proposals(*, limit: int = 50) -> list[EvolutionProposal]:
    query = _col(COLLECTION_PROPOSALS).order_by("created_at").limit(limit)
    return [EvolutionProposal(**s.to_dict()) for s in query.stream()]


def write_decision(decision: PromotionDecision) -> PromotionDecision:
    _col(COLLECTION_DECISIONS).document(decision.decision_id).set(decision.model_dump(mode="json"))
    return decision


def list_decisions(*, limit: int = 50) -> list[PromotionDecision]:
    query = _col(COLLECTION_DECISIONS).order_by("created_at").limit(limit)
    return [PromotionDecision(**s.to_dict()) for s in query.stream()]


def reset_for_test() -> None:
    """Delete every document this package owns. Test-only, and it says so."""
    for name in (
        COLLECTION_EVALUATIONS,
        COLLECTION_VERSIONS,
        COLLECTION_PROPOSALS,
        COLLECTION_DECISIONS,
    ):
        for snap in _col(name).stream():
            snap.reference.delete()


__all__ = [
    "COLLECTION_DECISIONS",
    "COLLECTION_EVALUATIONS",
    "COLLECTION_PROPOSALS",
    "COLLECTION_VERSIONS",
    "active_version",
    "ensure_seeded",
    "evaluations_for_mission",
    "evaluations_for_version",
    "get_evaluation",
    "get_proposal",
    "get_version",
    "list_decisions",
    "list_evaluations",
    "list_proposals",
    "list_versions",
    "next_version_n",
    "reset_for_test",
    "set_status",
    "write_decision",
    "write_evaluation",
    "write_proposal",
    "write_version",
]
